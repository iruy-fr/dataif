#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "infra" / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def build_dsn() -> str:
    explicit = os.getenv("WAREHOUSE_DSN")
    if explicit:
        return explicit

    env_file = load_env_file(ENV_PATH)
    db_name = os.getenv("DATAIF_DB_NAME") or env_file.get("DATAIF_DB_NAME", "dataif")
    user = os.getenv("DATAIF_ETL_USER") or env_file.get("DATAIF_ETL_USER", "etl_user")
    password = os.getenv("DATAIF_ETL_PASSWORD") or env_file.get("DATAIF_ETL_PASSWORD", "etl_password")
    host = os.getenv("POSTGRES_HOST") or env_file.get("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_EXPOSE_PORT") or env_file.get("POSTGRES_EXPOSE_PORT", "5433")

    if host == "postgres":
        host = "localhost"

    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def fetch_one(cur: RealDictCursor, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    cur.execute(query, params)
    return cur.fetchone()


def fetch_all(cur: RealDictCursor, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cur.execute(query, params)
    return list(cur.fetchall())


def latest_raw_run(cur: RealDictCursor, run_id: str | None) -> dict[str, Any] | None:
    if run_id:
        return fetch_one(
            cur,
            """
            SELECT run_id, status, extracted_count, loaded_count, details, started_at, finished_at
            FROM audit.etl_run_log
            WHERE connector_id = 'nilo_pecanha'
              AND run_id = %s
            ORDER BY finished_at DESC NULLS LAST, started_at DESC
            LIMIT 1
            """,
            (run_id,),
        )

    return fetch_one(
        cur,
        """
        SELECT run_id, status, extracted_count, loaded_count, details, started_at, finished_at
        FROM audit.etl_run_log
        WHERE connector_id = 'nilo_pecanha'
          AND status = 'raw_loaded'
        ORDER BY finished_at DESC NULLS LAST, started_at DESC
        LIMIT 1
        """,
        (),
    )


def load_manifest(cur: RealDictCursor, run_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        cur,
        """
        SELECT content_text::jsonb AS manifest
        FROM raw.nilo_pecanha_assets
        WHERE run_id = %s
          AND asset_type = 'powerbi_microdados_manifest'
        ORDER BY ingested_at DESC
        LIMIT 1
        """,
        (run_id,),
    )
    return dict(row["manifest"]) if row and row.get("manifest") else None


def load_raw_counts_by_file(cur: RealDictCursor, run_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        cur,
        """
        SELECT
          payload->>'tipo_microdados' AS tipo_microdados,
          payload->>'source_file_name' AS source_file_name,
          COUNT(*)::bigint AS raw_rows
        FROM raw.nilo_pecanha_records
        WHERE run_id = %s
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        (run_id,),
    )


def load_core_checks(cur: RealDictCursor, run_id: str) -> dict[str, Any]:
    row = fetch_one(
        cur,
        """
        SELECT
          COUNT(*)::bigint AS total_rows,
          SUM(CASE WHEN COALESCE(payload->>'id', '') = '' THEN 1 ELSE 0 END)::bigint AS missing_id,
          SUM(CASE WHEN COALESCE(payload->>'ano', '') = '' THEN 1 ELSE 0 END)::bigint AS missing_ano,
          SUM(CASE WHEN COALESCE(payload->>'tipo_microdados', '') = '' THEN 1 ELSE 0 END)::bigint AS missing_tipo_microdados,
          SUM(CASE WHEN COALESCE(payload->>'source_file_name', '') = '' THEN 1 ELSE 0 END)::bigint AS missing_source_file_name,
          SUM(CASE WHEN COALESCE(payload->>'microdados_url', '') = '' THEN 1 ELSE 0 END)::bigint AS missing_microdados_url,
          SUM(
            CASE
              WHEN COALESCE(payload->>'source_method', '') <> 'powerbi_microdados' THEN 1
              ELSE 0
            END
          )::bigint AS unexpected_source_method,
          SUM(
            CASE
              WHEN COALESCE(payload->>'ano', '') <> ''
               AND COALESCE(payload->>'ano', '') !~ '^[0-9]{4}$'
                THEN 1
              ELSE 0
            END
          )::bigint AS ano_not_four_digits,
          SUM(
            CASE
              WHEN COALESCE(payload->>'ano', '') ~ '^[0-9]{4}$'
               AND COALESCE(substring(payload->>'source_file_name' FROM '([0-9]{4})'), '') <> ''
               AND payload->>'ano' <> substring(payload->>'source_file_name' FROM '([0-9]{4})')
                THEN 1
              ELSE 0
            END
          )::bigint AS ano_file_mismatch
        FROM raw.nilo_pecanha_records
        WHERE run_id = %s
        """,
        (run_id,),
    )
    return row or {}


def load_sample_profile(cur: RealDictCursor, run_id: str, sample_size: int, max_examples: int) -> list[dict[str, Any]]:
    return fetch_all(
        cur,
        """
        WITH sample AS (
          SELECT payload
          FROM raw.nilo_pecanha_records
          WHERE run_id = %s
          ORDER BY id
          LIMIT %s
        ),
        pairs AS (
          SELECT
            e.key,
            NULLIF(BTRIM(e.value), '') AS value
          FROM sample s
          CROSS JOIN LATERAL jsonb_each_text(s.payload) AS e(key, value)
        ),
        distinct_values AS (
          SELECT DISTINCT key, value
          FROM pairs
          WHERE value IS NOT NULL
        ),
        ranked_values AS (
          SELECT
            key,
            value,
            ROW_NUMBER() OVER (PARTITION BY key ORDER BY value) AS rn
          FROM distinct_values
        )
        SELECT
          p.key,
          COUNT(*) FILTER (WHERE p.value IS NOT NULL)::bigint AS populated_rows,
          COUNT(DISTINCT p.value)::bigint AS distinct_values,
          COALESCE(
            ARRAY_AGG(rv.value ORDER BY rv.value) FILTER (WHERE rv.rn <= %s),
            ARRAY[]::text[]
          ) AS example_values
        FROM pairs p
        LEFT JOIN ranked_values rv
          ON rv.key = p.key
         AND rv.value = p.value
        GROUP BY p.key
        ORDER BY populated_rows DESC, p.key
        """,
        (run_id, sample_size, max_examples),
    )


def print_operational_summary(run_row: dict[str, Any], manifest: dict[str, Any], raw_counts: list[dict[str, Any]]) -> list[str]:
    details = dict(run_row.get("details") or {})
    runtime = dict(details.get("runtime") or {})
    checks = dict(details.get("checks") or {})
    manifest_downloads = list(manifest.get("downloads") or [])
    raw_total = sum(int(row["raw_rows"]) for row in raw_counts)
    manifest_total = sum(int(item.get("row_count") or 0) for item in manifest_downloads)

    print("Validacao operacional")
    print(f"- run_id: {run_row['run_id']}")
    print(f"- status audit: {run_row['status']}")
    print(f"- periodo: {run_row['started_at']} -> {run_row['finished_at']}")
    print(f"- downloads reportados pela pipeline: {runtime.get('download_count', 0)}")
    print(f"- raw_count reportado no audit: {checks.get('raw_count', 0)}")
    print(f"- asset_count reportado no audit: {checks.get('asset_count', 0)}")
    print(f"- manifesto: {len(manifest_downloads)} downloads / {manifest_total} linhas esperadas")
    print(f"- raw agregado por arquivo: {len(raw_counts)} arquivos / {raw_total} linhas persistidas")

    failures: list[str] = []
    if int(runtime.get("download_count") or 0) != len(manifest_downloads):
        failures.append("download_count do audit difere do manifesto")
    if int(checks.get("raw_count") or 0) != manifest_total:
        failures.append("raw_count do audit difere da soma do manifesto")
    if raw_total != manifest_total:
        failures.append("raw agregado por arquivo difere da soma do manifesto")

    print("")
    print("Conferencia por arquivo")
    counts_by_key = {
        (str(row["tipo_microdados"]), str(row["source_file_name"])): int(row["raw_rows"])
        for row in raw_counts
    }
    for item in manifest_downloads:
        key = (str(item.get("tipo_microdados") or ""), str(item.get("source_file_name") or ""))
        manifest_rows = int(item.get("row_count") or 0)
        raw_rows = counts_by_key.get(key, 0)
        marker = "OK" if manifest_rows == raw_rows else "DIVERGENTE"
        print(f"- {key[0]} | {key[1]} | manifesto={manifest_rows} | raw={raw_rows} | {marker}")
        if manifest_rows != raw_rows:
            failures.append(f"arquivo divergente: {key[1]}")

    return failures


def print_analytical_summary(core_checks: dict[str, Any], profile: list[dict[str, Any]], sample_size: int) -> list[str]:
    failures: list[str] = []

    print("")
    print("Primeira validacao analitica")
    print(f"- total_rows: {core_checks.get('total_rows', 0)}")
    for key in (
        "missing_id",
        "missing_ano",
        "missing_tipo_microdados",
        "missing_source_file_name",
        "missing_microdados_url",
        "unexpected_source_method",
        "ano_not_four_digits",
        "ano_file_mismatch",
    ):
        value = int(core_checks.get(key) or 0)
        print(f"- {key}: {value}")
        if value > 0:
            failures.append(f"{key}={value}")

    print("")
    print(f"Perfil amostral de colunas ({sample_size} registros)")
    for row in profile[:20]:
        examples = ", ".join(row["example_values"][:4]) if row["example_values"] else "-"
        print(
            f"- {row['key']}: preenchidos={row['populated_rows']} "
            f"| distintos={row['distinct_values']} | exemplos={examples}"
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida a ultima run raw do conector PNP no Postgres.")
    parser.add_argument("--run-id", help="Run especifica para validar. Se omitido, usa a ultima raw_loaded.")
    parser.add_argument("--sample-size", type=int, default=1000, help="Quantidade de registros usados no perfil amostral.")
    parser.add_argument("--max-examples", type=int, default=4, help="Quantidade maxima de exemplos por coluna no perfil.")
    parser.add_argument("--strict", action="store_true", help="Retorna codigo 1 se qualquer inconsistência for encontrada.")
    args = parser.parse_args()

    dsn = build_dsn()
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        run_row = latest_raw_run(cur, args.run_id)
        if not run_row:
            print("Nenhuma run encontrada para o conector nilo_pecanha.")
            return 1

        manifest = load_manifest(cur, str(run_row["run_id"]))
        if not manifest:
            print(f"Run {run_row['run_id']} nao possui manifesto em raw.nilo_pecanha_assets.")
            return 1

        raw_counts = load_raw_counts_by_file(cur, str(run_row["run_id"]))
        core_checks = load_core_checks(cur, str(run_row["run_id"]))
        profile = load_sample_profile(cur, str(run_row["run_id"]), args.sample_size, args.max_examples)

    operational_failures = print_operational_summary(run_row, manifest, raw_counts)
    analytical_failures = print_analytical_summary(core_checks, profile, args.sample_size)

    all_failures = [*operational_failures, *analytical_failures]
    print("")
    if all_failures:
        print("Resultado final: inconsistencias encontradas")
        for failure in all_failures:
            print(f"- {failure}")
        return 1 if args.strict else 0

    print("Resultado final: sem inconsistencias nas validacoes executadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
