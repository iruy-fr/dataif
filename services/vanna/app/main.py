from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from .config import settings
from .sql_guard import SQLGuard
from .vanna_engine import DataifVannaEngine


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)


def _allowed_schema() -> str:
    return settings.effective_allowed_schema()


def _extract_sql(candidate: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", candidate, flags=re.IGNORECASE | re.DOTALL)
    return (fenced.group(1) if fenced else candidate).strip()


def _fallback_sql(question: str) -> str:
    lower = question.lower()
    if "cat" in lower or "catálogo" in lower or "catalogo" in lower or "view" in lower:
        return (
            "SELECT relation_group, relation_name, relation_description "
            "FROM curated.vw_pnp_vanna_catalogo ORDER BY relation_group, relation_name LIMIT 50"
        )
    if "total" in lower or "quant" in lower or "matricula" in lower or "matrícula" in lower:
        return (
            "SELECT ano, SUM(matriculas) AS total_matriculas "
            "FROM curated.mv_pnp_dashboard_matriculas "
            "GROUP BY ano ORDER BY ano DESC LIMIT 50"
        )
    if "indicador" in lower or "resumo" in lower or "média" in lower or "media" in lower:
        return (
            "SELECT dominio, indicador, ano, COUNT(*) AS registros, AVG(valor) AS media_valor "
            "FROM curated.vw_pnp_vanna_resumo "
            "GROUP BY dominio, indicador, ano ORDER BY ano DESC, dominio, indicador LIMIT 50"
        )
    return (
        "SELECT run_id, instance_key, dominio, indicador, ano, instituicao, regiao, uf, municipio, valor "
        "FROM curated.vw_pnp_vanna_resumo "
        "ORDER BY ano DESC NULLS LAST, dominio, indicador LIMIT 50"
    )


app = FastAPI(title="dataif-vanna", version="0.1.0")
engine = create_engine(settings.vanna_dsn, pool_pre_ping=True)
allowed_schema = _allowed_schema()
guard = SQLGuard({allowed_schema})
vanna_engine = DataifVannaEngine(settings, engine, allowed_schema)


@app.get("/health")
def health() -> dict[str, object]:
    runtime = vanna_engine.runtime_config()
    return {
        "status": "ok",
        "llm_provider": runtime.provider,
        "model": runtime.model_name(),
        "allowed_schema": allowed_schema,
        "llm_available": vanna_engine.is_llm_available(),
        "llm_status": vanna_engine.provider_status(),
    }


@app.post("/train")
def train() -> dict[str, object]:
    try:
        vanna_engine.train_once(force=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Vanna unavailable for training: {exc}") from exc
    return {"status": "ok", "allowed_schema": allowed_schema}


@app.post("/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    generation_mode = "vanna"
    try:
        sql = _extract_sql(vanna_engine.generate_sql(req.question))
    except Exception as exc:
        generation_mode = f"fallback: {exc}"
        sql = _fallback_sql(req.question)

    try:
        sql = guard.enforce_limit(sql, settings.vanna_max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with engine.begin() as conn:
        rows = conn.execute(text(sql)).fetchmany(settings.vanna_max_rows)

    items = [dict(row._mapping) for row in rows]
    return {
        "question": req.question,
        "sql": sql,
        "rows": items,
        "row_count": len(items),
        "generation_mode": generation_mode,
    }
