from __future__ import annotations

import argparse
import base64
import contextlib
import gzip
import hashlib
import io
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, unquote, urlparse

import requests

DEFAULT_POWERBI_MICRODADOS_URL = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiZDhkNGNiYzgtMjQ0My00OGVlLWJjNzYtZWQwYjI2OThhYWM1IiwidCI6IjllNjgyMzU5LWQxMjgtNGVkYi1iYjU4LTgyYjJhMTUzNDBmZiJ9"
)
MICRODADOS_SECTION_DISPLAY_NAME = "Microdados da PNP"
MICRODADOS_ROWS_QUERY_REF = "Microdados.Ano Base"
MICRODADOS_COLUMNS_QUERY_REF = "Microdados.Tipo de microdados"
MICRODADOS_VALUES_QUERY_REF = "Microdados.MicrodadosURL"
MICRODADOS_ENTITY_NAME = "Microdados"
MICRODADOS_ANO_PROPERTY = "Ano Base"
MICRODADOS_TIPO_PROPERTY = "Tipo de microdados"
MICRODADOS_URL_PROPERTY = "MicrodadosURL"


@dataclass(frozen=True)
class PowerBIMicrodadosContext:
    page_url: str
    resource_key: str
    tenant_id: str
    resolved_cluster_uri: str
    api_base_url: str
    model_id: int
    dataset_id: str
    report_id: str
    report_numeric_id: int
    section_name: str
    section_display_name: str
    visual_id: str
    visual_type: str
    prototype_query: dict[str, Any]


@dataclass(frozen=True)
class MicrodadosCatalogEntry:
    ano_base: str
    tipo_microdados: str
    microdados_url: str


@dataclass(frozen=True)
class MicrodadosDownloadResult:
    ano_base: str
    tipo_microdados: str
    source_url: str
    output_path: str
    size_bytes: int
    sha256: str
    content_type: str | None
    preview_lines: tuple[str, ...]


@dataclass(frozen=True)
class MicrodadosContentResult:
    source_url: str
    content_bytes: bytes
    size_bytes: int
    sha256: str
    content_type: str | None


@dataclass(frozen=True)
class MicrodadosContentStream:
    source_url: str
    raw_stream: Any
    content_type: str | None
    size_bytes: int
    sha256: str | None


class _IterContentStream(io.RawIOBase):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = bytearray()
        self._closed = False

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        if self._closed:
            return 0

        requested = len(buffer)
        while len(self._buffer) < requested:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                break
            if chunk:
                self._buffer.extend(chunk)

        if not self._buffer:
            return 0

        count = min(requested, len(self._buffer))
        buffer[:count] = self._buffer[:count]
        del self._buffer[:count]
        return count

    def close(self) -> None:
        self._closed = True
        super().close()


