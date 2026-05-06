from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor, execute_values


def register_run_start(
    dsn: str,
    *,
    run_id: str,
    instance_key: str | None,
    airflow_dag_id: str | None = None,
    airflow_dag_run_id: str | None = None,
    status: str,
    trigger_mode: str,
    requested_by: str,
    logical_date: datetime | None,
    started_at: datetime,
) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.pnp_runs (
              run_id,
              instance_key,
              airflow_dag_id,
              airflow_dag_run_id,
              logical_date,
              trigger_mode,
              requested_by,
              status,
              started_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE
            SET
              instance_key = EXCLUDED.instance_key,
              airflow_dag_id = EXCLUDED.airflow_dag_id,
              airflow_dag_run_id = EXCLUDED.airflow_dag_run_id,
              logical_date = EXCLUDED.logical_date,
              trigger_mode = EXCLUDED.trigger_mode,
              requested_by = EXCLUDED.requested_by,
              status = EXCLUDED.status,
              started_at = EXCLUDED.started_at
            """,
            (
                run_id,
                instance_key,
                airflow_dag_id,
                airflow_dag_run_id,
                logical_date,
                trigger_mode,
                requested_by,
                status,
                started_at,
            ),
        )


def register_run_step_start(
    dsn: str,
    *,
    run_id: str,
    instance_key: str | None,
    airflow_task_id: str,
    map_index: int | None,
    status: str,
    details: dict[str, Any],
    started_at: datetime,
) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.pnp_run_steps (
              run_id,
              instance_key,
              airflow_task_id,
              map_index,
              status,
              started_at,
              details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, airflow_task_id, map_index_key) DO UPDATE
            SET
              instance_key = EXCLUDED.instance_key,
              status = EXCLUDED.status,
              started_at = EXCLUDED.started_at,
              finished_at = NULL,
              records_affected = NULL,
              error_message = NULL,
              details_json = EXCLUDED.details_json
            """,
            (
                run_id,
                instance_key,
                airflow_task_id,
                map_index,
                status,
                started_at,
                Json(details),
            ),
        )


def finish_run_step(
    dsn: str,
    *,
    run_id: str,
    airflow_task_id: str,
    map_index: int | None,
    status: str,
    finished_at: datetime,
    records_affected: int | None,
    error_message: str | None,
    details: dict[str, Any],
) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw.pnp_run_steps
            SET
              status = %s,
              finished_at = %s,
              records_affected = %s,
              error_message = %s,
              details_json = details_json || %s
            WHERE run_id = %s
              AND airflow_task_id = %s
              AND map_index_key = COALESCE(%s, -1)
            """,
            (
                status,
                finished_at,
                records_affected,
                error_message,
                Json(details),
                run_id,
                airflow_task_id,
                map_index,
            ),
        )


def append_run_package(
    dsn: str,
    *,
    run_id: str,
    instance_key: str | None,
    airflow_dag_id: str | None,
    airflow_dag_run_id: str | None,
    airflow_task_id: str,
    package_type: str,
    package_name: str,
    package_status: str,
    records_affected: int | None,
    payload: dict[str, Any],
) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.pnp_run_packages (
              run_id,
              instance_key,
              airflow_dag_id,
              airflow_dag_run_id,
              airflow_task_id,
              package_type,
              package_name,
              package_status,
              records_affected,
              payload_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                instance_key,
                airflow_dag_id,
                airflow_dag_run_id,
                airflow_task_id,
                package_type,
                package_name,
                package_status,
                records_affected,
                Json(payload),
            ),
        )


def finish_run(
    dsn: str,
    *,
    run_id: str,
    status: str,
    catalog_entry_count: int,
    selected_download_count: int,
    downloaded_file_count: int,
    raw_record_count: int,
    error_message: str | None,
    run_summary: dict[str, Any],
    finished_at: datetime,
) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw.pnp_runs
            SET
              status = %s,
              catalog_entry_count = %s,
              selected_download_count = %s,
              downloaded_file_count = %s,
              raw_record_count = %s,
              error_message = %s,
              run_summary_json = %s,
              finished_at = %s
            WHERE run_id = %s
            """,
            (
                status,
                catalog_entry_count,
                selected_download_count,
                downloaded_file_count,
                raw_record_count,
                error_message,
                Json(run_summary),
                finished_at,
                run_id,
            ),
        )


