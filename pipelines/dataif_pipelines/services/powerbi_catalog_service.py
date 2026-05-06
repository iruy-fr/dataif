from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from dataif_pipelines.connectors.nilo_pecanha.powerbi_microdados import (
    MicrodadosCatalogEntry,
    PowerBIMicrodadosClient,
    PowerBIMicrodadosContext,
)


@dataclass(frozen=True)
class CatalogSelectionResult:
    instance_key: str | None
    selected_years: tuple[str, ...]
    selected_microdados_types: tuple[str, ...]
    selection_source: str
    context: PowerBIMicrodadosContext
    catalog_entries: tuple[MicrodadosCatalogEntry, ...]
    selected_entries: tuple[MicrodadosCatalogEntry, ...]


def create_powerbi_client(*, page_url: str, timeout_seconds: int) -> PowerBIMicrodadosClient:
    return PowerBIMicrodadosClient(page_url=page_url, timeout_seconds=timeout_seconds)


def resolve_catalog_selection(
    *,
    client: PowerBIMicrodadosClient,
    request_params: dict[str, Any],
) -> CatalogSelectionResult:
    instance_key = str(request_params.get("instance_key") or "").strip() or None
    selected_years = tuple(
        str(item).strip()
        for item in (request_params.get("selected_years") or [])
        if isinstance(item, str) and item.strip()
    )
    selected_microdados_types = tuple(
        str(item).strip()
        for item in (request_params.get("selected_microdados_types") or [])
        if isinstance(item, str) and item.strip()
    )
    if not selected_years:
        raise RuntimeError("powerbi_microdados mode requires selected_years")
    if not selected_microdados_types:
        raise RuntimeError("powerbi_microdados mode requires selected_microdados_types")

    context, catalog_entries = client.fetch_catalog()
    selected_downloads = [
        item
        for item in (request_params.get("selected_downloads") or [])
        if isinstance(item, dict)
    ]

    if selected_downloads:
        selected_keys = {
            (
                str(item.get("ano_base") or "").strip(),
                str(item.get("tipo_microdados") or "").strip(),
                str(item.get("microdados_url") or "").strip(),
            )
            for item in selected_downloads
            if str(item.get("ano_base") or "").strip()
            and str(item.get("tipo_microdados") or "").strip()
            and str(item.get("microdados_url") or "").strip()
        }
        filtered_entries = [
            entry
            for entry in catalog_entries
            if (entry.ano_base, entry.tipo_microdados, entry.microdados_url) in selected_keys
        ]
        missing_keys = selected_keys - {
            (entry.ano_base, entry.tipo_microdados, entry.microdados_url)
            for entry in filtered_entries
        }
        if missing_keys:
            missing_text = ", ".join(
                f"{ano_base}/{tipo_microdados}"
                for ano_base, tipo_microdados, _microdados_url in sorted(missing_keys)
            )
            raise RuntimeError(f"powerbi_microdados selected_downloads missing from public catalog: {missing_text}")
        selection_source = "selected_downloads"
    else:
        filtered_entries = [
            entry
            for entry in catalog_entries
            if entry.ano_base in selected_years and entry.tipo_microdados in selected_microdados_types
        ]
        selection_source = "catalog_filter"

    if not filtered_entries:
        raise RuntimeError("powerbi_microdados selection matched no download links in the public catalog")

    return CatalogSelectionResult(
        instance_key=instance_key,
        selected_years=selected_years,
        selected_microdados_types=selected_microdados_types,
        selection_source=selection_source,
        context=context,
        catalog_entries=tuple(catalog_entries),
        selected_entries=tuple(filtered_entries),
    )


def build_catalog_entry_rows(
    *,
    run_id: str,
    selection: CatalogSelectionResult,
) -> list[dict[str, Any]]:
    selected_keys = {
        (entry.ano_base, entry.tipo_microdados, entry.microdados_url)
        for entry in selection.selected_entries
    }
    rows: list[dict[str, Any]] = []
    for entry in selection.catalog_entries:
        rows.append(
            {
                "run_id": run_id,
                "instance_key": selection.instance_key,
                "ano_base": entry.ano_base,
                "tipo_microdados": entry.tipo_microdados,
                "microdados_url": entry.microdados_url,
                "resource_key": selection.context.resource_key,
                "visual_id": selection.context.visual_id,
                "api_base_url": selection.context.api_base_url,
                "catalog_hash": hashlib.sha256(
                    f"{entry.ano_base}|{entry.tipo_microdados}|{entry.microdados_url}".encode("utf-8")
                ).hexdigest(),
                "is_selected": (entry.ano_base, entry.tipo_microdados, entry.microdados_url) in selected_keys,
            }
        )
    return rows


def build_run_selection_rows(
    *,
    run_id: str,
    selection: CatalogSelectionResult,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selection_rank, entry in enumerate(selection.selected_entries, start=1):
        rows.append(
            {
                "run_id": run_id,
                "instance_key": selection.instance_key,
                "ano_base": entry.ano_base,
                "tipo_microdados": entry.tipo_microdados,
                "microdados_url": entry.microdados_url,
                "selection_source": selection.selection_source,
                "selection_rank": selection_rank,
                "details_json": {
                    "page_url": selection.context.page_url,
                    "resource_key": selection.context.resource_key,
                },
            }
        )
    return rows
