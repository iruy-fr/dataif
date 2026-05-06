from __future__ import annotations

from typing import Any

from dataif_pipelines.repositories import pnp_raw_repository


def collect_run_checks(dsn: str, run_id: str) -> dict[str, Any]:
    return pnp_raw_repository.collect_run_checks(dsn, run_id)
