from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from dataif_pipelines.repositories import pnp_raw_repository

_ENDPOINT_SQL = {
    "Matrículas": {
        "domain": "020_pnp_matriculas.sql",
    },
    "Eficiência Acadêmica": {
        "domain": "030_pnp_eficiencia_academica.sql",
    },
    "Servidores": {
        "domain": "040_pnp_servidores.sql",
    },
    "Financeiro": {
        "domain": "050_pnp_financeiro.sql",
    },
}


def _resolve_sql_dir() -> Path:
    candidates = (
        Path(__file__).resolve().parents[2] / "sql" / "staging",
        Path(__file__).resolve().parents[3] / "sql" / "staging",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("staging SQL directory not found in expected locations")


def _read_sql_file(filename: str) -> str:
    return (_resolve_sql_dir() / filename).read_text(encoding="utf-8")


def _list_run_download_batches(dsn: str, *, run_id: str, instance_key: str | None) -> list[dict[str, Any]]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              download_id,
              tipo_microdados
            FROM raw.pnp_downloads
            WHERE run_id = %s
              AND instance_key IS NOT DISTINCT FROM %s
              AND status = 'success'
            ORDER BY
              CASE tipo_microdados
                WHEN 'Matrículas' THEN 1
                WHEN 'Eficiência Acadêmica' THEN 2
                WHEN 'Servidores' THEN 3
                WHEN 'Financeiro' THEN 4
                ELSE 99
              END,
              download_id
            """,
            (run_id, instance_key),
        )
        return [dict(row) for row in cur.fetchall()]


def _collect_materialized_counts(dsn: str, *, run_id: str) -> dict[str, int]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        counts: dict[str, int] = {}
        for table_name, result_key in (
            ("staging.pnp_matriculas", "matriculas_count"),
            ("staging.pnp_eficiencia_academica", "eficiencia_academica_count"),
            ("staging.pnp_servidores", "servidores_count"),
            ("staging.pnp_financeiro", "financeiro_count"),
        ):
            cur.execute(f"SELECT COUNT(*) AS count_value FROM {table_name} WHERE run_id = %s", (run_id,))
            counts[result_key] = int((cur.fetchone() or {}).get("count_value") or 0)
        counts["deduplicated_count"] = (
            counts["matriculas_count"]
            + counts["eficiencia_academica_count"]
            + counts["servidores_count"]
            + counts["financeiro_count"]
        )
        return counts


def materialize_instance_staging(dsn: str, *, run_id: str, instance_key: str | None) -> dict[str, Any]:
    raw_checks = pnp_raw_repository.collect_run_checks(dsn, run_id)
    started_at = datetime.now(tz=UTC)
    batch_rows = _list_run_download_batches(dsn, run_id=run_id, instance_key=instance_key)
    counts = {
        "matriculas_count": 0,
        "eficiencia_academica_count": 0,
        "servidores_count": 0,
        "financeiro_count": 0,
        "deduplicated_count": 0,
    }
    try:
        with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging.pnp_ingestion_runs (
                  run_id,
                  instance_key,
                  status,
                  selected_download_count,
                  downloaded_file_count,
                  raw_record_count,
                  deduplicated_record_count,
                  quality_status,
                  quality_summary_json,
                  started_at,
                  finished_at,
                  updated_at
                )
                VALUES (%s, %s, 'running', %s, %s, %s, 0, NULL, '{}'::jsonb, %s, NULL, NOW())
                ON CONFLICT (run_id) DO UPDATE
                SET
                  instance_key = EXCLUDED.instance_key,
                  status = EXCLUDED.status,
                  selected_download_count = EXCLUDED.selected_download_count,
                  downloaded_file_count = EXCLUDED.downloaded_file_count,
                  raw_record_count = EXCLUDED.raw_record_count,
                  deduplicated_record_count = 0,
                  quality_status = NULL,
                  quality_summary_json = '{}'::jsonb,
                  started_at = EXCLUDED.started_at,
                  finished_at = NULL,
                  updated_at = NOW()
                """,
                (
                    run_id,
                    instance_key,
                    int(raw_checks.get("run_selection_count") or 0),
                    int(raw_checks.get("download_count") or 0),
                    int(raw_checks.get("raw_count") or 0),
                    started_at,
                ),
            )
            conn.commit()

        for batch in batch_rows:
            tipo_microdados = str(batch.get("tipo_microdados") or "")
            sql_files = _ENDPOINT_SQL.get(tipo_microdados)
            if not sql_files:
                continue
            params = {
                "instance_key": instance_key,
                "run_id": run_id,
                "download_id": int(batch["download_id"]),
            }
            with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
                cur.execute("SET LOCAL synchronous_commit = OFF")
                cur.execute(_read_sql_file(sql_files["domain"]), params)
                conn.commit()

        counts = _collect_materialized_counts(dsn, run_id=run_id)

        with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE staging.pnp_ingestion_runs
                SET
                  status = 'success',
                  deduplicated_record_count = %s,
                  quality_status = 'passed',
                  quality_summary_json = %s,
                  finished_at = NOW(),
                  updated_at = NOW()
                WHERE run_id = %s
                """,
                (
                    counts["deduplicated_count"],
                    Json(
                        {
                            "raw_checks": raw_checks,
                            "staging_counts": {
                                "matriculas_count": counts["matriculas_count"],
                                "eficiencia_academica_count": counts["eficiencia_academica_count"],
                                "servidores_count": counts["servidores_count"],
                                "financeiro_count": counts["financeiro_count"],
                                "deduplicated_count": counts["deduplicated_count"],
                            },
                            "batch_count": len(batch_rows),
                        }
                    ),
                    run_id,
                ),
            )
    except Exception as exc:
        with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as error_conn:
            with error_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging.pnp_ingestion_runs (
                      run_id,
                      instance_key,
                      status,
                      selected_download_count,
                      downloaded_file_count,
                      raw_record_count,
                      deduplicated_record_count,
                      quality_status,
                      quality_summary_json,
                      started_at,
                      finished_at,
                      updated_at
                    )
                    VALUES (%s, %s, 'running', %s, %s, %s, 0, NULL, '{}'::jsonb, %s, NULL, NOW())
                    ON CONFLICT (run_id) DO UPDATE
                    SET
                      instance_key = EXCLUDED.instance_key,
                      status = EXCLUDED.status,
                      selected_download_count = EXCLUDED.selected_download_count,
                      downloaded_file_count = EXCLUDED.downloaded_file_count,
                      raw_record_count = EXCLUDED.raw_record_count,
                      deduplicated_record_count = 0,
                      quality_status = NULL,
                      quality_summary_json = '{}'::jsonb,
                      started_at = EXCLUDED.started_at,
                      finished_at = NULL,
                      updated_at = NOW()
                    """,
                    (
                        run_id,
                        instance_key,
                        int(raw_checks.get("run_selection_count") or 0),
                        int(raw_checks.get("download_count") or 0),
                        int(raw_checks.get("raw_count") or 0),
                        started_at,
                    ),
                )
        raise

    return {
        "run_id": run_id,
        "instance_key": instance_key,
        "matriculas_count": counts["matriculas_count"],
        "eficiencia_academica_count": counts["eficiencia_academica_count"],
        "servidores_count": counts["servidores_count"],
        "financeiro_count": counts["financeiro_count"],
        "deduplicated_record_count": counts["deduplicated_count"],
        "batch_count": len(batch_rows),
    }


def collect_staging_checks(dsn: str, run_id: str) -> dict[str, Any]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              run_id,
              instance_key,
              status,
              selected_download_count,
              downloaded_file_count,
              raw_record_count,
              deduplicated_record_count,
              quality_status,
              quality_summary_json,
              started_at,
              finished_at
            FROM staging.pnp_ingestion_runs
            WHERE run_id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else {"run_id": run_id}
