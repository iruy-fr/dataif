from __future__ import annotations

import re
import unicodedata
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .sql_guard import SQLGuard
from .vanna_engine import CONTEXT_INSUFFICIENT_MARKER, DataifVannaEngine


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    llm_override: dict[str, Any] | None = None


def _allowed_schema() -> str:
    return settings.effective_allowed_schema()


def _extract_sql(candidate: str) -> str:
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", candidate, flags=re.IGNORECASE | re.DOTALL)
    extracted = (fenced.group(1) if fenced else candidate).strip()
    select_match = re.search(r"\bselect\b", extracted, flags=re.IGNORECASE)
    if select_match:
        return extracted[select_match.start() :].strip()
    return extracted


def _extract_year(question: str) -> int | None:
    match = re.search(r"\b(20\d{2}|19\d{2})\b", question)
    return int(match.group(1)) if match else None


def _extract_institution(question: str) -> str | None:
    match = re.search(r"\bIF[A-Z0-9]{2,}\b", question.upper())
    return match.group(0) if match else None


def _strip_accents(text_value: str) -> str:
    normalized = unicodedata.normalize("NFKD", text_value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _normalized_question(question: str) -> str:
    return _strip_accents(question.lower())


def _is_matriculas_question(question: str) -> bool:
    return "matricula" in _normalized_question(question)


def _is_simple_matriculas_total_question(question: str) -> bool:
    lower = _normalized_question(question)
    if not _is_matriculas_question(question):
        return False
    if _extract_year(question) is None and _extract_institution(question) is None:
        return False

    total_terms = ("quantidade", "quantas", "quantos", "total", "soma")
    if not any(term in lower for term in total_terms):
        return False

    grouped_terms = (
        " por ",
        "distribu",
        "ranking",
        "top ",
        "maiores",
        "menores",
        "curso",
        "sexo",
        "cor",
        "raca",
        "raça",
        "renda",
        "faixa",
        "modalidade",
        "turno",
        "oferta",
        "municipio",
        "município",
        "uf",
        "regiao",
        "região",
        "situacao",
        "situação",
        "compar",
        "evolu",
        "serie",
        "série",
    )
    return not any(term in lower for term in grouped_terms)



# As duas views abaixo nao sao materializadas: recalculam um GROUP BY sobre staging.pnp_matriculas
# a cada consulta. curated.mv_pnp_dashboard_matriculas cobre o mesmo grao de dados, ja particionada
# por ano e indexada, exceto para as colunas em _HEAVY_ONLY_COLUMNS (que so existem nas views pesadas).
_HEAVY_VIEWS = ("curated.vw_pnp_matriculas_perfil", "curated.vw_pnp_matriculas_oferta")
_FAST_SOURCE = "curated.mv_pnp_dashboard_matriculas"
_HEAVY_ONLY_COLUMNS = ("eixo_tecnologico", "subeixo_tecnologico")

# Valores informais -> valores codificados usados de fato em curated.mv_pnp_dashboard_matriculas.
# Só sexo está confirmado (F/M/S/I); outras colunas categóricas entram aqui conforme forem
# validadas via `SELECT DISTINCT <coluna> FROM curated.mv_pnp_dashboard_matriculas` na VM.
_CATEGORICAL_LITERAL_MAP: dict[str, dict[str, str]] = {
    "sexo": {
        "feminino": "F",
        "mulher": "F",
        "masculino": "M",
        "homem": "M",
    },
}

# Valores canonicos (com acentuacao correta) de curated.mv_pnp_dashboard_matriculas, levantados
# via `SELECT DISTINCT <coluna> ...` na VM. A LLM as vezes gera o literal certo mas sem acento
# (ex.: 'Educacao a Distancia' em vez de 'Educação a Distância'), o que casa zero linhas sem
# erro. _normalize_categorical_literals corrige isso comparando por acento/caixa, nao por
# substring fixa, entao cobre qualquer valor da lista sem precisar de um caso por pergunta.
_CATEGORICAL_KNOWN_VALUES: dict[str, tuple[str, ...]] = {
    "cor_raca": ("Amarela", "Branca", "Indígena", "Parda", "Preta", "Não declarada", "S/I"),
    "faixa_etaria": (
        "Menor de 14 anos", "15 a 19 anos", "20 a 24 anos", "25 a 29 anos", "30 a 34 anos",
        "35 a 39 anos", "40 a 44 anos", "45 a 49 anos", "50 a 54 anos", "55 a 59 anos",
        "Maior de 60 anos", "S/I",
    ),
    "renda_familiar": (
        "0<RFP<=0,5", "0,5<RFP<=1", "1<RFP<=1,5", "1,5<RFP<=2,5", "2,5<RFP<=3,5",
        "RFP>3,5", "Não declarada", "S/I",
    ),
    "modalidade_ensino": ("Educação Presencial", "Educação a Distância"),
    "turno": ("Matutino", "Vespertino", "Noturno", "Integral", "Não se aplica", "Sem Informação"),
    "situacao_matricula": (
        "Em curso", "Concluída", "Integralizada", "Abandono", "Cancelada", "Desligada",
        "Reprovado", "Transf. externa", "Transf. interna",
    ),
    "tipo_curso": (
        "Técnico", "Tecnologia", "Bacharelado", "Licenciatura", "ABI",
        "Qualificação Profissional (FIC)", "Especialização Técnica",
        "Especialização (Lato Sensu)", "Mestrado", "Mestrado Profissional", "Doutorado",
        "Doutorado Profissional", "Ensino Fundamental I", "Ensino Fundamental II",
        "Ensino Médio", "Educação Infantil",
    ),
    "tipo_oferta": (
        "Integrado", "Concomitante", "Subsequente", "Todos", "Não se aplica",
        "PROEJA -", "PROEJA - Integrado", "PROEJA - Concomitante", "PROEJA - Subsequente",
    ),
}


def _normalize_categorical_literals(sql: str) -> str:
    optimized = sql
    for column, value_map in _CATEGORICAL_LITERAL_MAP.items():
        for informal, coded in value_map.items():
            pattern = re.compile(
                rf"({re.escape(column)}\s*=\s*)'{re.escape(informal)}'",
                flags=re.IGNORECASE,
            )
            optimized = pattern.sub(rf"\1'{coded}'", optimized)

    def _fix_accent(match: re.Match[str]) -> str:
        column = match.group("column")
        literal = match.group("literal")
        known_values = _CATEGORICAL_KNOWN_VALUES.get(column.lower())
        if not known_values:
            return match.group(0)
        literal_key = _strip_accents(literal).lower()
        for canonical in known_values:
            if _strip_accents(canonical).lower() == literal_key and canonical != literal:
                return f"{match.group('prefix')}'{canonical}'"
        return match.group(0)

    literal_pattern = re.compile(
        r"(?P<prefix>(?P<column>[a-z_]+)\s*=\s*)'(?P<literal>[^']*)'",
        flags=re.IGNORECASE,
    )
    optimized = literal_pattern.sub(_fix_accent, optimized)
    return optimized


def _optimize_generated_sql(sql: str) -> tuple[str, bool]:
    optimized = sql.strip()
    lower = optimized.lower()
    changed = False

    uses_heavy_only_column = any(column in lower for column in _HEAVY_ONLY_COLUMNS)
    if not uses_heavy_only_column:
        for heavy_view in _HEAVY_VIEWS:
            if heavy_view in lower:
                optimized = re.sub(re.escape(heavy_view), _FAST_SOURCE, optimized, flags=re.IGNORECASE)
                changed = True
                lower = optimized.lower()

    normalized = _normalize_categorical_literals(optimized)
    if normalized != optimized:
        optimized = normalized
        changed = True

    return optimized, changed


def _fallback_sql(question: str) -> str:
    lower = _normalized_question(question)
    if "cat" in lower or "catálogo" in lower or "catalogo" in lower or "view" in lower:
        return (
            "SELECT relation_group, relation_name, relation_description "
            "FROM curated.vw_pnp_vanna_catalogo ORDER BY relation_group, relation_name LIMIT 50"
        )
    if "total" in lower or "quant" in lower or "matricula" in lower:
        filters: list[str] = []
        year = _extract_year(question)
        institution = _extract_institution(question)
        if year is not None:
            filters.append(f"ano = {year}")
        if institution is not None:
            filters.append(f"instituicao = '{institution}'")
        where_clause = f"WHERE {' AND '.join(filters)} " if filters else ""
        return (
            "SELECT ano, instituicao, SUM(matriculas) AS total_matriculas "
            f"FROM {_FAST_SOURCE} "
            f"{where_clause}"
            "GROUP BY ano, instituicao ORDER BY ano DESC, total_matriculas DESC LIMIT 50"
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
engine = create_engine(
    settings.vanna_dsn,
    pool_pre_ping=True,
    connect_args={"options": "-c statement_timeout=15000"},
)
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
    simple_total_question = _is_simple_matriculas_total_question(req.question)
    if simple_total_question:
        generation_mode = "optimized_fallback: pnp_matriculas_rollup"
        sql = _fallback_sql(req.question)
    else:
        try:
            raw_response = vanna_engine.generate_sql(req.question, runtime_override=req.llm_override)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Vanna SQL generation failed: {exc}") from exc

        sql = _extract_sql(raw_response)
        if not re.search(r"\bselect\b", sql, flags=re.IGNORECASE):
            # A LLM nao devolveu SQL nenhuma -- seja porque julgou o contexto insuficiente
            # (guideline padrao da lib vanna), seja porque tentou uma intermediate_sql bloqueada
            # por allow_llm_to_see_data=False. Detectamos isso pela ausencia estrutural de
            # "select" na resposta, nao por casar um texto especifico, entao cobre qualquer
            # fraseado que a LLM use. Repassamos ao usuario em vez do erro tecnico do SQLGuard.
            explanation = sql.strip()
            if explanation.upper().startswith(CONTEXT_INSUFFICIENT_MARKER.upper()):
                explanation = explanation[len(CONTEXT_INSUFFICIENT_MARKER) :].strip()
            raise HTTPException(
                status_code=422,
                detail=(
                    "Não consegui gerar uma consulta para esta pergunta com o contexto "
                    "disponível. Tente adicionar mais detalhes (ano, instituição, ou o que "
                    f"exatamente deseja consultar). Detalhe: {explanation}"
                ),
            )

        sql, optimized = _optimize_generated_sql(sql)
        if optimized:
            generation_mode = "vanna: optimized_sql"

    try:
        sql = guard.enforce_limit(sql, settings.vanna_max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        with engine.begin() as conn:
            rows = conn.execute(text(sql)).fetchmany(settings.vanna_max_rows)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail=f"Vanna SQL execution failed: {exc}") from exc

    items = [dict(row._mapping) for row in rows]
    return {
        "question": req.question,
        "sql": sql,
        "rows": items,
        "row_count": len(items),
        "generation_mode": generation_mode,
    }
