from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from dataif_pipelines.connectors.nilo_pecanha.powerbi_microdados import MicrodadosCatalogEntry, PowerBIMicrodadosClient
from dataif_pipelines.services.powerbi_catalog_service import CatalogSelectionResult


@dataclass(frozen=True)
class ParsedCsvContent:
    headers: tuple[str, ...]
    rows: list[dict[str, Any]]
    delimiter: str
    invalid_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class DownloadBatch:
    records: list[dict[str, Any]]
    downloads: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    quarantine_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class CsvRowResult:
    source_row_number: int
    row: dict[str, Any] | None
    invalid_row: dict[str, Any] | None


@dataclass(frozen=True)
class StreamedCsvContent:
    headers: tuple[str, ...]
    delimiter: str
    row_results: Iterator[CsvRowResult]


def normalize_column_name(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    collapsed = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return collapsed or "coluna"


def parse_csv_content(content: str) -> ParsedCsvContent:
    if not content:
        return ParsedCsvContent(headers=(), rows=[], delimiter=",", invalid_rows=[])

    lines = content.splitlines()
    first_line = lines[0] if lines else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    stream = io.StringIO(content)
    reader = csv.DictReader(stream, delimiter=delimiter)
    headers = tuple(str(item).strip() for item in (reader.fieldnames or []) if item is not None)
    rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []

    for row_number, row in enumerate(reader, start=1):
        extras = row.get(None)
        if extras:
            invalid_rows.append(
                {
                    "source_row_number": row_number,
                    "error_type": "csv_extra_columns",
                    "error_message": "row has extra columns beyond the detected header",
                    "raw_line_text": json.dumps(extras, ensure_ascii=True),
                }
            )

        cleaned = {
            str(key).strip(): (value.strip() if isinstance(value, str) else value)
            for key, value in row.items()
            if key is not None
        }
        if cleaned:
            rows.append(cleaned)

    return ParsedCsvContent(headers=headers, rows=rows, delimiter=delimiter, invalid_rows=invalid_rows)


def decode_content_bytes(content_bytes: bytes, source_url: str) -> str:
    content = content_bytes
    if source_url.endswith(".gz"):
        content = gzip.decompress(content_bytes)
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def stream_csv_content(content_bytes: bytes, source_url: str) -> StreamedCsvContent:
    if not content_bytes:
        return StreamedCsvContent(headers=(), delimiter=",", row_results=iter(()))

    binary_factory = _build_binary_factory(content_bytes, source_url)
    encoding = _detect_content_encoding(binary_factory)
    text_stream = io.TextIOWrapper(binary_factory(), encoding=encoding, errors="replace", newline="")
    first_line = text_stream.readline()
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(_iter_text_lines(first_line, text_stream), delimiter=delimiter)
    headers = tuple(str(item).strip() for item in (reader.fieldnames or []) if item is not None)

    def _row_iter() -> Iterator[CsvRowResult]:
        try:
            for row_number, row in enumerate(reader, start=1):
                extras = row.get(None)
                invalid_row = None
                if extras:
                    invalid_row = {
                        "source_row_number": row_number,
                        "error_type": "csv_extra_columns",
                        "error_message": "row has extra columns beyond the detected header",
                        "raw_line_text": json.dumps(extras, ensure_ascii=True),
                    }

                cleaned = {
                    str(key).strip(): (value.strip() if isinstance(value, str) else value)
                    for key, value in row.items()
                    if key is not None
                }
                yield CsvRowResult(
                    source_row_number=row_number,
                    row=cleaned or None,
                    invalid_row=invalid_row,
                )
        finally:
            text_stream.close()

    return StreamedCsvContent(headers=headers, delimiter=delimiter, row_results=_row_iter())


def stream_csv_binary_stream(binary_stream, source_url: str) -> StreamedCsvContent:
    buffered_raw = io.BufferedReader(binary_stream)
    decoded_binary_stream = gzip.GzipFile(fileobj=buffered_raw) if source_url.endswith(".gz") else buffered_raw
    buffered_decoded_stream = io.BufferedReader(decoded_binary_stream)
    sample = buffered_decoded_stream.peek(65536)[:65536]
    encoding = _detect_bytes_encoding(sample)
    text_stream = io.TextIOWrapper(buffered_decoded_stream, encoding=encoding, errors="replace", newline="")
    first_line = text_stream.readline()
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.DictReader(_iter_text_lines(first_line, text_stream), delimiter=delimiter)
    headers = tuple(str(item).strip() for item in (reader.fieldnames or []) if item is not None)

    def _row_iter() -> Iterator[CsvRowResult]:
        try:
            for row_number, row in enumerate(reader, start=1):
                extras = row.get(None)
                invalid_row = None
                if extras:
                    invalid_row = {
                        "source_row_number": row_number,
                        "error_type": "csv_extra_columns",
                        "error_message": "row has extra columns beyond the detected header",
                        "raw_line_text": json.dumps(extras, ensure_ascii=True),
                    }

                cleaned = {
                    str(key).strip(): (value.strip() if isinstance(value, str) else value)
                    for key, value in row.items()
                    if key is not None
                }
                yield CsvRowResult(
                    source_row_number=row_number,
                    row=cleaned or None,
                    invalid_row=invalid_row,
                )
        finally:
            text_stream.close()

    return StreamedCsvContent(headers=headers, delimiter=delimiter, row_results=_row_iter())


def build_download_batch(
    *,
    client: PowerBIMicrodadosClient,
    run_id: str,
    endpoint_id: int,
    endpoint_key: str,
    selection: CatalogSelectionResult,
) -> DownloadBatch:
    records: list[dict[str, Any]] = []
    downloads: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    total_record_count = 0

    for selection_rank, entry in enumerate(selection.selected_entries, start=1):
        content = client.fetch_entry_content(entry)
        streamed = stream_csv_content(content.content_bytes, entry.microdados_url)
        source_file_name = resolve_source_file_name(entry)
        row_count = 0

        for row_result in streamed.row_results:
            if row_result.invalid_row:
                quarantine_rows.append(
                    build_quarantine_row(
                        run_id=run_id,
                        instance_key=selection.instance_key,
                        entry=entry,
                        invalid_row=row_result.invalid_row,
                    )
                )

            if not row_result.row:
                continue

            row_count += 1
            records.append(
                build_record_payload(
                    row=row_result.row,
                    row_number=row_result.source_row_number,
                    entry=entry,
                    selection=selection,
                    source_file_name=source_file_name,
                    source_file_sha256=content.sha256,
                )
            )

        total_record_count += row_count
        download_row = build_download_row(
            run_id=run_id,
            instance_key=selection.instance_key,
            entry=entry,
            source_file_name=source_file_name,
            source_file_sha256=content.sha256,
            content_type=content.content_type,
            size_bytes=content.size_bytes,
            row_count_raw=row_count,
            delimiter=streamed.delimiter,
            selection_source=selection.selection_source,
            selection_rank=selection_rank,
            headers=streamed.headers,
            status="success",
            error_message=None,
        )
        downloads.append(download_row)
        assets.append(
            build_download_asset_row(
                run_id=run_id,
                endpoint_id=endpoint_id,
                endpoint_key=endpoint_key,
                entry=entry,
                source_file_name=source_file_name,
                content_type=content.content_type,
                size_bytes=content.size_bytes,
                sha256=content.sha256,
                row_count=row_count,
                headers=streamed.headers,
            )
        )

    assets.append(
        build_manifest_asset_row(
            run_id=run_id,
            endpoint_id=endpoint_id,
            endpoint_key=endpoint_key,
            selection=selection,
            downloads=downloads,
            raw_record_count=total_record_count,
        )
    )
    return DownloadBatch(records=records, downloads=downloads, assets=assets, quarantine_rows=quarantine_rows)


def resolve_source_file_name(entry: MicrodadosCatalogEntry) -> str:
    return urlparse(entry.microdados_url).path.rsplit("/", 1)[-1] or f"{entry.ano_base}.csv"


def build_download_row(
    *,
    run_id: str,
    instance_key: str | None,
    entry: MicrodadosCatalogEntry,
    source_file_name: str,
    source_file_sha256: str,
    content_type: str | None,
    size_bytes: int,
    row_count_raw: int,
    delimiter: str,
    selection_source: str,
    selection_rank: int,
    headers: tuple[str, ...],
    status: str,
    error_message: str | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "instance_key": instance_key,
        "ano_base": entry.ano_base,
        "tipo_microdados": entry.tipo_microdados,
        "microdados_url": entry.microdados_url,
        "source_file_name": source_file_name,
        "source_file_sha256": source_file_sha256,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "row_count_raw": row_count_raw,
        "status": status,
        "error_message": error_message,
        "details_json": {
            "delimiter": delimiter,
            "selection_source": selection_source,
            "selection_rank": selection_rank,
            "header_count": len(headers),
        },
        "headers": headers,
        "normalized_headers": {header: normalize_column_name(header) for header in headers},
    }


def build_download_asset_row(
    *,
    run_id: str,
    endpoint_id: int,
    endpoint_key: str,
    entry: MicrodadosCatalogEntry,
    source_file_name: str,
    content_type: str | None,
    size_bytes: int,
    sha256: str,
    row_count: int,
    headers: tuple[str, ...],
) -> dict[str, Any]:
    return _build_asset_row(
        run_id=run_id,
        endpoint_id=endpoint_id,
        endpoint_key=endpoint_key,
        asset_type="powerbi_microdados_download",
        source_url=entry.microdados_url,
        content_text=json.dumps(
            {
                "ano_base": entry.ano_base,
                "tipo_microdados": entry.tipo_microdados,
                "microdados_url": entry.microdados_url,
                "source_file_name": source_file_name,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "row_count": row_count,
                "headers": list(headers),
            },
            ensure_ascii=True,
            sort_keys=True,
        ),
    )


def build_manifest_asset_row(
    *,
    run_id: str,
    endpoint_id: int,
    endpoint_key: str,
    selection: CatalogSelectionResult,
    downloads: list[dict[str, Any]],
    raw_record_count: int,
) -> dict[str, Any]:
    manifest = {
        "status": "ok",
        "selected_years": list(selection.selected_years),
        "selected_microdados_types": list(selection.selected_microdados_types),
        "selection_source": selection.selection_source,
        "catalog_entry_count": len(selection.catalog_entries),
        "selected_entry_count": len(selection.selected_entries),
        "raw_record_count": raw_record_count,
        "context": {
            "page_url": selection.context.page_url,
            "resource_key": selection.context.resource_key,
            "tenant_id": selection.context.tenant_id,
            "resolved_cluster_uri": selection.context.resolved_cluster_uri,
            "api_base_url": selection.context.api_base_url,
            "model_id": selection.context.model_id,
            "dataset_id": selection.context.dataset_id,
            "report_id": selection.context.report_id,
            "report_numeric_id": selection.context.report_numeric_id,
            "section_name": selection.context.section_name,
            "section_display_name": selection.context.section_display_name,
            "visual_id": selection.context.visual_id,
            "visual_type": selection.context.visual_type,
        },
        "entries": [
            {
                "ano_base": entry.ano_base,
                "tipo_microdados": entry.tipo_microdados,
                "microdados_url": entry.microdados_url,
                "is_selected": entry in selection.selected_entries,
            }
            for entry in selection.catalog_entries
        ],
        "downloads": downloads,
    }
    return _build_asset_row(
        run_id=run_id,
        endpoint_id=endpoint_id,
        endpoint_key=endpoint_key,
        asset_type="powerbi_microdados_manifest",
        source_url=selection.context.page_url,
        content_text=json.dumps(manifest, ensure_ascii=True, sort_keys=True),
    )


def build_quarantine_row(
    *,
    run_id: str,
    instance_key: str | None,
    entry: MicrodadosCatalogEntry,
    invalid_row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "instance_key": instance_key,
        "source_url": entry.microdados_url,
        "source_row_number": invalid_row.get("source_row_number"),
        "error_type": str(invalid_row.get("error_type") or "csv_parse_error"),
        "error_message": str(invalid_row.get("error_message") or "CSV parsing produced an invalid row"),
        "raw_line_text": str(invalid_row.get("raw_line_text") or ""),
        "details_json": {"tipo_microdados": entry.tipo_microdados},
    }


def build_record_payload(
    *,
    row: dict[str, Any],
    row_number: int,
    entry: MicrodadosCatalogEntry,
    selection: CatalogSelectionResult,
    source_file_name: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    enriched = {str(key): value for key, value in row.items() if isinstance(key, str)}
    dataset_name = f"pnp_microdados_{_slugify(entry.tipo_microdados)}"
    enriched.update(
        {
            "id": str(
                enriched.get("Código da Matricula")
                or enriched.get("Código da Matrícula")
                or enriched.get("Código do Ciclo Matricula")
                or enriched.get("Matrícula")
                or f"{entry.ano_base}|{entry.tipo_microdados}|{source_file_name}|{row_number}"
            ),
            "dataset": dataset_name,
            "entidade": entry.tipo_microdados,
            "ano": entry.ano_base,
            "tipo": entry.tipo_microdados,
            "indicador": entry.tipo_microdados,
            "tipo_microdados": entry.tipo_microdados,
            "microdados_url": entry.microdados_url,
            "source_file_name": source_file_name,
            "source_file_sha256": source_file_sha256,
            "source_method": "powerbi_microdados",
            "source_row_number": row_number,
            "instance_key": selection.instance_key,
        }
    )
    return enriched


def _build_asset_row(
    *,
    run_id: str,
    endpoint_id: int,
    endpoint_key: str,
    asset_type: str,
    source_url: str,
    content_text: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "endpoint_id": endpoint_id,
        "endpoint_key": endpoint_key,
        "asset_type": asset_type,
        "source_url": source_url,
        "content_text": content_text,
        "content_hash": hashlib.sha256(content_text.encode("utf-8")).hexdigest(),
    }


def _build_binary_factory(content_bytes: bytes, source_url: str):
    def _factory():
        raw = io.BytesIO(content_bytes)
        if source_url.endswith(".gz"):
            return gzip.GzipFile(fileobj=raw)
        return raw

    return _factory


def _detect_content_encoding(binary_factory) -> str:
    stream = binary_factory()
    try:
        sample = stream.read(65536)
    finally:
        stream.close()

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _detect_bytes_encoding(sample: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _iter_text_lines(first_line: str, text_stream: io.TextIOWrapper) -> Iterator[str]:
    if first_line:
        yield first_line
    yield from text_stream


def _slugify(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    collapsed = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return collapsed or "arquivo"
