from __future__ import annotations

import base64
import json
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

DEFAULT_PNP_POWERBI_REPORT_URL = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiZDhkNGNiYzgtMjQ0My00OGVlLWJjNzYtZWQwYjI2OThhYWM1IiwidCI6IjllNjgyMzU5LWQxMjgtNGVkYi1iYjU4LTgyYjJhMTUzNDBmZiJ9"
)
MICRODADOS_SECTION_DISPLAY_NAME = "Microdados da PNP"
MICRODADOS_ROWS_QUERY_REF = "Microdados.Ano Base"
MICRODADOS_COLUMNS_QUERY_REF = "Microdados.Tipo de microdados"
MICRODADOS_VALUES_QUERY_REF = "Microdados.MicrodadosURL"
MICRODADOS_ENTITY_NAME = "Microdados"
MICRODADOS_ANO_PROPERTY = "Ano Base"
MICRODADOS_TIPO_PROPERTY = "Tipo de microdados"
MICRODADOS_URL_PROPERTY = "MicrodadosURL"
PNP_MICRODADOS_TYPES = (
    "Eficiência Acadêmica",
    "Financeiro",
    "Matrículas",
    "Servidores",
)


def load_public_microdados_catalog(
    *,
    timeout_seconds: float,
    page_url: str = DEFAULT_PNP_POWERBI_REPORT_URL,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        html_response = client.get(page_url)
        html_response.raise_for_status()
        html = html_response.text

        resource_descriptor = _extract_resource_descriptor(html) or _decode_resource_descriptor_from_url(page_url)
        resource_key = str(resource_descriptor.get("k") or "").strip()
        tenant_id = str(resource_descriptor.get("t") or "").strip()
        if not resource_key or not tenant_id:
            raise RuntimeError("Power BI page did not expose the public resource descriptor")

        resolved_cluster_uri = _extract_resolved_cluster_uri(html)
        if not resolved_cluster_uri:
            route_response = client.get(
                f"https://api.powerbi.com/public/routing/cluster/{tenant_id}",
                headers=_powerbi_headers(resource_key),
            )
            route_response.raise_for_status()
            resolved_cluster_uri = str((route_response.json() or {}).get("FixedClusterUri") or "").strip()
            if not resolved_cluster_uri:
                raise RuntimeError("Power BI routing did not return FixedClusterUri")

        api_base_url = _build_apim_url(resolved_cluster_uri)
        metadata_response = client.get(
            f"{api_base_url}/public/reports/{resource_key}/modelsAndExploration?preferReadOnlySession=true",
            headers=_powerbi_headers(resource_key),
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        visual = _find_microdados_visual(metadata)
        report = dict((metadata.get("exploration") or {}).get("report") or {})
        model = dict(report.get("model") or {})
        model_fallback = dict((metadata.get("models") or [{}])[0] or {})

        query_body = {
            "version": "1.0.0",
            "queries": [
                {
                    "Query": {
                        "Commands": [
                            {
                                "SemanticQueryDataShapeCommand": {
                                    "Query": dict((visual.get("singleVisual") or {}).get("prototypeQuery") or {}),
                                    "Binding": {
                                        "Primary": {"Groupings": [{"Projections": [0, 1, 2]}]},
                                        "DataReduction": {"DataVolume": 3, "Primary": {"Top": {"Count": 500}}},
                                        "Version": 1,
                                    },
                                    "ExecutionMetricsKind": 1,
                                }
                            }
                        ]
                    },
                    "ApplicationContext": {
                        "DatasetId": str(model.get("dbName") or model_fallback.get("dbName") or ""),
                        "Sources": [
                            {
                                "ReportId": str(report.get("objectId") or ""),
                                "VisualId": str(visual.get("name") or ""),
                            }
                        ],
                    },
                }
            ],
            "modelId": int(report.get("modelId") or model_fallback.get("id") or 0),
        }
        query_response = client.post(
            f"{api_base_url}/public/reports/querydata?synchronous=true",
            headers=_powerbi_headers(resource_key, json_request=True),
            json=query_body,
        )
        query_response.raise_for_status()
        items = _decode_microdados_catalog(query_response.json())
        type_rank = {item: index for index, item in enumerate(PNP_MICRODADOS_TYPES)}
        items.sort(
            key=lambda item: (
                -int(item["ano_base"]) if str(item["ano_base"]).isdigit() else 0,
                type_rank.get(item["tipo_microdados"], 999),
                item["microdados_url"],
            )
        )
        years = sorted({item["ano_base"] for item in items}, reverse=True)
        by_year: dict[str, list[str]] = {}
        for year in years:
            types = sorted(
                {item["tipo_microdados"] for item in items if item["ano_base"] == year},
                key=lambda item: (PNP_MICRODADOS_TYPES.index(item) if item in PNP_MICRODADOS_TYPES else 999, item),
            )
            by_year[year] = types

        return {
            "page_url": page_url,
            "resource_key": resource_key,
            "available_years": years,
            "available_microdados_types": [item for item in PNP_MICRODADOS_TYPES if any(t == item for t in {row["tipo_microdados"] for row in items})],
            "types_by_year": by_year,
            "items": items,
        }


def _powerbi_headers(resource_key: str, json_request: bool = False) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "ActivityId": str(uuid.uuid4()),
        "RequestId": str(uuid.uuid4()),
        "X-PowerBI-ResourceKey": resource_key,
    }
    if json_request:
        headers["Content-Type"] = "application/json"
    return headers


def _extract_resource_descriptor(html: str) -> dict[str, str]:
    marker = "resourceDescriptor = JSON.parse('"
    start = html.find(marker)
    if start < 0:
        return {}
    start += len(marker)
    end = html.find("');", start)
    if end < 0:
        return {}
    payload = bytes(html[start:end], "utf-8").decode("unicode_escape")
    descriptor = json.loads(payload)
    return {
        "k": str(descriptor.get("k") or "").strip(),
        "t": str(descriptor.get("t") or "").strip(),
    }


def _decode_resource_descriptor_from_url(page_url: str) -> dict[str, str]:
    parsed = urlparse(page_url)
    encoded = parse_qs(parsed.query).get("r", [])
    if not encoded:
        return {}
    token = unquote(encoded[0])
    padding = "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    return {
        "k": str(payload.get("k") or "").strip(),
        "t": str(payload.get("t") or "").strip(),
    }