def mark_run_downloads_failed(
    dsn: str,
    *,
    run_id: str,
    error_message: str,
) -> int:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE raw.pnp_downloads
            SET
              status = 'failed',
              error_message = %s,
              finished_at = NOW()
            WHERE run_id = %s
              AND status = 'running'
            """,
            (error_message, run_id),
        )
        return cur.rowcount if cur.rowcount > 0 else 0


def load_instance_runtime_config(dsn: str, *, instance_key: str) -> dict[str, Any]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              pipeline_id,
              instance_key,
              instance_name,
              connection_key,
              connection_name,
              page_url,
              schedule,
              is_active,
              metadata
            FROM raw.pnp_instances
            WHERE instance_key = %s
              AND deleted_at IS NULL
            """,
            (instance_key,),
        )
        instance_row = cur.fetchone()
        if not instance_row:
            raise LookupError(instance_key)

        cur.execute(
            """
            SELECT
              ano_base,
              tipo_microdados,
              configured_microdados_url,
              selection_rank,
              metadata
            FROM raw.pnp_instance_selection
            WHERE instance_key = %s
              AND is_active = TRUE
            ORDER BY COALESCE(selection_rank, 2147483647), ano_base DESC, tipo_microdados
            """,
            (instance_key,),
        )
        selection_rows = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT
              pe.endpoint_key,
              pe.selection_source,
              pe.metadata AS pipeline_endpoint_metadata,
              et.endpoint_name,
              et.tipo_microdados,
              et.raw_table_schema,
              et.raw_table_name,
              et.staging_table_schema,
              et.staging_table_name,
              et.curated_relation_schema,
              et.curated_relation_name,
              et.metadata AS endpoint_metadata
            FROM raw.pnp_pipeline_endpoints pe
            JOIN raw.pnp_endpoint_tables et
              ON et.endpoint_key = pe.endpoint_key
            WHERE pe.instance_key = %s
              AND pe.is_active = TRUE
              AND et.is_active = TRUE
            ORDER BY et.endpoint_name, pe.endpoint_key
            """,
            (instance_key,),
        )
        endpoint_rows = [dict(row) for row in cur.fetchall()]

    selected_downloads = [
        {
            "ano_base": str(row["ano_base"]),
            "tipo_microdados": str(row["tipo_microdados"]),
            "microdados_url": str(row["configured_microdados_url"]),
        }
        for row in selection_rows
        if row.get("configured_microdados_url")
    ]
    selected_years = list(dict.fromkeys(str(row["ano_base"]) for row in selection_rows))
    selected_microdados_types = list(dict.fromkeys(str(row["tipo_microdados"]) for row in selection_rows))
    selected_endpoints = [str(row["endpoint_key"]) for row in endpoint_rows]
    endpoint_tables = [
        {
            "endpoint_key": str(row["endpoint_key"]),
            "endpoint_name": str(row["endpoint_name"]),
            "tipo_microdados": str(row["tipo_microdados"]),
            "selection_source": row.get("selection_source"),
            "raw_table": f"{row['raw_table_schema']}.{row['raw_table_name']}",
            "staging_table": (
                f"{row['staging_table_schema']}.{row['staging_table_name']}"
                if row.get("staging_table_name")
                else None
            ),
            "curated_relation": (
                f"{row['curated_relation_schema']}.{row['curated_relation_name']}"
                if row.get("curated_relation_name")
                else None
            ),
            "metadata": {
                **dict(row.get("endpoint_metadata") or {}),
                **dict(row.get("pipeline_endpoint_metadata") or {}),
            },
        }
        for row in endpoint_rows
    ]
    return {
        "pipeline_id": str(instance_row["pipeline_id"]),
        "instance_key": str(instance_row["instance_key"]),
        "instance_name": str(instance_row["instance_name"]),
        "connection_key": instance_row.get("connection_key"),
        "connection_name": instance_row.get("connection_name"),
        "page_url": str(instance_row["page_url"]),
        "schedule": instance_row.get("schedule"),
        "is_active": bool(instance_row.get("is_active")),
        "metadata": dict(instance_row.get("metadata") or {}),
        "selected_years": selected_years,
        "selected_microdados_types": selected_microdados_types,
        "selected_endpoints": selected_endpoints,
        "endpoint_tables": endpoint_tables,
        "selected_downloads": selected_downloads,
        "selection_rows": selection_rows,
        "request_params": {
            "mode": "powerbi_microdados",
            "pipeline_id": str(instance_row["pipeline_id"]),
            "instance_key": str(instance_row["instance_key"]),
            "instance_name": str(instance_row["instance_name"]),
            "selected_years": selected_years,
            "selected_microdados_types": selected_microdados_types,
            "selected_endpoints": selected_endpoints,
            "endpoint_tables": endpoint_tables,
            "selected_downloads": selected_downloads,
        },
    }


def list_active_instance_schedules(dsn: str) -> list[dict[str, Any]]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              i.instance_key,
              i.schedule,
              i.updated_at,
              (
                SELECT MAX(r.started_at)
                FROM raw.pnp_runs r
                WHERE r.instance_key = i.instance_key
              ) AS last_started_at,
              EXISTS (
                SELECT 1
                FROM raw.pnp_runs r
                WHERE r.instance_key = i.instance_key
                  AND r.status = 'running'
              ) AS has_running_run
            FROM raw.pnp_instances i
            WHERE i.is_active = TRUE
              AND i.deleted_at IS NULL
            ORDER BY i.instance_key
            """,
        )
        return [dict(row) for row in cur.fetchall()]


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
    asset_count = len(pending_assets)
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        _insert_catalog_entries(cur, pending_catalog_entries)
        run_selection_map = _upsert_run_selection(cur, pending_run_selection)
        download_id_by_url = _upsert_downloads(cur, pending_downloads, run_selection_map)
        download_column_count = _upsert_download_columns(cur, pending_downloads, download_id_by_url)
        domain_counts = _insert_domain_records(cur, normalized_records, download_id_by_url)
        quarantine_count = _insert_quarantine(cur, pending_quarantine, download_id_by_url)

        if write_legacy:
            raise RuntimeError("legacy PNP compatibility support has been removed")

    return {
        "catalog_entry_count": len(pending_catalog_entries),
        "selected_download_count": len(pending_run_selection),
        "downloaded_file_count": len(pending_downloads),
        "download_column_count": download_column_count,
        "asset_count": asset_count,
        "raw_record_count": sum(domain_counts.values()),
        "quarantine_count": quarantine_count,
        **{f"{domain_key}_count": count for domain_key, count in domain_counts.items()},
    }


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
    asset_count = len(pending_assets)
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        _insert_catalog_entries(cur, pending_catalog_entries)
        run_selection_map = _upsert_run_selection(cur, pending_run_selection)
        download_id_by_url = _upsert_downloads(cur, pending_downloads, run_selection_map)
        download_column_count = 0
        if include_download_columns:
            download_column_count = _upsert_download_columns(cur, pending_downloads, download_id_by_url)

        if write_legacy:
            raise RuntimeError("legacy PNP compatibility support has been removed")

    return {
        "catalog_entry_count": len(pending_catalog_entries),
        "selected_download_count": len(pending_run_selection),
        "downloaded_file_count": len(pending_downloads),
        "download_column_count": download_column_count,
        "asset_count": asset_count,
        "download_id_by_url": download_id_by_url,
    }


