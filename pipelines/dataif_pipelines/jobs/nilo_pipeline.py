from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from dataif_pipelines.connectors.base.types import RunContext
from dataif_pipelines.connectors.nilo_pecanha.config import load_config
from dataif_pipelines.connectors.nilo_pecanha.connector import NiloPecanhaConnector
from dataif_pipelines.repositories import pnp_raw_repository

logger = logging.getLogger(__name__)


def _warehouse_dsn() -> str:
    dsn = os.getenv("WAREHOUSE_DSN")
    if not dsn:
        raise RuntimeError("WAREHOUSE_DSN is required")
    return dsn


def run_extract_to_raw(instance_key: str | None = None) -> str:
    run_id = str(uuid.uuid4())
    config = load_config()
    started_at = datetime.now(tz=UTC)
    run_context = RunContext(run_id=run_id, started_at=started_at, source_url=config.endpoint)
    connector = NiloPecanhaConnector(dsn=_warehouse_dsn(), config=config)
    pnp_raw_repository.register_run_start(
        _warehouse_dsn(),
        run_id=run_id,
        instance_key=instance_key,
        status="running",
        trigger_mode="legacy_run_extract_to_raw",
        requested_by="nilo_pipeline.run_extract_to_raw",
        logical_date=started_at,
        started_at=started_at,
    )

    try:
        extracted_count = 0
        if hasattr(connector, "extract_and_load_raw"):
            loaded_count = connector.extract_and_load_raw(run_context, instance_key=instance_key)
            extracted_count = int(connector.runtime_stats().get("raw_domain_count") or loaded_count)
        else:
            raw_records = connector.fetch(run_context, instance_key=instance_key)
            normalized_records = connector.normalize(raw_records, run_context)
            loaded_count = connector.load_raw(normalized_records, run_context)
            extracted_count = len(raw_records)
        checks = connector.post_load_checks(run_id)

        details = {
            "source": config.endpoint,
            "instance_key": instance_key,
            "runtime": connector.runtime_stats(),
            "checks": checks,
            "extracted_count": extracted_count,
            "loaded_count": loaded_count,
        }

        pnp_raw_repository.finish_run(
            _warehouse_dsn(),
            run_id=run_id,
            status="success",
            catalog_entry_count=int(checks.get("catalog_entry_count") or 0),
            selected_download_count=int(checks.get("run_selection_count") or 0),
            downloaded_file_count=int(checks.get("download_count") or 0),
            raw_record_count=int(checks.get("raw_count") or loaded_count),
            error_message=None,
            run_summary=details,
            finished_at=datetime.now(tz=UTC),
        )

        logger.info("Raw load completed run_id=%s extracted=%s loaded=%s", run_id, extracted_count, loaded_count)
        return run_id
    except Exception as exc:
        details = {
            "source": config.endpoint,
            "instance_key": instance_key,
            "runtime": connector.runtime_stats(),
            "error": str(exc),
        }
        pnp_raw_repository.finish_run(
            _warehouse_dsn(),
            run_id=run_id,
            status="failed",
            catalog_entry_count=0,
            selected_download_count=0,
            downloaded_file_count=int(connector.runtime_stats().get("download_count") or 0),
            raw_record_count=int(connector.runtime_stats().get("raw_domain_count") or 0),
            error_message=str(exc),
            run_summary=details,
            finished_at=datetime.now(tz=UTC),
        )
        pnp_raw_repository.mark_run_downloads_failed(
            _warehouse_dsn(),
            run_id=run_id,
            error_message=str(exc),
        )
        raise


def run_staging(run_id: str) -> int:
    raise RuntimeError(
        "run_staging no longer supports the legacy nilo staging tables; use the PNP workflow staging services instead"
    )


def run_mart_and_curated(run_id: str) -> int:
    raise RuntimeError(
        "run_mart_and_curated no longer supports the legacy nilo mart tables; use the PNP workflow curated services instead"
    )
