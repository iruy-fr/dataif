from __future__ import annotations

import gzip
from datetime import datetime

from dataif_pipelines.connectors.base.types import RunContext
from dataif_pipelines.connectors.nilo_pecanha.powerbi_microdados import (
    MicrodadosCatalogEntry,
    MicrodadosContentResult,
    PowerBIMicrodadosContext,
)
from dataif_pipelines.services import pnp_download_service, pnp_raw_ingestion_service, powerbi_catalog_service


def _sample_context() -> PowerBIMicrodadosContext:
    return PowerBIMicrodadosContext(
        page_url="https://app.powerbi.com/view?r=fake",
        resource_key="resource-key-123",
        tenant_id="tenant-id-456",
        resolved_cluster_uri="https://wabi-brazil-south-b-primary-redirect.analysis.windows.net/",
        api_base_url="https://wabi-brazil-south-b-primary-api.analysis.windows.net",
        model_id=321,
        dataset_id="dataset-guid",
        report_id="report-guid",
        report_numeric_id=987,
        section_name="section-1",
        section_display_name="Microdados da PNP",
        visual_id="visual-123",
        visual_type="pivotTable",
        prototype_query={"Version": 2},
    )


def test_powerbi_catalog_service_resolves_selection_and_builds_rows() -> None:
    entries = [
        MicrodadosCatalogEntry(
            ano_base="2024",
            tipo_microdados="Matrículas",
            microdados_url="https://example.test/microdados_2024_matriculas.csv.gz",
        ),
        MicrodadosCatalogEntry(
            ano_base="2024",
            tipo_microdados="Servidores",
            microdados_url="https://example.test/microdados_2024_servidores.csv.gz",
        ),
    ]

    class _FakeClient:
        def fetch_catalog(self):
            return _sample_context(), entries

    selection = powerbi_catalog_service.resolve_catalog_selection(
        client=_FakeClient(),
        request_params={
            "instance_key": "pnp_ifb",
            "selected_years": ["2024"],
            "selected_microdados_types": ["Matrículas"],
            "selected_downloads": [
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Matrículas",
                    "microdados_url": "https://example.test/microdados_2024_matriculas.csv.gz",
                }
            ],
        },
    )

    catalog_rows = powerbi_catalog_service.build_catalog_entry_rows(run_id="run-1", selection=selection)
    run_selection_rows = powerbi_catalog_service.build_run_selection_rows(run_id="run-1", selection=selection)

    assert selection.instance_key == "pnp_ifb"
    assert selection.selection_source == "selected_downloads"
    assert len(selection.selected_entries) == 1
    assert len(catalog_rows) == 2
    assert len(run_selection_rows) == 1
    assert catalog_rows[0]["run_id"] == "run-1"
    assert run_selection_rows[0]["selection_rank"] == 1


def test_pnp_download_service_builds_download_batch() -> None:
    entry = MicrodadosCatalogEntry(
        ano_base="2024",
        tipo_microdados="Matrículas",
        microdados_url="https://example.test/microdados_2024_matriculas.csv.gz",
    )
    selection = powerbi_catalog_service.CatalogSelectionResult(
        instance_key="pnp_ifb",
        selected_years=("2024",),
        selected_microdados_types=("Matrículas",),
        selection_source="selected_downloads",
        context=_sample_context(),
        catalog_entries=(entry,),
        selected_entries=(entry,),
    )

    class _FakeClient:
        def fetch_entry_content(self, selected_entry: MicrodadosCatalogEntry) -> MicrodadosContentResult:
            payload = gzip.compress("Código da Matricula;Nome\n123;Alice\n456;Bruno\n".encode("utf-8"))
            return MicrodadosContentResult(
                source_url=selected_entry.microdados_url,
                content_bytes=payload,
                size_bytes=len(payload),
                sha256="sha-test",
                content_type="application/x-gzip",
            )

        @staticmethod
        def decode_content_bytes(content_bytes: bytes, source_url: str) -> str:
            return gzip.decompress(content_bytes).decode("utf-8")

    batch = pnp_download_service.build_download_batch(
        client=_FakeClient(),
        run_id="run-1",
        endpoint_id=77,
        endpoint_key="pnp_publico__microdados",
        selection=selection,
    )

    assert len(batch.records) == 2
    assert len(batch.downloads) == 1
    assert [item["asset_type"] for item in batch.assets] == [
        "powerbi_microdados_download",
        "powerbi_microdados_manifest",
    ]
    assert batch.records[0]["dataset"] == "pnp_microdados_matriculas"
    assert batch.downloads[0]["headers"] == ("Código da Matricula", "Nome")


def test_pnp_raw_ingestion_service_normalizes_and_quarantines_records(monkeypatch) -> None:
    run_context = RunContext(run_id="run-1", started_at=datetime(2026, 1, 1), source_url="https://x")
    raw_records = [
        {
            "payload": {
                "tipo_microdados": "Matrículas",
                "Código da Matricula": "123",
                "Ano": "2024",
                "source_row_number": 1,
                "source_file_name": "matriculas.csv",
                "source_file_sha256": "sha-test",
                "instance_key": "pnp_ifb",
            },
            "source_url": "https://example.test/matriculas.csv.gz",
            "endpoint_id": 77,
            "endpoint_key": "pnp_publico__microdados",
            "source_kind": "powerbi_microdados",
        },
        {
            "payload": {
                "tipo_microdados": "Inexistente",
                "source_row_number": 2,
                "instance_key": "pnp_ifb",
            },
            "source_url": "https://example.test/invalid.csv.gz",
            "endpoint_id": 77,
            "endpoint_key": "pnp_publico__microdados",
            "source_kind": "powerbi_microdados",
        },
    ]

    result = pnp_raw_ingestion_service.normalize_raw_records(raw_records, run_context)

    captured: dict[str, object] = {}

    def _fake_load_raw_batch(dsn: str, **kwargs):
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return {"raw_record_count": 1}

    monkeypatch.setattr(pnp_raw_ingestion_service.pnp_raw_repository, "load_raw_batch", _fake_load_raw_batch)
    stats = pnp_raw_ingestion_service.load_raw_batch(
        "postgresql://warehouse",
        normalized_records=result.normalized_records,
        pending_assets=[],
        pending_catalog_entries=[],
        pending_run_selection=[],
        pending_downloads=[],
        pending_quarantine=result.quarantine_rows,
        write_legacy=True,
    )

    assert len(result.normalized_records) == 1
    assert result.normalized_records[0]["raw_table_name"] == "pnp_matriculas_src"
    assert len(result.quarantine_rows) == 1
    assert captured["dsn"] == "postgresql://warehouse"
    assert stats["raw_record_count"] == 1
