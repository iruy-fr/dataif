from __future__ import annotations

from types import SimpleNamespace

import pytest

from dataif_pipelines.jobs import nilo_pipeline


def test_run_extract_to_raw_logs_failed_status(monkeypatch) -> None:
    run_events: list[tuple[str, dict[str, object]]] = []

    class _BrokenConnector:
        def __init__(self, dsn: str, config) -> None:
            self._config = config

        def connector_id(self) -> str:
            return "nilo_pecanha"

        def fetch(self, run_context, instance_key: str | None = None) -> list[dict[str, object]]:
            raise RuntimeError("falha ao baixar catálogo público")

        def runtime_stats(self) -> dict[str, int]:
            return {"download_count": 0}

    monkeypatch.setattr(nilo_pipeline, "_warehouse_dsn", lambda: "postgresql://warehouse")
    monkeypatch.setattr(
        nilo_pipeline,
        "load_config",
        lambda: SimpleNamespace(endpoint="https://app.powerbi.com/view?r=fake"),
    )
    monkeypatch.setattr(nilo_pipeline, "NiloPecanhaConnector", _BrokenConnector)
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "register_run_start",
        lambda dsn, **kwargs: run_events.append(("start", kwargs)),
    )
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "finish_run",
        lambda dsn, **kwargs: run_events.append(("finish", kwargs)),
    )
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "mark_run_downloads_failed",
        lambda dsn, **kwargs: run_events.append(("mark_failed", kwargs)),
    )

    with pytest.raises(RuntimeError, match="falha ao baixar catálogo público"):
        nilo_pipeline.run_extract_to_raw()

    assert [event[0] for event in run_events] == ["start", "finish", "mark_failed"]
    assert run_events[1][1]["status"] == "failed"
    assert run_events[1][1]["run_summary"]["error"] == "falha ao baixar catálogo público"


def test_run_extract_to_raw_passes_instance_key(monkeypatch) -> None:
    captured: list[str | None] = []
    run_events: list[tuple[str, dict[str, object]]] = []

    class _Connector:
        def __init__(self, dsn: str, config) -> None:
            self._config = config

        def connector_id(self) -> str:
            return "nilo_pecanha"

        def fetch(self, run_context, instance_key: str | None = None) -> list[dict[str, object]]:
            captured.append(instance_key)
            return []

        def normalize(self, raw_records, run_context):
            return []

        def load_raw(self, normalized_records, run_context) -> int:
            return 0

        def post_load_checks(self, run_id: str) -> dict[str, int]:
            return {"run_id": run_id, "raw_count": 0, "asset_count": 0}

        def runtime_stats(self) -> dict[str, int]:
            return {"download_count": 0}

    monkeypatch.setattr(nilo_pipeline, "_warehouse_dsn", lambda: "postgresql://warehouse")
    monkeypatch.setattr(
        nilo_pipeline,
        "load_config",
        lambda: SimpleNamespace(endpoint="https://app.powerbi.com/view?r=fake"),
    )
    monkeypatch.setattr(nilo_pipeline, "NiloPecanhaConnector", _Connector)
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "register_run_start",
        lambda dsn, **kwargs: run_events.append(("start", kwargs)),
    )
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "finish_run",
        lambda dsn, **kwargs: run_events.append(("finish", kwargs)),
    )

    nilo_pipeline.run_extract_to_raw(instance_key="pnp_ifb")

    assert captured == ["pnp_ifb"]
    assert [event[0] for event in run_events] == ["start", "finish"]
    assert run_events[0][1]["instance_key"] == "pnp_ifb"
    assert run_events[1][1]["status"] == "success"


def test_run_extract_to_raw_prefers_buffered_connector_path(monkeypatch) -> None:
    run_events: list[tuple[str, dict[str, object]]] = []

    class _Connector:
        def __init__(self, dsn: str, config) -> None:
            self._config = config

        def connector_id(self) -> str:
            return "nilo_pecanha"

        def extract_and_load_raw(self, run_context, instance_key: str | None = None) -> int:
            assert instance_key == "pnp_ifb"
            return 12

        def post_load_checks(self, run_id: str) -> dict[str, int]:
            return {
                "run_id": run_id,
                "catalog_entry_count": 3,
                "run_selection_count": 1,
                "download_count": 1,
                "raw_count": 12,
            }

        def runtime_stats(self) -> dict[str, int]:
            return {
                "download_count": 1,
                "raw_domain_count": 12,
                "asset_count": 2,
                "download_column_count": 4,
                "quarantine_count": 0,
            }

        def fetch(self, run_context, instance_key: str | None = None):
            raise AssertionError("legacy fetch path should not be used")

    monkeypatch.setattr(nilo_pipeline, "_warehouse_dsn", lambda: "postgresql://warehouse")
    monkeypatch.setattr(
        nilo_pipeline,
        "load_config",
        lambda: SimpleNamespace(endpoint="https://app.powerbi.com/view?r=fake"),
    )
    monkeypatch.setattr(nilo_pipeline, "NiloPecanhaConnector", _Connector)
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "register_run_start",
        lambda dsn, **kwargs: run_events.append(("start", kwargs)),
    )
    monkeypatch.setattr(
        nilo_pipeline.pnp_raw_repository,
        "finish_run",
        lambda dsn, **kwargs: run_events.append(("finish", kwargs)),
    )

    nilo_pipeline.run_extract_to_raw(instance_key="pnp_ifb")

    assert [event[0] for event in run_events] == ["start", "finish"]
    assert run_events[1][1]["status"] == "success"
    assert run_events[1][1]["raw_record_count"] == 12