def _extract_resolved_cluster_uri(html: str) -> str:
    marker = "var resolvedClusterUri = '"
    start = html.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = html.find("';", start)
    if end < 0:
        return ""
    return html[start:end].strip()


def _build_apim_url(cluster_uri: str) -> str:
    parsed = urlparse(cluster_uri)
    hostname = parsed.hostname or ""
    if not hostname:
        raise RuntimeError("Invalid Power BI cluster uri")
    host_tokens = hostname.split(".")
    host_tokens[0] = host_tokens[0].replace("-redirect", "")
    host_tokens[0] = host_tokens[0].replace("global-", "")
    host_tokens[0] = f"{host_tokens[0]}-api"
    scheme = parsed.scheme or "https"
    return f"{scheme}://{'.'.join(host_tokens)}"


def _find_microdados_visual(metadata: dict[str, Any]) -> dict[str, Any]:
    sections = list(((metadata.get("exploration") or {}).get("sections") or []))
    preferred_section = _find_microdados_section(sections)
    if preferred_section is not None:
        visual = _select_microdados_visual(preferred_section)
        if visual is not None:
            return visual

        fallback_visual = _build_fallback_visual(preferred_section)
        if fallback_visual is not None:
            return fallback_visual

    for section in sections:
        visual = _select_microdados_visual(section)
        if visual is not None:
            return visual

    if preferred_section is None:
        available_sections = ", ".join(
            sorted(
                {
                    str(section.get("displayName") or "").strip()
                    for section in sections
                    if str(section.get("displayName") or "").strip()
                }
            )
        )
        raise RuntimeError(
            "Power BI metadata did not expose the Microdados da PNP section"
            + (f"; available sections: {available_sections}" if available_sections else "")
        )

    raise RuntimeError(
        "Power BI metadata exposed the Microdados da PNP section, "
        "but no compatible visual or fallback query context was found"
    )