def load_raw_record_chunk(
    dsn: str,
    *,
    normalized_records: list[dict[str, Any]],
    pending_quarantine: list[dict[str, Any]],
    download_id_by_url: dict[str, int],
    pending_assets: list[dict[str, Any]] | None = None,
    write_legacy: bool = False,
) -> dict[str, int]:
    assets = pending_assets or []
    asset_count = len(assets)

    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        domain_counts = _insert_domain_records(cur, normalized_records, download_id_by_url)
        quarantine_count = _insert_quarantine(cur, pending_quarantine, download_id_by_url)

        if write_legacy:
            raise RuntimeError("legacy PNP compatibility support has been removed")

    return {
        "raw_record_count": sum(domain_counts.values()),
        "quarantine_count": quarantine_count,
        "asset_count": asset_count,
        **{f"{domain_key}_count": count for domain_key, count in domain_counts.items()},
    }


def collect_run_checks(dsn: str, run_id: str) -> dict[str, Any]:
    query_map = {
        "catalog_entry_count": "SELECT COUNT(*) FROM raw.pnp_catalog_entries WHERE run_id = %s",
        "run_selection_count": "SELECT COUNT(*) FROM raw.pnp_run_selection WHERE run_id = %s",
        "download_count": "SELECT COUNT(*) FROM raw.pnp_downloads WHERE run_id = %s",
        "download_column_count": """
            SELECT COUNT(*)
            FROM raw.pnp_download_columns c
            JOIN raw.pnp_downloads d ON d.download_id = c.download_id
            WHERE d.run_id = %s
        """,
        "matriculas_count": "SELECT COUNT(*) FROM raw.pnp_matriculas_src WHERE run_id = %s",
        "eficiencia_academica_count": "SELECT COUNT(*) FROM raw.pnp_eficiencia_academica_src WHERE run_id = %s",
        "servidores_count": "SELECT COUNT(*) FROM raw.pnp_servidores_src WHERE run_id = %s",
        "financeiro_count": "SELECT COUNT(*) FROM raw.pnp_financeiro_src WHERE run_id = %s",
        "quarantine_count": "SELECT COUNT(*) FROM raw.pnp_ingestion_quarantine WHERE run_id = %s",
        "run_package_count": "SELECT COUNT(*) FROM raw.pnp_run_packages WHERE run_id = %s",
        "staging_matriculas_count": "SELECT COUNT(*) FROM staging.pnp_matriculas WHERE run_id = %s",
        "staging_eficiencia_academica_count": "SELECT COUNT(*) FROM staging.pnp_eficiencia_academica WHERE run_id = %s",
        "staging_servidores_count": "SELECT COUNT(*) FROM staging.pnp_servidores WHERE run_id = %s",
        "staging_financeiro_count": "SELECT COUNT(*) FROM staging.pnp_financeiro WHERE run_id = %s",
        "curated_admin_ingestao_count": "SELECT COUNT(*) FROM curated.vw_pnp_admin_ingestao WHERE run_id = %s",
        "curated_qualidade_count": "SELECT COUNT(*) FROM curated.vw_pnp_qualidade_dados WHERE run_id = %s",
        "curated_matriculas_perfil_count": "SELECT COUNT(*) FROM curated.vw_pnp_matriculas_perfil WHERE run_id = %s",
        "curated_matriculas_oferta_count": "SELECT COUNT(*) FROM curated.vw_pnp_matriculas_oferta WHERE run_id = %s",
        "curated_eficiencia_situacao_count": "SELECT COUNT(*) FROM curated.vw_pnp_eficiencia_situacao WHERE run_id = %s",
        "curated_servidores_quadro_count": "SELECT COUNT(*) FROM curated.vw_pnp_servidores_quadro WHERE run_id = %s",
        "curated_financeiro_execucao_count": "SELECT COUNT(*) FROM curated.vw_pnp_financeiro_execucao WHERE run_id = %s",
        "curated_vanna_resumo_count": "SELECT COUNT(*) FROM curated.vw_pnp_vanna_resumo WHERE run_id = %s",
    }

    result: dict[str, Any] = {"run_id": run_id}
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        for key, query in query_map.items():
            cur.execute(query, (run_id,))
            result[key] = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT
              status,
              deduplicated_record_count,
              quality_status,
              quality_summary_json
            FROM staging.pnp_ingestion_runs
            WHERE run_id = %s
            """,
            (run_id,),
        )
        staging_row = cur.fetchone()
        if staging_row:
            result["staging_status"] = staging_row[0]
            result["staging_deduplicated_record_count"] = int(staging_row[1] or 0)
            result["staging_quality_status"] = staging_row[2]
            result["staging_quality_summary"] = staging_row[3]

    result["raw_count"] = (
        result["matriculas_count"]
        + result["eficiencia_academica_count"]
        + result["servidores_count"]
        + result["financeiro_count"]
    )
    return result


def _insert_catalog_entries(cur, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_catalog_entries (
          run_id,
          instance_key,
          ano_base,
          tipo_microdados,
          microdados_url,
          resource_key,
          visual_id,
          api_base_url,
          catalog_hash,
          is_selected
        ) VALUES %s
        ON CONFLICT (run_id, ano_base, tipo_microdados, microdados_url) DO UPDATE
        SET
          resource_key = EXCLUDED.resource_key,
          visual_id = EXCLUDED.visual_id,
          api_base_url = EXCLUDED.api_base_url,
          catalog_hash = EXCLUDED.catalog_hash,
          is_selected = EXCLUDED.is_selected,
          captured_at = NOW()
        """,
        [
            (
                row["run_id"],
                row.get("instance_key"),
                row["ano_base"],
                row["tipo_microdados"],
                row["microdados_url"],
                row.get("resource_key"),
                row.get("visual_id"),
                row.get("api_base_url"),
                row.get("catalog_hash"),
                bool(row.get("is_selected")),
            )
            for row in rows
        ],
        page_size=500,
    )


