from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from dataif_pipelines.connectors.base.connector import BaseConnector
from dataif_pipelines.connectors.base.types import NormalizedRecord, RawRecord, RunContext
from dataif_pipelines.connectors.nilo_pecanha.config import NiloConfig, load_config
from dataif_pipelines.services import (
    pnp_download_service,
    pnp_quality_service,
    pnp_raw_ingestion_service,
    powerbi_catalog_service,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EndpointDefinition:
    id: int
    endpoint_key: str
    description: str | None
    page_url: str | None
    api_endpoint_url: str | None
    csv_url: str | None
    dictionary_url: str | None
    request_params: dict[str, Any]


class NiloPecanhaConnector(BaseConnector):
    _STREAM_BATCH_SIZE = 250

    def __init__(self, dsn: str | None = None, config: NiloConfig | None = None) -> None:
        self.dsn = dsn or os.environ["WAREHOUSE_DSN"]
        self.config = config or load_config()
        self._pending_assets: list[dict[str, Any]] = []
        self._pending_catalog_entries: list[dict[str, Any]] = []
        self._pending_run_selection: list[dict[str, Any]] = []
        self._pending_downloads: list[dict[str, Any]] = []
        self._pending_quarantine: list[dict[str, Any]] = []
        self._last_asset_count = 0
        self._last_endpoint_count = 0
        self._download_count = 0
        self._last_download_column_count = 0
        self._last_quarantine_count = 0
        self._last_raw_domain_count = 0

    def connector_id(self) -> str:
        return "nilo_pecanha"

    def runtime_stats(self) -> dict[str, int]:
        return {
            "endpoint_count": self._last_endpoint_count,
            "asset_count": self._last_asset_count,
            "download_count": self._download_count,
            "download_column_count": self._last_download_column_count,
            "quarantine_count": self._last_quarantine_count,
            "raw_domain_count": self._last_raw_domain_count,
        }

    def fetch(self, run_context: RunContext, instance_key: str | None = None) -> list[RawRecord]:
        self._reset_pending_state()

        endpoints = self._load_active_endpoints(instance_key=instance_key)
        self._last_endpoint_count = len(endpoints)

        wrapped_records: list[RawRecord] = []
        for endpoint in endpoints:
            mode = str((endpoint.request_params or {}).get("mode") or "").strip().lower()
            if mode != "powerbi_microdados":
                logger.warning("Skipping unsupported nilo_pecanha endpoint mode=%s endpoint_key=%s", mode, endpoint.endpoint_key)
                continue

            payloads = self._fetch_powerbi_microdados_records(endpoint, run_context.run_id)
            wrapped_records.extend(
                self._wrap_payloads(
                    payloads=payloads,
                    endpoint=endpoint,
                    source_kind="powerbi_microdados",
                )
            )

        logger.info(
            "Fetched connector=%s endpoints=%s records=%s assets=%s downloads=%s",
            self.connector_id(),
            self._last_endpoint_count,
            len(wrapped_records),
            len(self._pending_assets),
            len(self._pending_downloads),
        )
        return wrapped_records

    def extract_and_load_raw(self, run_context: RunContext, instance_key: str | None = None) -> int:
        self._reset_pending_state()
        endpoints = self._load_active_endpoints(instance_key=instance_key)
        self._last_endpoint_count = len(endpoints)
        logger.info(
            "Starting streaming raw extraction connector=%s instance_key=%s endpoints=%s run_id=%s",
            self.connector_id(),
            instance_key,
            self._last_endpoint_count,
            run_context.run_id,
        )

        total_loaded = 0
        total_assets = 0
        total_download_columns = 0
        total_quarantine = 0

        for endpoint in endpoints:
            mode = str((endpoint.request_params or {}).get("mode") or "").strip().lower()
            if mode != "powerbi_microdados":
                logger.warning("Skipping unsupported nilo_pecanha endpoint mode=%s endpoint_key=%s", mode, endpoint.endpoint_key)
                continue

            logger.info(
                "Starting endpoint extraction endpoint_key=%s description=%s",
                endpoint.endpoint_key,
                endpoint.description,
            )
            endpoint_stats = self._extract_powerbi_microdados_streaming(endpoint, run_context)
            total_loaded += int(endpoint_stats.get("raw_record_count") or 0)
            total_assets += int(endpoint_stats.get("asset_count") or 0)
            total_download_columns += int(endpoint_stats.get("download_column_count") or 0)
            total_quarantine += int(endpoint_stats.get("quarantine_count") or 0)
            logger.info(
                "Finished endpoint extraction endpoint_key=%s raw_records=%s quarantine=%s downloads=%s",
                endpoint.endpoint_key,
                int(endpoint_stats.get("raw_record_count") or 0),
                int(endpoint_stats.get("quarantine_count") or 0),
                self._download_count,
            )

        self._last_asset_count = total_assets
        self._last_download_column_count = total_download_columns
        self._last_quarantine_count = total_quarantine
        self._last_raw_domain_count = total_loaded
        logger.info(
            "Buffered raw load completed connector=%s endpoints=%s downloads=%s raw_records=%s",
            self.connector_id(),
            self._last_endpoint_count,
            self._download_count,
            total_loaded,
        )
        return total_loaded

    def normalize(self, raw_records: list[RawRecord], run_context: RunContext) -> list[NormalizedRecord]:
        result = pnp_raw_ingestion_service.normalize_raw_records(raw_records, run_context)
        self._pending_quarantine.extend(result.quarantine_rows)
        return result.normalized_records

    def load_raw(self, normalized_records: list[NormalizedRecord], run_context: RunContext) -> int:
        stats = pnp_raw_ingestion_service.load_raw_batch(
            self.dsn,
            normalized_records=normalized_records,
            pending_assets=self._pending_assets,
            pending_catalog_entries=self._pending_catalog_entries,
            pending_run_selection=self._pending_run_selection,
            pending_downloads=self._pending_downloads,
            pending_quarantine=self._pending_quarantine,
            write_legacy=False,
        )

        self._last_asset_count = int(stats.get("asset_count") or 0)
        self._last_download_column_count = int(stats.get("download_column_count") or 0)
        self._last_quarantine_count = int(stats.get("quarantine_count") or 0)
        self._last_raw_domain_count = int(stats.get("raw_record_count") or 0)
        return self._last_raw_domain_count

    def post_load_checks(self, run_id: str) -> dict[str, object]:
        return pnp_quality_service.collect_run_checks(self.dsn, run_id)

    def _reset_pending_state(self) -> None:
        self._pending_assets = []
        self._pending_catalog_entries = []
        self._pending_run_selection = []
        self._pending_downloads = []
        self._pending_quarantine = []
        self._download_count = 0
        self._last_asset_count = 0
        self._last_download_column_count = 0
        self._last_quarantine_count = 0
        self._last_raw_domain_count = 0

    def _load_active_endpoints(self, instance_key: str | None = None) -> list[EndpointDefinition]:
        query = """
            SELECT
              pe.pipeline_endpoint_id AS id,
              pe.endpoint_key,
              CONCAT(i.instance_name, ' - ', et.endpoint_name) AS description,
              i.page_url,
              NULL::TEXT AS api_endpoint_url,
              NULL::TEXT AS csv_url,
              NULL::TEXT AS dictionary_url,
              jsonb_build_object(
                'mode', 'powerbi_microdados',
                'entity_type', 'pipeline',
                'instance_key', i.instance_key,
                'instance_name', i.instance_name,
                'pipeline_key', i.instance_key,
                'pipeline_name', i.instance_name,
                'connection_key', i.connection_key,
                'connection_name', i.connection_name,
                'endpoint_key', pe.endpoint_key,
                'endpoint_name', et.endpoint_name,
                'selected_years', COALESCE(sel.selected_years, '[]'::jsonb),
                'selected_microdados_types', jsonb_build_array(et.tipo_microdados),
                'selected_downloads', COALESCE(sel.selected_downloads, '[]'::jsonb),
                'selected_source_label', 'Catalogo publico de microdados via Power BI',
                'selected_source_group', 'Microdados Publicos',
                'source_path', 'powerbi_microdados'
              ) AS request_params
            FROM raw.pnp_pipeline_endpoints pe
            JOIN raw.pnp_instances i
              ON i.instance_key = pe.instance_key
            JOIN raw.pnp_endpoint_tables et
              ON et.endpoint_key = pe.endpoint_key
            LEFT JOIN LATERAL (
              SELECT
                to_jsonb(ARRAY_AGG(DISTINCT s.ano_base ORDER BY s.ano_base DESC)) AS selected_years,
                to_jsonb(
                  ARRAY_AGG(
                    jsonb_build_object(
                      'ano_base', s.ano_base,
                      'tipo_microdados', s.tipo_microdados,
                      'microdados_url', s.configured_microdados_url
                    )
                    ORDER BY COALESCE(s.selection_rank, 2147483647), s.ano_base DESC
                  ) FILTER (WHERE s.configured_microdados_url IS NOT NULL)
                ) AS selected_downloads
              FROM raw.pnp_instance_selection s
              WHERE s.instance_key = i.instance_key
                AND s.is_active = TRUE
                AND s.tipo_microdados = et.tipo_microdados
            ) sel ON TRUE
            WHERE i.is_active = TRUE
              AND i.deleted_at IS NULL
              AND pe.is_active = TRUE
              AND et.is_active = TRUE
        """
        params: list[Any] = []
        if instance_key:
            query += " AND i.instance_key = %s"
            params.append(instance_key)
        query += " ORDER BY i.instance_key, pe.pipeline_endpoint_id"

        with psycopg2.connect(self.dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        return [
            EndpointDefinition(
                id=int(row["id"]),
                endpoint_key=str(row["endpoint_key"]),
                description=row.get("description"),
                page_url=row.get("page_url"),
                api_endpoint_url=row.get("api_endpoint_url"),
                csv_url=row.get("csv_url"),
                dictionary_url=row.get("dictionary_url"),
                request_params=dict(row.get("request_params") or {}),
            )
            for row in rows
        ]

    def _fetch_powerbi_microdados_records(self, endpoint: EndpointDefinition, run_id: str) -> list[dict[str, Any]]:
        if not endpoint.page_url:
            raise RuntimeError("powerbi_microdados mode requires page_url")

        request_params = dict(endpoint.request_params or {})
        client = powerbi_catalog_service.create_powerbi_client(
            page_url=endpoint.page_url,
            timeout_seconds=self.config.timeout_seconds,
        )
        selection = powerbi_catalog_service.resolve_catalog_selection(
            client=client,
            request_params=request_params,
        )
        self._pending_catalog_entries.extend(
            powerbi_catalog_service.build_catalog_entry_rows(run_id=run_id, selection=selection)
        )
        self._pending_run_selection.extend(
            powerbi_catalog_service.build_run_selection_rows(run_id=run_id, selection=selection)
        )

        batch = pnp_download_service.build_download_batch(
            client=client,
            run_id=run_id,
            endpoint_id=endpoint.id,
            endpoint_key=endpoint.endpoint_key,
            selection=selection,
        )
        self._pending_assets.extend(batch.assets)
        self._pending_downloads.extend(batch.downloads)
        self._pending_quarantine.extend(batch.quarantine_rows)
        self._download_count += len(batch.downloads)
        return batch.records

    def _extract_powerbi_microdados_streaming(self, endpoint: EndpointDefinition, run_context: RunContext) -> dict[str, int]:
        if not endpoint.page_url:
            raise RuntimeError("powerbi_microdados mode requires page_url")

        request_params = dict(endpoint.request_params or {})
        client = powerbi_catalog_service.create_powerbi_client(
            page_url=endpoint.page_url,
            timeout_seconds=self.config.timeout_seconds,
        )
        selection = powerbi_catalog_service.resolve_catalog_selection(
            client=client,
            request_params=request_params,
        )
        catalog_entries = powerbi_catalog_service.build_catalog_entry_rows(run_id=run_context.run_id, selection=selection)
        run_selection_rows = powerbi_catalog_service.build_run_selection_rows(run_id=run_context.run_id, selection=selection)
        run_selection_by_url = {str(row["microdados_url"]): row for row in run_selection_rows}

        stats = pnp_raw_ingestion_service.upsert_raw_metadata(
            self.dsn,
            pending_assets=[],
            pending_catalog_entries=catalog_entries,
            pending_run_selection=[],
            pending_downloads=[],
            write_legacy=False,
        )
        total_asset_count = int(stats.get("asset_count") or 0)
        total_download_columns = int(stats.get("download_column_count") or 0)
        total_quarantine = 0
        total_raw_records = 0
        manifest_downloads: list[dict[str, Any]] = []

        for selection_rank, entry in enumerate(selection.selected_entries, start=1):
            source_file_name = pnp_download_service.resolve_source_file_name(entry)
            logger.info(
                "Starting download endpoint_key=%s selection_rank=%s ano=%s tipo=%s file=%s url=%s",
                endpoint.endpoint_key,
                selection_rank,
                entry.ano_base,
                entry.tipo_microdados,
                source_file_name,
                entry.microdados_url,
            )
            with client.open_entry_content_stream(entry) as content_stream:
                streamed = pnp_download_service.stream_csv_binary_stream(content_stream.raw_stream, entry.microdados_url)
                running_download = pnp_download_service.build_download_row(
                    run_id=run_context.run_id,
                    instance_key=selection.instance_key,
                    entry=entry,
                    source_file_name=source_file_name,
                    source_file_sha256="",
                    content_type=content_stream.content_type,
                    size_bytes=0,
                    row_count_raw=0,
                    delimiter=streamed.delimiter,
                    selection_source=selection.selection_source,
                    selection_rank=selection_rank,
                    headers=streamed.headers,
                    status="running",
                    error_message=None,
                )
                metadata_stats = pnp_raw_ingestion_service.upsert_raw_metadata(
                    self.dsn,
                    pending_assets=[],
                    pending_catalog_entries=[],
                    pending_run_selection=[run_selection_by_url[entry.microdados_url]],
                    pending_downloads=[running_download],
                    write_legacy=False,
                    include_download_columns=True,
                )
                download_id_by_url = dict(metadata_stats.get("download_id_by_url") or {})
                total_asset_count += int(metadata_stats.get("asset_count") or 0)
                total_download_columns += int(metadata_stats.get("download_column_count") or 0)

                raw_chunk: list[RawRecord] = []
                quarantine_chunk: list[dict[str, Any]] = []
                row_count = 0
                invalid_row_count = 0
                flushed_batches = 0

                for row_result in streamed.row_results:
                    if row_result.invalid_row:
                        quarantine_chunk.append(
                            pnp_download_service.build_quarantine_row(
                                run_id=run_context.run_id,
                                instance_key=selection.instance_key,
                                entry=entry,
                                invalid_row=row_result.invalid_row,
                            )
                        )
                        invalid_row_count += 1

                    if row_result.row:
                        row_count += 1
                        raw_chunk.append(
                            {
                                "payload": pnp_download_service.build_record_payload(
                                    row=row_result.row,
                                    row_number=row_result.source_row_number,
                                    entry=entry,
                                    selection=selection,
                                    source_file_name=source_file_name,
                                    source_file_sha256="",
                                ),
                                "source_url": entry.microdados_url,
                                "endpoint_id": endpoint.id,
                                "endpoint_key": endpoint.endpoint_key,
                                "source_kind": "powerbi_microdados",
                            }
                        )

                    if len(raw_chunk) >= self._STREAM_BATCH_SIZE or len(quarantine_chunk) >= self._STREAM_BATCH_SIZE:
                        chunk_stats = self._flush_streaming_chunk(raw_chunk, quarantine_chunk, run_context, download_id_by_url)
                        total_raw_records += int(chunk_stats.get("raw_record_count") or 0)
                        total_quarantine += int(chunk_stats.get("quarantine_count") or 0)
                        total_asset_count += int(chunk_stats.get("asset_count") or 0)
                        flushed_batches += 1
                        if flushed_batches == 1 or flushed_batches % 100 == 0:
                            logger.info(
                                "Streaming progress endpoint_key=%s file=%s rows=%s invalid_rows=%s flushed_batches=%s raw_records_total=%s",
                                endpoint.endpoint_key,
                                source_file_name,
                                row_count,
                                invalid_row_count,
                                flushed_batches,
                                total_raw_records,
                            )

                if raw_chunk or quarantine_chunk:
                    chunk_stats = self._flush_streaming_chunk(raw_chunk, quarantine_chunk, run_context, download_id_by_url)
                    total_raw_records += int(chunk_stats.get("raw_record_count") or 0)
                    total_quarantine += int(chunk_stats.get("quarantine_count") or 0)
                    total_asset_count += int(chunk_stats.get("asset_count") or 0)
                    flushed_batches += 1

                final_download = pnp_download_service.build_download_row(
                    run_id=run_context.run_id,
                    instance_key=selection.instance_key,
                    entry=entry,
                    source_file_name=source_file_name,
                    source_file_sha256=content_stream.sha256 or "",
                    content_type=content_stream.content_type,
                    size_bytes=content_stream.size_bytes,
                    row_count_raw=row_count,
                    delimiter=streamed.delimiter,
                    selection_source=selection.selection_source,
                    selection_rank=selection_rank,
                    headers=streamed.headers,
                    status="success",
                    error_message=None,
                )
                manifest_downloads.append(final_download)
                download_asset = pnp_download_service.build_download_asset_row(
                    run_id=run_context.run_id,
                    endpoint_id=endpoint.id,
                    endpoint_key=endpoint.endpoint_key,
                    entry=entry,
                    source_file_name=source_file_name,
                    content_type=content_stream.content_type,
                    size_bytes=content_stream.size_bytes,
                    sha256=content_stream.sha256 or "",
                    row_count=row_count,
                    headers=streamed.headers,
                )
            final_stats = pnp_raw_ingestion_service.upsert_raw_metadata(
                self.dsn,
                pending_assets=[download_asset],
                pending_catalog_entries=[],
                pending_run_selection=[],
                pending_downloads=[final_download],
                write_legacy=False,
                include_download_columns=False,
            )
            total_asset_count += int(final_stats.get("asset_count") or 0)
            self._download_count += 1
            logger.info(
                "Buffered download loaded endpoint_key=%s file=%s rows=%s invalid_rows=%s flushed_batches=%s size_bytes=%s",
                endpoint.endpoint_key,
                source_file_name,
                row_count,
                invalid_row_count,
                flushed_batches,
                content_stream.size_bytes,
            )

        manifest_asset = pnp_download_service.build_manifest_asset_row(
            run_id=run_context.run_id,
            endpoint_id=endpoint.id,
            endpoint_key=endpoint.endpoint_key,
            selection=selection,
            downloads=manifest_downloads,
            raw_record_count=sum(int(item.get("row_count_raw") or 0) for item in manifest_downloads),
        )
        manifest_stats = pnp_raw_ingestion_service.upsert_raw_metadata(
            self.dsn,
            pending_assets=[manifest_asset],
            pending_catalog_entries=[],
            pending_run_selection=[],
            pending_downloads=[],
            write_legacy=False,
        )
        total_asset_count += int(manifest_stats.get("asset_count") or 0)

        return {
            "asset_count": total_asset_count,
            "download_column_count": total_download_columns,
            "quarantine_count": total_quarantine,
            "raw_record_count": total_raw_records,
        }

    def _flush_streaming_chunk(
        self,
        raw_chunk: list[RawRecord],
        quarantine_chunk: list[dict[str, Any]],
        run_context: RunContext,
        download_id_by_url: dict[str, int],
    ) -> dict[str, int]:
        if not raw_chunk and not quarantine_chunk:
            return {"raw_record_count": 0, "quarantine_count": 0, "asset_count": 0}

        normalization_result = pnp_raw_ingestion_service.normalize_raw_records(raw_chunk, run_context)
        pending_quarantine = [*quarantine_chunk, *normalization_result.quarantine_rows]
        stats = pnp_raw_ingestion_service.load_raw_record_chunk(
            self.dsn,
            normalized_records=normalization_result.normalized_records,
            pending_quarantine=pending_quarantine,
            download_id_by_url=download_id_by_url,
            pending_assets=[],
            write_legacy=False,
        )
        raw_chunk.clear()
        quarantine_chunk.clear()
        return stats


    @staticmethod
    def _parse_csv(content: str) -> pnp_download_service.ParsedCsvContent:
        return pnp_download_service.parse_csv_content(content)

    @staticmethod
    def _wrap_payloads(
        payloads: list[dict[str, Any]],
        endpoint: EndpointDefinition,
        source_kind: str,
    ) -> list[RawRecord]:
        return [
            {
                "payload": payload,
                "source_url": str(payload.get("microdados_url") or endpoint.page_url or ""),
                "endpoint_id": endpoint.id,
                "endpoint_key": endpoint.endpoint_key,
                "source_kind": source_kind,
            }
            for payload in payloads
            if isinstance(payload, dict)
        ]