def _find_microdados_section(sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for section in sections:
        if str(section.get("displayName") or "").strip() == MICRODADOS_SECTION_DISPLAY_NAME:
            return section
    return None


def _select_microdados_visual(section: dict[str, Any]) -> dict[str, Any] | None:
    for container in section.get("visualContainers") or []:
        raw_config = container.get("config")
        if not isinstance(raw_config, str) or not raw_config.strip():
            continue
        try:
            visual = json.loads(raw_config)
        except json.JSONDecodeError:
            continue

        single_visual = dict(visual.get("singleVisual") or {})
        if not single_visual:
            continue

        projections = dict(single_visual.get("projections") or {})
        if _visual_matches_microdados_catalog(single_visual, projections):
            return visual
    return None


def _visual_matches_microdados_catalog(single_visual: dict[str, Any], projections: dict[str, Any]) -> bool:
    row_refs = [item.get("queryRef") for item in projections.get("Rows") or [] if item.get("active", True)]
    column_refs = [item.get("queryRef") for item in projections.get("Columns") or [] if item.get("active", True)]
    value_refs = [
        item.get("queryRef")
        for item in projections.get("Values") or []
        if item.get("active", True) or "active" not in item
    ]

    exact_projection_match = (
        single_visual.get("visualType") == "pivotTable"
        and row_refs == [MICRODADOS_ROWS_QUERY_REF]
        and column_refs == [MICRODADOS_COLUMNS_QUERY_REF]
        and value_refs == [MICRODADOS_VALUES_QUERY_REF]
    )
    if exact_projection_match:
        return True

    prototype_query = dict(single_visual.get("prototypeQuery") or {})
    select_names = {
        str(item.get("Name") or "").strip()
        for item in prototype_query.get("Select") or []
        if isinstance(item, dict)
    }
    return {
        MICRODADOS_ROWS_QUERY_REF,
        MICRODADOS_COLUMNS_QUERY_REF,
        MICRODADOS_VALUES_QUERY_REF,
    }.issubset(select_names)


def _build_fallback_visual(section: dict[str, Any]) -> dict[str, Any] | None:
    visual_containers = list(section.get("visualContainers") or [])
    if not visual_containers:
        return None

    fallback_name = str(visual_containers[0].get("objectName") or visual_containers[0].get("id") or "microdados_catalog")
    return {
        "name": fallback_name,
        "singleVisual": {
            "visualType": "microdados_catalog_fallback",
            "prototypeQuery": _build_fallback_prototype_query(),
        },
    }


def _build_fallback_prototype_query() -> dict[str, Any]:
    return {
        "Version": 2,
        "From": [{"Name": "m", "Entity": MICRODADOS_ENTITY_NAME, "Type": 0}],
        "Select": [
            {
                "Measure": {
                    "Expression": {"SourceRef": {"Source": "m"}},
                    "Property": MICRODADOS_URL_PROPERTY,
                },
                "Name": MICRODADOS_VALUES_QUERY_REF,
            },
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": "m"}},
                    "Property": MICRODADOS_ANO_PROPERTY,
                },
                "Name": MICRODADOS_ROWS_QUERY_REF,
            },
            {
                "Column": {
                    "Expression": {"SourceRef": {"Source": "m"}},
                    "Property": MICRODADOS_TIPO_PROPERTY,
                },
                "Name": MICRODADOS_COLUMNS_QUERY_REF,
            },
        ],
    }


def _decode_microdados_catalog(payload: dict[str, Any]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    items: list[dict[str, str]] = []
    for result in payload.get("results") or []:
        data = dict((result.get("result") or {}).get("data") or {})
        dsr = dict(data.get("dsr") or {})
        for dataset in dsr.get("DS") or []:
            for row in _decode_dsr_rows(dict(dataset or {})):
                if len(row) < 3:
                    continue
                year = str(row[0] or "").strip()
                microdata_type = str(row[1] or "").strip()
                download_url = str(row[2] or "").strip()
                if not year or not microdata_type or not download_url:
                    continue
                key = (year, microdata_type, download_url)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "ano_base": year,
                        "tipo_microdados": microdata_type,
                        "microdados_url": download_url,
                    }
                )
    return items


def _decode_dsr_rows(dataset: dict[str, Any]) -> list[list[Any]]:
    value_dicts = dict(dataset.get("ValueDicts") or {})
    rows: list[list[Any]] = []
    for placeholder in dataset.get("PH") or []:
        if not isinstance(placeholder, dict):
            continue
        for member_name, member_rows in placeholder.items():
            if not isinstance(member_name, str) or not member_name.startswith("DM") or not isinstance(member_rows, list):
                continue
            schema: list[dict[str, Any]] = []
            previous_values: list[Any] = []
            for member_row in member_rows:
                if not isinstance(member_row, dict):
                    continue
                if isinstance(member_row.get("S"), list):
                    schema = [dict(item or {}) for item in member_row["S"]]
                    previous_values = [None] * len(schema)
                if not schema:
                    continue
                inflated = _inflate_dsr_row(member_row, schema, previous_values)
                if inflated is None:
                    continue
                previous_values = list(inflated)
                rows.append([_resolve_dsr_value(schema_item, value_dicts, value) for schema_item, value in zip(schema, inflated)])
    return rows


def _inflate_dsr_row(
    row: dict[str, Any],
    schema: list[dict[str, Any]],
    previous_values: list[Any],
) -> list[Any] | None:
    compressed = row.get("C")
    if isinstance(compressed, list):
        values = list(previous_values) if previous_values else [None] * len(schema)
        start_index = len(schema) - len(compressed)
        if isinstance(row.get("R"), int):
            start_index = int(row["R"])
        start_index = max(0, min(start_index, len(schema)))
        for offset, value in enumerate(compressed):
            index = start_index + offset
            if index >= len(schema):
                break
            values[index] = value
        return values

    named_values = [row.get(str(column.get("N") or "")) for column in schema]
    if any(value is not None for value in named_values):
        return named_values
    return None


def _resolve_dsr_value(schema_item: dict[str, Any], value_dicts: dict[str, Any], raw_value: Any) -> Any:
    dictionary_name = schema_item.get("DN")
    if isinstance(raw_value, int) and isinstance(dictionary_name, str):
        dictionary = value_dicts.get(dictionary_name)
        if isinstance(dictionary, list) and 0 <= raw_value < len(dictionary):
            raw_value = dictionary[raw_value]

    if isinstance(raw_value, str):
        cleaned = raw_value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:-1]
        return cleaned
    return raw_value