def _upsert_run_selection(cur, rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {}

    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_run_selection (
          run_id,
          instance_key,
          ano_base,
          tipo_microdados,
          microdados_url,
          selection_source,
          selection_rank,
          details_json
        ) VALUES %s
        ON CONFLICT (run_id, ano_base, tipo_microdados, microdados_url) DO UPDATE
        SET
          selection_source = EXCLUDED.selection_source,
          selection_rank = EXCLUDED.selection_rank,
          details_json = EXCLUDED.details_json,
          selected_at = NOW()
        RETURNING run_selection_id, microdados_url
        """,
        [
            (
                row["run_id"],
                row.get("instance_key"),
                row["ano_base"],
                row["tipo_microdados"],
                row["microdados_url"],
                row.get("selection_source"),
                row.get("selection_rank"),
                Json(row.get("details_json") or {}),
            )
            for row in rows
        ],
        page_size=500,
    )
    return {str(row["microdados_url"]): int(row["run_selection_id"]) for row in cur.fetchall()}


def _upsert_downloads(cur, rows: list[dict[str, Any]], run_selection_map: dict[str, int]) -> dict[str, int]:
    if not rows:
        return {}

    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_downloads (
          run_id,
          instance_key,
          run_selection_id,
          ano_base,
          tipo_microdados,
          microdados_url,
          source_file_name,
          source_file_sha256,
          content_type,
          size_bytes,
          row_count_raw,
          status,
          error_message,
          details_json
        ) VALUES %s
        ON CONFLICT (run_id, microdados_url) DO UPDATE
        SET
          run_selection_id = EXCLUDED.run_selection_id,
          source_file_name = EXCLUDED.source_file_name,
          source_file_sha256 = EXCLUDED.source_file_sha256,
          content_type = EXCLUDED.content_type,
          size_bytes = EXCLUDED.size_bytes,
          row_count_raw = EXCLUDED.row_count_raw,
          status = EXCLUDED.status,
          error_message = EXCLUDED.error_message,
          details_json = EXCLUDED.details_json,
          finished_at = NOW()
        RETURNING download_id, microdados_url
        """,
        [
            (
                row["run_id"],
                row.get("instance_key"),
                run_selection_map.get(row["microdados_url"]),
                row["ano_base"],
                row["tipo_microdados"],
                row["microdados_url"],
                row.get("source_file_name"),
                row.get("source_file_sha256"),
                row.get("content_type"),
                row.get("size_bytes"),
                row.get("row_count_raw"),
                row.get("status") or "success",
                row.get("error_message"),
                Json(row.get("details_json") or {}),
            )
            for row in rows
        ],
        page_size=200,
    )
    return {str(row["microdados_url"]): int(row["download_id"]) for row in cur.fetchall()}


