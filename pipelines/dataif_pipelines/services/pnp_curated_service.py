from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

_CURATED_SQL_FILES = (
    "010_vw_pnp_admin_ingestao.sql",
    "020_vw_pnp_qualidade_dados.sql",
    "030_vw_pnp_matriculas.sql",
    "040_vw_pnp_eficiencia.sql",
    "050_vw_pnp_servidores.sql",
    "060_vw_pnp_financeiro.sql",
    "070_vw_pnp_vanna.sql",
    "004_mv_pnp_dashboard_fast.sql",
)


def _resolve_sql_dir() -> Path:
    candidates = (
        Path(__file__).resolve().parents[2] / "sql" / "views_curated",
        Path(__file__).resolve().parents[3] / "sql" / "views_curated",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("curated SQL directory not found in expected locations")


def _read_sql_file(filename: str) -> str:
    return (_resolve_sql_dir() / filename).read_text(encoding="utf-8")


def materialize_instance_curated(dsn: str, *, run_id: str, instance_key: str | None) -> dict[str, Any]:
    with psycopg2.connect(dsn, cursor_factory=RealDictCursor) as conn, conn.cursor() as cur:
        for filename in _CURATED_SQL_FILES:
            cur.execute(_read_sql_file(filename))

        result = _collect_curated_counts(cur, run_id=run_id, instance_key=instance_key)

    _vacuum_analyze_matriculas(dsn)
    return result


def _vacuum_analyze_matriculas(dsn: str) -> None:
    # VACUUM nao pode rodar dentro de um bloco de transacao; roda numa conexao autocommit
    # separada, depois que o DROP+CREATE+INSERT+INDEX acima ja fez commit. Sem isso, os
    # indices INCLUDE criados em 004_mv_pnp_dashboard_fast.sql so viram Index Only Scan
    # depois que o autovacuum espontaneo atualizar a visibility map (minutos depois, fora
    # do controle da pipeline).
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("VACUUM (ANALYZE) curated.mv_pnp_dashboard_matriculas;")
    finally:
        conn.close()


def _collect_curated_counts(cur, *, run_id: str, instance_key: str | None) -> dict[str, Any]:
    query_map = {
        "admin_ingestao_count": "SELECT COUNT(*) FROM curated.vw_pnp_admin_ingestao WHERE run_id = %s",
        "qualidade_count": "SELECT COUNT(*) FROM curated.vw_pnp_qualidade_dados WHERE run_id = %s",
        "matriculas_perfil_count": "SELECT COUNT(*) FROM curated.vw_pnp_matriculas_perfil WHERE run_id = %s",
        "matriculas_oferta_count": "SELECT COUNT(*) FROM curated.vw_pnp_matriculas_oferta WHERE run_id = %s",
        "eficiencia_situacao_count": "SELECT COUNT(*) FROM curated.vw_pnp_eficiencia_situacao WHERE run_id = %s",
        "servidores_quadro_count": "SELECT COUNT(*) FROM curated.vw_pnp_servidores_quadro WHERE run_id = %s",
        "financeiro_execucao_count": "SELECT COUNT(*) FROM curated.vw_pnp_financeiro_execucao WHERE run_id = %s",
        "vanna_resumo_count": "SELECT COUNT(*) FROM curated.vw_pnp_vanna_resumo WHERE run_id = %s",
        "vanna_catalogo_count": "SELECT COUNT(*) FROM curated.vw_pnp_vanna_catalogo",
        "mv_matriculas_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_matriculas",
        "mv_eficiencia_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_eficiencia",
        "mv_servidores_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_servidores",
        "mv_financeiro_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_financeiro",
        "mv_qualidade_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_qualidade",
        "mv_ingestao_count": "SELECT COUNT(*) FROM curated.mv_pnp_dashboard_ingestao",
    }
    result: dict[str, Any] = {"run_id": run_id, "instance_key": instance_key}
    for key, query in query_map.items():
        if "%s" in query:
            cur.execute(query, (run_id,))
        else:
            cur.execute(query)
        row = cur.fetchone()
        result[key] = int(next(iter(row.values()))) if row else 0
    return result
