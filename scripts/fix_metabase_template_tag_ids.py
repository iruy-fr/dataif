from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from hashlib import md5


API_BASE = os.getenv("METABASE_API_URL", "http://localhost:3001/api").rstrip("/")
API_KEY = os.getenv("METABASE_API_KEY")
CARD_NAME_PREFIX = os.getenv("METABASE_CARD_PREFIX", "PNP 2024 - ")

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


def ensure_template_tag_ids() -> dict[str, int]:
    updated = 0
    skipped = 0

    for card_stub in api("GET", "/card"):
        card_id = int(card_stub["id"])
        name = card_stub.get("name") or ""
        if not name.startswith(CARD_NAME_PREFIX):
            continue

        card = api("GET", f"/card/{card_id}")
        dataset_query = card.get("dataset_query") or {}
        native = dataset_query.get("native") or {}
        template_tags = native.get("template-tags") or {}
        if not template_tags:
            skipped += 1
            continue

        changed = False
        normalized_tags = {}
        for slug, tag in template_tags.items():
            if not isinstance(tag, dict):
                normalized_tags[slug] = tag
                continue

            tag = dict(tag)
            if not tag.get("id"):
                tag["id"] = md5(f"{card_id}:{slug}".encode("utf-8")).hexdigest()[:12]
                changed = True
            normalized_tags[slug] = tag

        if not changed:
            skipped += 1
            continue

        payload = {
            "name": card["name"],
            "description": card.get("description"),
            "display": card["display"],
            "dataset_query": {
                **dataset_query,
                "native": {
                    **native,
                    "template-tags": normalized_tags,
                },
            },
            "visualization_settings": card.get("visualization_settings") or {},
            "parameters": [],
        }
        api("PUT", f"/card/{card_id}", payload)
        updated += 1

    return {"updated": updated, "skipped": skipped}


if __name__ == "__main__":
    print(json.dumps(ensure_template_tag_ids(), ensure_ascii=False))