def _upsert_download_columns(cur, rows: list[dict[str, Any]], download_id_by_url: dict[str, int]) -> int:
    values: list[tuple[Any, ...]] = []
    for row in rows:
        download_id = download_id_by_url.get(str(row["microdados_url"]))
        if not download_id:
            continue
        for position, column_name in enumerate(row.get("headers") or (), start=1):
            values.append(
                (
                    download_id,
                    position,
                    column_name,
                    row.get("normalized_headers", {}).get(column_name) or column_name,
                )
            )

    if not values:
        return 0

    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_download_columns (
          download_id,
          column_position,
          column_name,
          normalized_column_name
        ) VALUES %s
        ON CONFLICT (download_id, column_position) DO UPDATE
        SET
          column_name = EXCLUDED.column_name,
          normalized_column_name = EXCLUDED.normalized_column_name,
          captured_at = NOW()
        """,
        values,
        page_size=500,
    )
    return len(values)


def _insert_domain_records(cur, rows: list[dict[str, Any]], download_id_by_url: dict[str, int]) -> dict[str, int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["raw_table_name"])].append(row)

    counts: dict[str, int] = {}
    for table_name, table_rows in grouped.items():
        data_columns = list((table_rows[0].get("field_values") or {}).keys())
        insert_columns = [
            "run_id",
            "instance_key",
            "download_id",
            "record_hash",
            "source_record_id",
            "source_row_number",
            "source_file_name",
            "source_file_sha256",
            "source_url",
            "ano_base",
            "tipo_microdados",
            *data_columns,
        ]
        values = [
            (
                row["run_id"],
                row.get("instance_key"),
                download_id_by_url.get(str(row["source_url"])),
                row["record_hash"],
                row.get("source_record_id"),
                row.get("source_row_number"),
                row.get("source_file_name"),
                row.get("source_file_sha256"),
                row["source_url"],
                row.get("ano_base"),
                row["tipo_microdados"],
                *[row.get("field_values", {}).get(column_name) for column_name in data_columns],
            )
            for row in table_rows
        ]

        statement = sql.SQL(
            """
            INSERT INTO {} ({}) VALUES %s
            ON CONFLICT (run_id, download_id, source_row_number) DO NOTHING
            """
        ).format(
            sql.Identifier("raw", table_name),
            sql.SQL(", ").join(sql.Identifier(column_name) for column_name in insert_columns),
        )
        execute_values(cur, statement.as_string(cur), values, page_size=1000)
        counts[table_name.replace("pnp_", "").replace("_src", "")] = len(values)

    return counts


def _insert_quarantine(cur, rows: list[dict[str, Any]], download_id_by_url: dict[str, int]) -> int:
    if not rows:
        return 0

    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_ingestion_quarantine (
          run_id,
          instance_key,
          download_id,
          source_row_number,
          error_type,
          error_message,
          raw_line_text,
          details_json
        ) VALUES %s
        """,
        [
            (
                row["run_id"],
                row.get("instance_key"),
                download_id_by_url.get(str(row.get("source_url") or "")),
                row.get("source_row_number"),
                row.get("error_type"),
                row.get("error_message"),
                row.get("raw_line_text"),
                Json(row.get("details_json") or {}),
            )
            for row in rows
        ],
        page_size=200,
    )
    return len(rows)
