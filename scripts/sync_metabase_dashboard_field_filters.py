from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


API_BASE = os.getenv("METABASE_API_URL", "http://localhost:3001/api").rstrip("/")
API_KEY = os.getenv("METABASE_API_KEY")
DATABASE_ID = int(os.getenv("METABASE_DATABASE_ID", "2"))
DASHBOARD_ID = int(os.getenv("METABASE_DASHBOARD_ID", "3"))

if not API_KEY:
    raise SystemExit("METABASE_API_KEY is required")


def api(method: str, path: str, payload: dict | list | None = None) -> dict | list:
    data = None
    headers = {"x-api-key": API_KEY, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def find_source_name(query: str) -> str | None:
    match = re.search(r"\bFROM\s+([a-zA-Z0-9_.]+)", query, flags=re.IGNORECASE)
    return match.group(1).split(".")[-1] if match else None


def normalize_filter_clause(query: str, slugs: list[str]) -> str:
    normalized = []
    for line in query.splitlines():
        stripped = line.strip()
        replaced = False
        if stripped.startswith("[[ AND"):
            for slug in slugs:
                if f"{{{{{slug}}}}}" in line:
                    normalized.append("[[ AND {{" + slug + "}} ]]")
                    replaced = True
                    break
        if not replaced:
            normalized.append(line)
    return "\n".join(normalized)


def widget_type(slug: str) -> str:
    if slug == "ano":
        return "number/="
    if slug == "municipio":
        return "string/contains"
    return "string/="


def fetch_field_map() -> dict[str, dict[str, int]]:
    metadata = api("GET", f"/database/{DATABASE_ID}/metadata")
    result: dict[str, dict[str, int]] = {}
    for table in metadata.get("tables", []):
        if table.get("schema") != "curated":
            continue
        result[table["name"]] = {field["name"]: int(field["id"]) for field in table.get("fields", [])}
    return result


def build_template_tag(slug: str, field_id: int, current_tag: dict) -> dict:
    tag = {
        "id": current_tag.get("id"),
        "name": slug,
        "display-name": current_tag.get("display-name") or slug.replace("_", " ").title(),
        "type": "dimension",
        "required": False,
        "widget-type": widget_type(slug),
        "dimension": ["field", field_id, None],
    }
    if tag["widget-type"] == "string/contains":
        tag["options"] = {"case-sensitive": False}
    return tag


def build_parameter(slug: str, tag: dict, current_parameter: dict | None) -> dict:
    parameter = {
        "id": tag["id"],
        "type": tag["widget-type"],
        "target": ["dimension", ["template-tag", slug]],
        "name": tag["display-name"],
        "slug": slug,
        "required": False,
        "isMultiSelect": True,
    }
    if current_parameter:
        for key in ("values_query_type", "default", "options"):
            if key in current_parameter:
                parameter[key] = current_parameter[key]
    if "options" in tag:
        parameter["options"] = tag["options"]
    return parameter


def minimal_dashcard_payload(dashcard: dict, parameter_mappings: list[dict]) -> dict:
    payload = {
        "id": dashcard["id"],
        "card_id": dashcard.get("card_id"),
        "row": dashcard["row"],
        "col": dashcard["col"],
        "size_x": dashcard["size_x"],
        "size_y": dashcard["size_y"],
        "dashboard_tab_id": dashcard.get("dashboard_tab_id"),
        "parameter_mappings": parameter_mappings,
        "visualization_settings": dashcard.get("visualization_settings") or {},
    }
    return payload


def sync() -> dict[str, int]:
    field_map = fetch_field_map()
    dashboard = api("GET", f"/dashboard/{DASHBOARD_ID}")
    dashcards = dashboard.get("dashcards", [])

    card_cache: dict[int, dict] = {}
    updated_cards = 0
    for dashcard in dashcards:
        card_id = dashcard.get("card_id")
        if not card_id:
            continue

        card = api("GET", f"/card/{card_id}")
        card_cache[int(card_id)] = card
        dataset_query = card.get("dataset_query") or {}
        native = dataset_query.get("native") or {}
        template_tags = native.get("template-tags") or {}
        if not template_tags:
            continue

        source_name = find_source_name(native.get("query") or "")
        if not source_name or source_name not in field_map:
            continue

        current_parameters = {item.get("slug"): item for item in (card.get("parameters") or []) if item.get("slug")}
        normalized_tags = {}
        ordered_slugs = [slug for slug in template_tags if slug in field_map[source_name]]
        for slug in ordered_slugs:
            normalized_tags[slug] = build_template_tag(slug, field_map[source_name][slug], template_tags[slug])

        normalized_query = normalize_filter_clause(native["query"], ordered_slugs)
        parameters = [build_parameter(slug, normalized_tags[slug], current_parameters.get(slug)) for slug in ordered_slugs]

        payload = {
            "name": card["name"],
            "description": card.get("description"),
            "display": card["display"],
            "dataset_query": {
                **dataset_query,
                "native": {
                    **native,
                    "query": normalized_query,
                    "template-tags": normalized_tags,
                },
            },
            "visualization_settings": card.get("visualization_settings") or {},
            "parameters": parameters,
        }
        api("PUT", f"/card/{card_id}", payload)
        updated_cards += 1
        card_cache[int(card_id)] = api("GET", f"/card/{card_id}")

    used_slugs = []
    for card in card_cache.values():
        tags = (card.get("dataset_query") or {}).get("native", {}).get("template-tags", {})
        for slug in tags:
            if slug not in used_slugs:
                used_slugs.append(slug)

    dashboard_params = []
    seen_slugs = set()
    for parameter in dashboard.get("parameters", []):
        slug = parameter.get("slug")
        if slug not in used_slugs or slug in seen_slugs:
            continue
        dashboard_params.append(parameter)
        seen_slugs.add(slug)

    dashcards_payload = []
    mapped_dashcards = 0
    for dashcard in dashcards:
        card_id = dashcard.get("card_id")
        if not card_id:
            dashcards_payload.append(minimal_dashcard_payload(dashcard, []))
            continue

        card = card_cache[int(card_id)]
        tags = (card.get("dataset_query") or {}).get("native", {}).get("template-tags", {})
        parameter_mappings = []
        for parameter in dashboard_params:
            slug = parameter["slug"]
            if slug not in tags:
                continue
            parameter_mappings.append(
                {
                    "parameter_id": parameter["id"],
                    "card_id": card_id,
                    "target": ["dimension", ["template-tag", slug], {"stage-number": 0}],
                }
            )
        if parameter_mappings:
            mapped_dashcards += 1
        dashcards_payload.append(minimal_dashcard_payload(dashcard, parameter_mappings))

    api(
        "PUT",
        f"/dashboard/{DASHBOARD_ID}",
        {
            "name": dashboard["name"],
            "description": dashboard.get("description"),
            "width": dashboard.get("width", "fixed"),
            "auto_apply_filters": dashboard.get("auto_apply_filters", True),
            "parameters": dashboard_params,
            "tabs": dashboard.get("tabs", []),
            "dashcards": dashcards_payload,
        },
    )

    return {
        "updated_cards": updated_cards,
        "dashboard_params": len(dashboard_params),
        "mapped_dashcards": mapped_dashcards,
        "dashcards_total": len([dc for dc in dashcards if dc.get("card_id")]),
    }


if __name__ == "__main__":
    print(json.dumps(sync(), ensure_ascii=False))