class PowerBIMicrodadosClient:
    def __init__(
        self,
        page_url: str = DEFAULT_POWERBI_MICRODADOS_URL,
        timeout_seconds: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        self.page_url = page_url
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def discover_context(self) -> PowerBIMicrodadosContext:
        response = self.session.get(self.page_url, timeout=self.timeout_seconds)
        response.raise_for_status()
        html = response.text

        resource_descriptor = self._extract_resource_descriptor(html) or self._decode_resource_descriptor_from_url(self.page_url)
        resource_key = str(resource_descriptor.get("k") or "").strip()
        tenant_id = str(resource_descriptor.get("t") or "").strip()
        if not resource_key:
            raise RuntimeError("Power BI page did not expose a resource key")
        if not tenant_id:
            raise RuntimeError("Power BI page did not expose a tenant id")

        resolved_cluster_uri = self._extract_resolved_cluster_uri(html)
        if not resolved_cluster_uri:
            resolved_cluster_uri = self._resolve_cluster_uri(resource_key=resource_key, tenant_id=tenant_id)
        api_base_url = self._build_apim_url(resolved_cluster_uri)

        metadata_response = self.session.get(
            f"{api_base_url}/public/reports/{resource_key}/modelsAndExploration?preferReadOnlySession=true",
            headers=self._powerbi_headers(resource_key),
            timeout=self.timeout_seconds,
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()

        report = dict((metadata.get("exploration") or {}).get("report") or {})
        model = dict(report.get("model") or {})
        model_fallback = dict((metadata.get("models") or [{}])[0] or {})
        section, visual = self._find_microdados_visual(metadata)

        model_id = int(report.get("modelId") or model_fallback.get("id") or 0)
        dataset_id = str(model.get("dbName") or model_fallback.get("dbName") or "").strip()
        report_id = str(report.get("objectId") or "").strip()
        report_numeric_id = int(report.get("id") or 0)
        if not model_id or not dataset_id or not report_id:
            raise RuntimeError("Power BI metadata did not expose model/report identifiers for microdados")

        return PowerBIMicrodadosContext(
            page_url=self.page_url,
            resource_key=resource_key,
            tenant_id=tenant_id,
            resolved_cluster_uri=resolved_cluster_uri,
            api_base_url=api_base_url,
            model_id=model_id,
            dataset_id=dataset_id,
            report_id=report_id,
            report_numeric_id=report_numeric_id,
            section_name=str(section.get("name") or ""),
            section_display_name=str(section.get("displayName") or ""),
            visual_id=str(visual.get("name") or ""),
            visual_type=str((visual.get("singleVisual") or {}).get("visualType") or ""),
            prototype_query=dict((visual.get("singleVisual") or {}).get("prototypeQuery") or {}),
        )

    def fetch_catalog(self) -> tuple[PowerBIMicrodadosContext, list[MicrodadosCatalogEntry]]:
        context = self.discover_context()
        response = self.session.post(
            f"{context.api_base_url}/public/reports/querydata?synchronous=true",
            headers=self._powerbi_headers(context.resource_key, json_request=True),
            json=self._build_querydata_body(context),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        entries = self._decode_microdados_catalog(response.json())
        return context, entries

    def download_entry(
        self,
        entry: MicrodadosCatalogEntry,
        output_dir: str | Path,
        preview_line_count: int = 0,
    ) -> MicrodadosDownloadResult:
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = Path(urlparse(entry.microdados_url).path).name or (
            f"{entry.ano_base}_{self._slugify(entry.tipo_microdados)}.bin"
        )
        output_path = target_dir / filename
        content = self.fetch_entry_content(entry)
        with output_path.open("wb") as handle:
            handle.write(content.content_bytes)

        preview_lines = self._read_preview_lines(output_path, preview_line_count)
        return MicrodadosDownloadResult(
            ano_base=entry.ano_base,
            tipo_microdados=entry.tipo_microdados,
            source_url=entry.microdados_url,
            output_path=str(output_path),
            size_bytes=content.size_bytes,
            sha256=content.sha256,
            content_type=content.content_type,
            preview_lines=preview_lines,
        )

    def fetch_entry_content(self, entry: MicrodadosCatalogEntry) -> MicrodadosContentResult:
        hasher = hashlib.sha256()
        chunks: list[bytes] = []
        size_bytes = 0

        with self.session.get(entry.microdados_url, stream=True, timeout=self.timeout_seconds) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                hasher.update(chunk)
                size_bytes += len(chunk)

        return MicrodadosContentResult(
            source_url=entry.microdados_url,
            content_bytes=b"".join(chunks),
            size_bytes=size_bytes,
            sha256=hasher.hexdigest(),
            content_type=content_type,
        )

    @contextlib.contextmanager
    def open_entry_content_stream(self, entry: MicrodadosCatalogEntry) -> Iterator[MicrodadosContentStream]:
        with self.session.get(entry.microdados_url, stream=True, timeout=self.timeout_seconds) as response:
            response.raise_for_status()
            size_header = response.headers.get("content-length")
            try:
                size_bytes = int(size_header or 0)
            except (TypeError, ValueError):
                size_bytes = 0
            yield MicrodadosContentStream(
                source_url=entry.microdados_url,
                raw_stream=_IterContentStream(response.iter_content(65536)),
                content_type=response.headers.get("content-type"),
                size_bytes=size_bytes,
                sha256=None,
            )

    def _resolve_cluster_uri(self, resource_key: str, tenant_id: str) -> str:
        response = self.session.get(
            f"https://api.powerbi.com/public/routing/cluster/{tenant_id}",
            headers=self._powerbi_headers(resource_key),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        fixed_cluster_uri = str((response.json() or {}).get("FixedClusterUri") or "").strip()
        if not fixed_cluster_uri:
            raise RuntimeError("Power BI cluster routing did not return FixedClusterUri")
        return fixed_cluster_uri

    @staticmethod
    def _powerbi_headers(resource_key: str, json_request: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "ActivityId": str(uuid.uuid4()),
            "RequestId": str(uuid.uuid4()),
            "X-PowerBI-ResourceKey": resource_key,
        }
        if json_request:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _extract_resource_descriptor(html: str) -> dict[str, str]:
        marker = "resourceDescriptor = JSON.parse('"
        start = html.find(marker)
        if start < 0:
            return {}
        start += len(marker)
        end = html.find("');", start)
        if end < 0:
            return {}
        payload = html[start:end]
        decoded = bytes(payload, "utf-8").decode("unicode_escape")
        try:
            descriptor = json.loads(decoded)
        except json.JSONDecodeError:
            return {}
        return {
            "k": str(descriptor.get("k") or "").strip(),
            "t": str(descriptor.get("t") or "").strip(),
        }

    @staticmethod
    def _decode_resource_descriptor_from_url(page_url: str) -> dict[str, str]:
        parsed = urlparse(page_url)
        encoded = parse_qs(parsed.query).get("r", [])
        if not encoded:
            return {}
        token = unquote(encoded[0])
        padding = "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(token + padding).decode("utf-8")
        payload = json.loads(decoded)
        return {
            "k": str(payload.get("k") or "").strip(),
            "t": str(payload.get("t") or "").strip(),
        }

    @staticmethod
    def _extract_resolved_cluster_uri(html: str) -> str:
        marker = "var resolvedClusterUri = '"
        start = html.find(marker)
        if start < 0:
            return ""
        start += len(marker)
        end = html.find("';", start)
        if end < 0:
            return ""
        return html[start:end].strip()

    @staticmethod
    def _build_apim_url(cluster_uri: str) -> str:
        parsed = urlparse(cluster_uri)
        hostname = parsed.hostname or ""
        if not hostname:
            raise RuntimeError("Invalid Power BI cluster uri")
        host_tokens = hostname.split(".")
        host_tokens[0] = host_tokens[0].replace("-redirect", "")
        host_tokens[0] = host_tokens[0].replace("global-", "")
        host_tokens[0] = f"{host_tokens[0]}-api"
        scheme = parsed.scheme or "https"
        return f"{scheme}://{'.'.join(host_tokens)}"

    @classmethod
    def _find_microdados_visual(cls, metadata: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        sections = list(((metadata.get("exploration") or {}).get("sections") or []))

        preferred_section = cls._find_microdados_section(sections)
        if preferred_section is not None:
            visual = cls._select_microdados_visual(preferred_section)
            if visual:
                return preferred_section, visual

            fallback_visual = cls._build_fallback_visual(preferred_section)
            if fallback_visual is not None:
                return preferred_section, fallback_visual

        for section in sections:
            visual = cls._select_microdados_visual(section)
            if visual:
                return section, visual

        if preferred_section is None:
            section_names = ", ".join(
                sorted(
                    {
                        str(section.get("displayName") or "").strip()
                        for section in sections
                        if str(section.get("displayName") or "").strip()
                    }
                )
            )
            raise RuntimeError(
                "Power BI metadata did not expose the Microdados da PNP section"
                + (f"; available sections: {section_names}" if section_names else "")
            )

        raise RuntimeError("Power BI metadata exposed the Microdados da PNP section, but no compatible visual or fallback query context was found")

    @staticmethod
    def _find_microdados_section(sections: list[dict[str, Any]]) -> dict[str, Any] | None:
        for section in sections:
            if str(section.get("displayName") or "").strip() == MICRODADOS_SECTION_DISPLAY_NAME:
                return section
        return None

    @classmethod
    def _select_microdados_visual(cls, section: dict[str, Any]) -> dict[str, Any] | None:
        for container in section.get("visualContainers") or []:
            raw_config = container.get("config")
            if not isinstance(raw_config, str) or not raw_config.strip():
                continue
            try:
                visual = json.loads(raw_config)
            except json.JSONDecodeError:
                continue

            single_visual = dict(visual.get("singleVisual") or {})
            if not single_visual:
                continue

            projections = dict(single_visual.get("projections") or {})
            if cls._visual_matches_microdados_catalog(single_visual, projections):
                return visual
        return None

    @classmethod
    def _visual_matches_microdados_catalog(cls, single_visual: dict[str, Any], projections: dict[str, Any]) -> bool:
        row_refs = [item.get("queryRef") for item in projections.get("Rows") or [] if item.get("active", True)]
        column_refs = [item.get("queryRef") for item in projections.get("Columns") or [] if item.get("active", True)]
        value_refs = [item.get("queryRef") for item in projections.get("Values") or [] if item.get("active", True) or "active" not in item]

        exact_projection_match = (
            row_refs == [MICRODADOS_ROWS_QUERY_REF]
            and column_refs == [MICRODADOS_COLUMNS_QUERY_REF]
            and value_refs == [MICRODADOS_VALUES_QUERY_REF]
        )
        if exact_projection_match:
            return True

        prototype_query = dict(single_visual.get("prototypeQuery") or {})
        select_names = {
            str(item.get("Name") or "").strip()
            for item in prototype_query.get("Select") or []
            if isinstance(item, dict)
        }
        if {
            MICRODADOS_ROWS_QUERY_REF,
            MICRODADOS_COLUMNS_QUERY_REF,
            MICRODADOS_VALUES_QUERY_REF,
        }.issubset(select_names):
            return True

        return False

    @classmethod
    def _build_fallback_visual(cls, section: dict[str, Any]) -> dict[str, Any] | None:
        visual_containers = list(section.get("visualContainers") or [])
        if not visual_containers:
            return None

        fallback_name = str(visual_containers[0].get("objectName") or visual_containers[0].get("id") or "microdados_catalog")
        return {
            "name": fallback_name,
            "singleVisual": {
                "visualType": "microdados_catalog_fallback",
                "prototypeQuery": cls._build_fallback_prototype_query(),
            },
        }

    @staticmethod
    def _build_fallback_prototype_query() -> dict[str, Any]:
        return {
            "Version": 2,
            "From": [{"Name": "m", "Entity": MICRODADOS_ENTITY_NAME, "Type": 0}],
            "Select": [
                {
                    "Measure": {
                        "Expression": {"SourceRef": {"Source": "m"}},
                        "Property": MICRODADOS_URL_PROPERTY,
                    },
                    "Name": MICRODADOS_VALUES_QUERY_REF,
                },
                {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": "m"}},
                        "Property": MICRODADOS_ANO_PROPERTY,
                    },
                    "Name": MICRODADOS_ROWS_QUERY_REF,
                },
                {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": "m"}},
                        "Property": MICRODADOS_TIPO_PROPERTY,
                    },
                    "Name": MICRODADOS_COLUMNS_QUERY_REF,
                },
            ],
        }

    @staticmethod
    def _build_querydata_body(context: PowerBIMicrodadosContext) -> dict[str, Any]:
        return {
            "version": "1.0.0",
            "queries": [
                {
                    "Query": {
                        "Commands": [
                            {
                                "SemanticQueryDataShapeCommand": {
                                    "Query": context.prototype_query,
                                    "Binding": {
                                        "Primary": {"Groupings": [{"Projections": [0, 1, 2]}]},
                                        "DataReduction": {"DataVolume": 3, "Primary": {"Top": {"Count": 500}}},
                                        "Version": 1,
                                    },
                                    "ExecutionMetricsKind": 1,
                                }
                            }
                        ]
                    },
                    "ApplicationContext": {
                        "DatasetId": context.dataset_id,
                        "Sources": [{"ReportId": context.report_id, "VisualId": context.visual_id}],
                    },
                }
            ],
            "modelId": context.model_id,
        }

    @classmethod
    def _decode_microdados_catalog(cls, payload: dict[str, Any]) -> list[MicrodadosCatalogEntry]:
        seen: set[tuple[str, str, str]] = set()
        entries: list[MicrodadosCatalogEntry] = []

        results = payload.get("results") or []
        for result in results:
            data = dict((result.get("result") or {}).get("data") or {})
            dsr = dict(data.get("dsr") or {})
            for dataset in dsr.get("DS") or []:
                for row_values in cls._decode_dsr_rows(dict(dataset or {})):
                    if len(row_values) < 3:
                        continue
                    ano_base = str(row_values[0] or "").strip()
                    tipo_microdados = str(row_values[1] or "").strip()
                    microdados_url = str(row_values[2] or "").strip()
                    if not ano_base or not tipo_microdados or not microdados_url:
                        continue
                    key = (ano_base, tipo_microdados, microdados_url)
                    if key in seen:
                        continue
                    seen.add(key)
                    entries.append(
                        MicrodadosCatalogEntry(
                            ano_base=ano_base,
                            tipo_microdados=tipo_microdados,
                            microdados_url=microdados_url,
                        )
                    )

        if not entries:
            raise RuntimeError("Power BI querydata did not expose any microdados download entries")
        return entries

    @classmethod
    def _decode_dsr_rows(cls, dataset: dict[str, Any]) -> list[list[Any]]:
        value_dicts = dict(dataset.get("ValueDicts") or {})
        decoded_rows: list[list[Any]] = []

        for placeholder in dataset.get("PH") or []:
            if not isinstance(placeholder, dict):
                continue
            for member_name, rows in placeholder.items():
                if not isinstance(member_name, str) or not member_name.startswith("DM"):
                    continue
                if not isinstance(rows, list):
                    continue

                schema: list[dict[str, Any]] = []
                previous_values: list[Any] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if isinstance(row.get("S"), list):
                        schema = [dict(item or {}) for item in row["S"]]
                        previous_values = [None] * len(schema)
                    if not schema:
                        continue

                    inflated = cls._inflate_dsr_row(row=row, schema=schema, previous_values=previous_values)
                    if inflated is None:
                        continue

                    previous_values = list(inflated)
                    decoded_rows.append(
                        [
                            cls._resolve_dsr_value(schema_item, raw_value, value_dicts)
                            for schema_item, raw_value in zip(schema, inflated)
                        ]
                    )

        return decoded_rows

    @staticmethod
    def _inflate_dsr_row(
        row: dict[str, Any],
        schema: list[dict[str, Any]],
        previous_values: list[Any],
    ) -> list[Any] | None:
        compressed = row.get("C")
        if isinstance(compressed, list):
            values = list(previous_values) if previous_values else [None] * len(schema)
            start_index = len(schema) - len(compressed)
            repeated_prefix = row.get("R")
            if isinstance(repeated_prefix, int):
                start_index = repeated_prefix
            start_index = max(0, min(start_index, len(schema)))
            for offset, value in enumerate(compressed):
                index = start_index + offset
                if index >= len(schema):
                    break
                values[index] = value
            return values

        named_values = [row.get(str(column.get("N") or "")) for column in schema]
        if any(value is not None for value in named_values):
            return named_values
        return None

    @staticmethod
    def _resolve_dsr_value(schema_item: dict[str, Any], raw_value: Any, value_dicts: dict[str, Any]) -> Any:
        dictionary_name = schema_item.get("DN")
        if isinstance(raw_value, int) and isinstance(dictionary_name, str):
            dictionary = value_dicts.get(dictionary_name)
            if isinstance(dictionary, list) and 0 <= raw_value < len(dictionary):
                raw_value = dictionary[raw_value]

        if isinstance(raw_value, str):
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
        return raw_value

    @staticmethod
    def _slugify(value: str) -> str:
        safe = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
        collapsed = "_".join(part for part in safe.split("_") if part)
        return collapsed or "arquivo"

    @staticmethod
    def _read_preview_lines(path: Path, line_count: int) -> tuple[str, ...]:
        if line_count <= 0:
            return ()

        opener = gzip.open if path.suffix == ".gz" else open
        lines: list[str] = []
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for _ in range(line_count):
                line = handle.readline()
                if not line:
                    break
                lines.append(line.rstrip("\n"))
        return tuple(lines)

    @staticmethod
    def decode_content_bytes(content_bytes: bytes, source_url: str) -> str:
        raw_bytes = gzip.decompress(content_bytes) if source_url.lower().endswith(".gz") else content_bytes
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="replace")


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consulta o catálogo de microdados públicos da PNP via Power BI.")
    parser.add_argument("--page-url", default=DEFAULT_POWERBI_MICRODADOS_URL, help="URL pública do relatório Power BI.")
    parser.add_argument("--timeout-seconds", type=int, default=60, help="Timeout HTTP em segundos.")
    parser.add_argument("--output-json", help="Caminho para salvar o catálogo completo em JSON.")
    parser.add_argument("--download-dir", help="Diretório para baixar arquivos de microdados.")
    parser.add_argument(
        "--download-limit",
        type=int,
        default=0,
        help="Quantidade de arquivos a baixar. Use 0 para apenas listar o catálogo.",
    )
    parser.add_argument(
        "--preview-lines",
        type=int,
        default=0,
        help="Quantidade de linhas de prévia para imprimir por arquivo baixado.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    client = PowerBIMicrodadosClient(page_url=args.page_url, timeout_seconds=args.timeout_seconds)
    context, entries = client.fetch_catalog()

    manifest = {
        "context": asdict(context),
        "entries": [asdict(entry) for entry in entries],
    }

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "entry_count": len(entries),
                "first_entry": asdict(entries[0]) if entries else None,
                "resource_key": context.resource_key,
                "visual_id": context.visual_id,
            },
            ensure_ascii=False,
        )
    )

    if args.download_dir and args.download_limit > 0:
        download_results = [
            asdict(client.download_entry(entry, args.download_dir, preview_line_count=args.preview_lines))
            for entry in entries[: args.download_limit]
        ]
        print(json.dumps({"downloads": download_results}, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
