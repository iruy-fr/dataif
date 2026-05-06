from __future__ import annotations

import gzip
import json
from datetime import datetime

from dataif_pipelines.connectors.base.types import RunContext
from dataif_pipelines.connectors.nilo_pecanha.config import NiloConfig
from dataif_pipelines.connectors.nilo_pecanha.connector import EndpointDefinition, NiloPecanhaConnector
from dataif_pipelines.connectors.nilo_pecanha.powerbi_microdados import (
    MicrodadosCatalogEntry,
    MicrodadosContentResult,
    PowerBIMicrodadosClient,
    PowerBIMicrodadosContext,
)
from dataif_pipelines.services import pnp_raw_ingestion_service


class _FakeResponse:
    def __init__(
        self,
        *,
        text: str | None = None,
        json_payload: dict[str, object] | None = None,
        content_bytes: bytes | None = None,
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self.text = text or ""
        self._json_payload = json_payload
        self._content_bytes = content_bytes or b""
        self.headers = headers or {}
        self.status_code = status_code

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict[str, object]:
        if self._json_payload is None:
            raise RuntimeError("missing json payload")
        return self._json_payload

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self._content_bytes), chunk_size):
            yield self._content_bytes[index : index + chunk_size]


class _FakeSession:
    def __init__(self, html: str, metadata: dict[str, object], querydata: dict[str, object], download_bytes: bytes) -> None:
        self.html = html
        self.metadata = metadata
        self.querydata = querydata
        self.download_bytes = download_bytes
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append(("GET", url))
        if url.startswith("https://app.powerbi.com/view"):
            return _FakeResponse(text=self.html)
        if "modelsAndExploration" in url:
            return _FakeResponse(json_payload=self.metadata)
        return _FakeResponse(
            content_bytes=self.download_bytes,
            headers={"content-type": "application/x-gzip"},
        )

    def post(self, url: str, **kwargs) -> _FakeResponse:
        self.calls.append(("POST", url))
        return _FakeResponse(json_payload=self.querydata)


def _sample_html() -> str:
    return """
    <script>
    var resolvedClusterUri = 'https://wabi-brazil-south-b-primary-redirect.analysis.windows.net/';
    var resourceDescriptor = JSON.parse('{\"k\":\"resource-key-123\",\"t\":\"tenant-id-456\"}');
    </script>
    """


def _sample_metadata() -> dict[str, object]:
    visual_config = {
        "name": "visual-123",
        "singleVisual": {
            "visualType": "pivotTable",
            "projections": {
                "Rows": [{"queryRef": "Microdados.Ano Base", "active": True}],
                "Columns": [{"queryRef": "Microdados.Tipo de microdados", "active": True}],
                "Values": [{"queryRef": "Microdados.MicrodadosURL"}],
            },
            "prototypeQuery": {
                "Version": 2,
                "From": [{"Name": "m", "Entity": "Microdados", "Type": 0}],
                "Select": [
                    {
                        "Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "MicrodadosURL"},
                        "Name": "Microdados.MicrodadosURL",
                    },
                    {
                        "Column": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "Ano Base"},
                        "Name": "Microdados.Ano Base",
                    },
                    {
                        "Column": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "Tipo de microdados"},
                        "Name": "Microdados.Tipo de microdados",
                    },
                ],
            },
        },
    }
    return {
        "models": [{"id": 321, "dbName": "dataset-guid"}],
        "exploration": {
            "report": {
                "id": 987,
                "objectId": "report-guid",
                "modelId": 321,
                "model": {"dbName": "dataset-guid"},
            },
            "sections": [
                {
                    "name": "section-1",
                    "displayName": "Microdados da PNP",
                    "visualContainers": [{"config": json.dumps(visual_config)}],
                }
            ],
        },
    }


def _sample_metadata_without_visual_config() -> dict[str, object]:
    return {
        "models": [{"id": 321, "dbName": "dataset-guid"}],
        "exploration": {
            "report": {
                "id": 987,
                "objectId": "report-guid",
                "modelId": 321,
                "model": {"dbName": "dataset-guid"},
            },
            "sections": [
                {
                    "id": 436918153,
                    "displayName": "Microdados da PNP",
                    "objectId": "6f981727-fd2b-4c02-96db-fd01d317703c",
                    "objectName": "71dc5f10b403dca78121",
                    "visualContainers": [
                        {
                            "id": 10231332861,
                            "objectName": "05245e013098d1766963",
                            "x": 0.0,
                            "y": 0.0,
                            "z": 0.0,
                            "width": 0.0,
                            "height": 0.0,
                        }
                    ],
                }
            ],
        },
    }


