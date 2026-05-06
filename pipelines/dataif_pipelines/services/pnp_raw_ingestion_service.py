from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from dataif_pipelines.connectors.base.types import NormalizedRecord, RawRecord, RunContext
from dataif_pipelines.connectors.nilo_pecanha.transform import normalize_domain_record, normalize_record
from dataif_pipelines.repositories import pnp_raw_repository


@dataclass(frozen=True)
class NormalizationResult:
    normalized_records: list[NormalizedRecord]
    quarantine_rows: list[dict[str, Any]]


def normalize_raw_records(raw_records: list[RawRecord], run_context: RunContext) -> NormalizationResult:
    normalized: list[NormalizedRecord] = []
    quarantine_rows: list[dict[str, Any]] = []

    for raw_record in raw_records:
        payload = raw_record.get("payload")
        if not isinstance(payload, dict):
            continue

        source_url = str(raw_record.get("source_url") or run_context.source_url)
        legacy_record = normalize_record(
            payload=payload,
            source_url=source_url,
            run_id=run_context.run_id,
            endpoint_id=int(raw_record.get("endpoint_id")),
            endpoint_key=str(raw_record.get("endpoint_key") or "default"),
            source_kind=str(raw_record.get("source_kind") or "powerbi_microdados"),
        )

        try:
            domain_record = normalize_domain_record(
                payload=payload,
                run_id=run_context.run_id,
                instance_key=str(payload.get("instance_key") or "").strip() or None,
                source_url=source_url,
            )
        except Exception as exc:
            quarantine_rows.append(
                {
                    "run_id": run_context.run_id,
                    "instance_key": str(payload.get("instance_key") or "").strip() or None,
                    "source_url": source_url,
                    "source_row_number": payload.get("source_row_number"),
                    "error_type": "unsupported_domain",
                    "error_message": str(exc),
                    "raw_line_text": json.dumps(payload, ensure_ascii=True, sort_keys=True),
                    "details_json": {"tipo_microdados": payload.get("tipo_microdados")},
                }
            )
            continue

        normalized.append({**legacy_record, **domain_record})

    return NormalizationResult(normalized_records=normalized, quarantine_rows=quarantine_rows)


def load_raw_batch(
    dsn: str,
    *,
    normalized_records: list[dict[str, Any]],
    pending_assets: list[dict[str, Any]],
    pending_catalog_entries: list[dict[str, Any]],
    pending_run_selection: list[dict[str, Any]],
    pending_downloads: list[dict[str, Any]],
    pending_quarantine: list[dict[str, Any]],
    write_legacy: bool = False,
) -> dict[str, int]:
    return pnp_raw_repository.load_raw_batch(
        dsn,
        normalized_records=normalized_records,
        pending_assets=pending_assets,
        pending_catalog_entries=pending_catalog_entries,
        pending_run_selection=pending_run_selection,
        pending_downloads=pending_downloads,
        pending_quarantine=pending_quarantine,
        write_legacy=write_legacy,
    )


def upsert_raw_metadata(
    dsn: str,
    *,
    pending_assets: list[dict[str, Any]],
    pending_catalog_entries: list[dict[str, Any]],
    pending_run_selection: list[dict[str, Any]],
    pending_downloads: list[dict[str, Any]],
    write_legacy: bool = False,
    include_download_columns: bool = True,
) -> dict[str, Any]:
    return pnp_raw_repository.upsert_raw_metadata(
        dsn,
        pending_assets=pending_assets,
        pending_catalog_entries=pending_catalog_entries,
        pending_run_selection=pending_run_selection,
        pending_downloads=pending_downloads,
        write_legacy=write_legacy,
        include_download_columns=include_download_columns,
    )


def load_raw_record_chunk(
    dsn: str,
    *,
    normalized_records: list[dict[str, Any]],
    pending_quarantine: list[dict[str, Any]],
    download_id_by_url: dict[str, int],
    pending_assets: list[dict[str, Any]] | None = None,
    write_legacy: bool = False,
) -> dict[str, int]:
    return pnp_raw_repository.load_raw_record_chunk(
        dsn,
        normalized_records=normalized_records,
        pending_quarantine=pending_quarantine,
        download_id_by_url=download_id_by_url,
        pending_assets=pending_assets,
        write_legacy=write_legacy,
    )