def _sample_querydata() -> dict[str, object]:
    return {
        "results": [
            {
                "result": {
                    "data": {
                        "dsr": {
                            "DS": [
                                {
                                    "PH": [
                                        {
                                            "DM0": [
                                                {
                                                    "S": [
                                                        {"N": "G0", "T": 1, "DN": "D0"},
                                                        {"N": "G1", "T": 1, "DN": "D1"},
                                                        {"N": "M0", "T": 13, "DN": "D2"},
                                                    ],
                                                    "C": [0, 0, 0],
                                                },
                                                {"C": [1, 1], "R": 1},
                                                {"C": [1, 2, 2]},
                                            ]
                                        }
                                    ],
                                    "ValueDicts": {
                                        "D0": ["2024", "2023"],
                                        "D1": ["Matrículas", "Servidores", "Financeiro"],
                                        "D2": [
                                            "'https://example.test/microdados_2024_matriculas.csv.gz'",
                                            "'https://example.test/microdados_2024_servidores.csv.gz'",
                                            "'https://example.test/microdados_2023_financeiro.csv.gz'",
                                        ],
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        ]
    }


def test_powerbi_microdados_client_fetches_catalog_and_decodes_compressed_rows() -> None:
    gz_bytes = gzip.compress("coluna_a;coluna_b\n1;2\n".encode("utf-8"))
    session = _FakeSession(_sample_html(), _sample_metadata(), _sample_querydata(), gz_bytes)
    client = PowerBIMicrodadosClient(
        page_url="https://app.powerbi.com/view?r=fake",
        timeout_seconds=15,
        session=session,
    )

    context, entries = client.fetch_catalog()

    assert context.resource_key == "resource-key-123"
    assert context.api_base_url == "https://wabi-brazil-south-b-primary-api.analysis.windows.net"
    assert context.visual_id == "visual-123"
    assert entries == [
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
        MicrodadosCatalogEntry(
            ano_base="2023",
            tipo_microdados="Financeiro",
            microdados_url="https://example.test/microdados_2023_financeiro.csv.gz",
        ),
    ]
    assert session.calls == [
        ("GET", "https://app.powerbi.com/view?r=fake"),
        (
            "GET",
            "https://wabi-brazil-south-b-primary-api.analysis.windows.net/public/reports/resource-key-123/modelsAndExploration?preferReadOnlySession=true",
        ),
        (
            "POST",
            "https://wabi-brazil-south-b-primary-api.analysis.windows.net/public/reports/querydata?synchronous=true",
        ),
    ]


def test_powerbi_microdados_client_fetches_catalog_with_fallback_visual_context() -> None:
    gz_bytes = gzip.compress("coluna_a;coluna_b\n1;2\n".encode("utf-8"))
    session = _FakeSession(_sample_html(), _sample_metadata_without_visual_config(), _sample_querydata(), gz_bytes)
    client = PowerBIMicrodadosClient(
        page_url="https://app.powerbi.com/view?r=fake",
        timeout_seconds=15,
        session=session,
    )

    context, entries = client.fetch_catalog()

    assert context.visual_id == "05245e013098d1766963"
    assert context.visual_type == "microdados_catalog_fallback"
    assert context.prototype_query["Select"][0]["Name"] == "Microdados.MicrodadosURL"
    assert len(entries) == 3


def test_powerbi_microdados_client_downloads_file_and_reads_preview(tmp_path) -> None:
    gz_bytes = gzip.compress("coluna_a;coluna_b\n1;2\n".encode("utf-8"))
    session = _FakeSession(_sample_html(), _sample_metadata(), _sample_querydata(), gz_bytes)
    client = PowerBIMicrodadosClient(
        page_url="https://app.powerbi.com/view?r=fake",
        timeout_seconds=15,
        session=session,
    )

    result = client.download_entry(
        MicrodadosCatalogEntry(
            ano_base="2024",
            tipo_microdados="Matrículas",
            microdados_url="https://example.test/microdados_2024_matriculas.csv.gz",
        ),
        tmp_path,
        preview_line_count=2,
    )

    assert result.size_bytes == len(gz_bytes)
    assert result.content_type == "application/x-gzip"
    assert result.preview_lines == ("coluna_a;coluna_b", "1;2")
    assert result.output_path.endswith("microdados_2024_matriculas.csv.gz")


def test_powerbi_microdados_client_decodes_cp1252_content() -> None:
    header = "Classe;Instituição;Número_de_registros\nD;IFPR;1\n".encode("cp1252")
    payload = gzip.compress(header)

    decoded = PowerBIMicrodadosClient.decode_content_bytes(
        payload,
        "https://example.test/microdados_servidores_2024.csv.gz",
    )

    assert "Instituição" in decoded
    assert "Número_de_registros" in decoded


def test_connector_fetch_supports_powerbi_microdados_mode(monkeypatch) -> None:
    context = PowerBIMicrodadosContext(
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
    entries = [
        MicrodadosCatalogEntry(
            ano_base="2024",
            tipo_microdados="Matrículas",
            microdados_url="https://example.test/microdados_2024_matriculas.csv.gz",
        ),
    ]

    class _FakeClient:
        def __init__(self, page_url: str, timeout_seconds: int) -> None:
            self.page_url = page_url
            self.timeout_seconds = timeout_seconds
            self.fetch_catalog_called = False

        def discover_context(self) -> PowerBIMicrodadosContext:
            return context

        def fetch_catalog(self) -> tuple[PowerBIMicrodadosContext, list[MicrodadosCatalogEntry]]:
            self.fetch_catalog_called = True
            return context, entries

        def fetch_entry_content(self, entry: MicrodadosCatalogEntry) -> MicrodadosContentResult:
            payload = gzip.compress("Código da Matricula;Nome\n123;Alice\n456;Bruno\n".encode("utf-8"))
            return MicrodadosContentResult(
                source_url=entry.microdados_url,
                content_bytes=payload,
                size_bytes=len(payload),
                sha256="sha-test",
                content_type="application/x-gzip",
            )

        @staticmethod
        def decode_content_bytes(content_bytes: bytes, source_url: str) -> str:
            return gzip.decompress(content_bytes).decode("utf-8")

    monkeypatch.setattr(
        "dataif_pipelines.connectors.nilo_pecanha.connector.powerbi_catalog_service.create_powerbi_client",
        lambda page_url, timeout_seconds: _FakeClient(page_url=page_url, timeout_seconds=timeout_seconds),
    )

    connector = NiloPecanhaConnector(
        dsn="postgresql://example",
        config=NiloConfig(
            endpoint="https://app.powerbi.com/view?r=fake",
            timeout_seconds=30,
        ),
    )
    endpoint = EndpointDefinition(
        id=77,
        endpoint_key="pnp_publico__microdados",
        description="Microdados publicos via Power BI",
        page_url="https://app.powerbi.com/view?r=fake",
        api_endpoint_url=None,
        csv_url=None,
        dictionary_url=None,
        request_params={
            "mode": "powerbi_microdados",
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
    monkeypatch.setattr(connector, "_load_active_endpoints", lambda instance_key=None: [endpoint])

    records = connector.fetch(
        RunContext(
            run_id="run-powerbi",
            started_at=datetime(2026, 3, 16, 0, 0, 0),
            source_url="https://app.powerbi.com/view?r=fake",
        )
    )

    assert len(records) == 2
    assert records[0]["source_url"] == "https://example.test/microdados_2024_matriculas.csv.gz"
    assert records[0]["endpoint_id"] == 77
    assert records[0]["endpoint_key"] == "pnp_publico__microdados"
    assert records[0]["payload"]["Código da Matricula"] == "123"
    assert records[0]["payload"]["source_row_number"] == 1
    assert records[0]["payload"]["dataset"] == "pnp_microdados_matriculas"
    assert records[1]["payload"]["Código da Matricula"] == "456"
    assert records[1]["payload"]["source_row_number"] == 2

    assert [item["asset_type"] for item in connector._pending_assets] == [
        "powerbi_microdados_download",
        "powerbi_microdados_manifest",
    ]
    assert connector._pending_downloads[0]["headers"] == ("Código da Matricula", "Nome")
    assert connector._pending_downloads[0]["normalized_headers"]["Código da Matricula"] == "codigo_da_matricula"
    manifest = json.loads(connector._pending_assets[1]["content_text"])
    assert manifest["context"]["visual_id"] == "visual-123"
    assert manifest["selection_source"] == "selected_downloads"
    assert manifest["selected_years"] == ["2024"]
    assert [item["tipo_microdados"] for item in manifest["entries"]] == ["Matrículas"]


def test_connector_extract_and_load_raw_streams_in_chunks(monkeypatch) -> None:
    context = PowerBIMicrodadosContext(
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
    entry = MicrodadosCatalogEntry(
        ano_base="2024",
        tipo_microdados="Matrículas",
        microdados_url="https://example.test/microdados_2024_matriculas.csv.gz",
    )

    class _FakeClient:
        def __init__(self, page_url: str, timeout_seconds: int) -> None:
            self.page_url = page_url
            self.timeout_seconds = timeout_seconds

        def fetch_catalog(self) -> tuple[PowerBIMicrodadosContext, list[MicrodadosCatalogEntry]]:
            return context, [entry]

        def fetch_entry_content(self, selected_entry: MicrodadosCatalogEntry) -> MicrodadosContentResult:
            payload = gzip.compress(
                (
                    "Código da Matricula;Nome\n"
                    "1;Alice\n"
                    "2;Bruno\n"
                    "3;Carla\n"
                    "4;Diego\n"
                    "5;Eva\n"
                ).encode("utf-8")
            )
            return MicrodadosContentResult(
                source_url=selected_entry.microdados_url,
                content_bytes=payload,
                size_bytes=len(payload),
                sha256="sha-stream",
                content_type="application/x-gzip",
            )

    monkeypatch.setattr(
        "dataif_pipelines.connectors.nilo_pecanha.connector.powerbi_catalog_service.create_powerbi_client",
        lambda page_url, timeout_seconds: _FakeClient(page_url=page_url, timeout_seconds=timeout_seconds),
    )

    metadata_calls: list[dict[str, object]] = []
    chunk_sizes: list[int] = []

    def _fake_upsert_raw_metadata(dsn: str, **kwargs):
        metadata_calls.append(kwargs)
        pending_downloads = list(kwargs.get("pending_downloads") or [])
        download_id_by_url = {}
        if pending_downloads:
            download_id_by_url = {str(pending_downloads[0]["microdados_url"]): 501}
        return {
            "asset_count": len(list(kwargs.get("pending_assets") or [])),
            "download_column_count": len(tuple(pending_downloads[0]["headers"])) if pending_downloads else 0,
            "download_id_by_url": download_id_by_url,
        }

    def _fake_normalize_raw_records(raw_records, run_context):
        return pnp_raw_ingestion_service.NormalizationResult(
            normalized_records=[{"raw_table_name": "pnp_matriculas_src"} for _ in raw_records],
            quarantine_rows=[],
        )

    def _fake_load_raw_record_chunk(dsn: str, **kwargs):
        normalized_records = list(kwargs.get("normalized_records") or [])
        chunk_sizes.append(len(normalized_records))
        return {
            "raw_record_count": len(normalized_records),
            "quarantine_count": len(list(kwargs.get("pending_quarantine") or [])),
            "asset_count": 0,
        }

    monkeypatch.setattr(
        "dataif_pipelines.connectors.nilo_pecanha.connector.pnp_raw_ingestion_service.upsert_raw_metadata",
        _fake_upsert_raw_metadata,
    )
    monkeypatch.setattr(
        "dataif_pipelines.connectors.nilo_pecanha.connector.pnp_raw_ingestion_service.normalize_raw_records",
        _fake_normalize_raw_records,
    )
    monkeypatch.setattr(
        "dataif_pipelines.connectors.nilo_pecanha.connector.pnp_raw_ingestion_service.load_raw_record_chunk",
        _fake_load_raw_record_chunk,
    )

    connector = NiloPecanhaConnector(
        dsn="postgresql://example",
        config=NiloConfig(
            endpoint="https://app.powerbi.com/view?r=fake",
            timeout_seconds=30,
        ),
    )
    connector._STREAM_BATCH_SIZE = 2
    endpoint = EndpointDefinition(
        id=77,
        endpoint_key="pnp_publico__microdados",
        description="Microdados publicos via Power BI",
        page_url="https://app.powerbi.com/view?r=fake",
        api_endpoint_url=None,
        csv_url=None,
        dictionary_url=None,
        request_params={
            "mode": "powerbi_microdados",
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
    monkeypatch.setattr(connector, "_load_active_endpoints", lambda instance_key=None: [endpoint])

    loaded = connector.extract_and_load_raw(
        RunContext(
            run_id="run-stream",
            started_at=datetime(2026, 3, 16, 0, 0, 0),
            source_url="https://app.powerbi.com/view?r=fake",
        )
    )

    assert loaded == 5
    assert chunk_sizes == [2, 2, 1]
    assert connector.runtime_stats()["download_count"] == 1
    assert connector.runtime_stats()["raw_domain_count"] == 5
    assert len(metadata_calls) == 4
    assert len(metadata_calls[0]["pending_catalog_entries"]) == 1
    assert metadata_calls[1]["pending_downloads"][0]["status"] == "running"
    assert metadata_calls[2]["pending_downloads"][0]["status"] == "success"
    assert metadata_calls[3]["pending_assets"][0]["asset_type"] == "powerbi_microdados_manifest"
