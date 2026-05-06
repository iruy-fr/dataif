from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import md5


API_BASE = os.getenv("METABASE_API_URL", "http://localhost:3001/api").rstrip("/")
API_KEY = os.getenv("METABASE_API_KEY")
DATABASE_ID = int(os.getenv("METABASE_DATABASE_ID", "2"))
DASHBOARD_NAME = os.getenv(
    "METABASE_DASHBOARD_NAME",
    "PNP 2024 - Painel Integrado de Gestao Administrativa",
)

if not API_KEY:
    raise SystemExit("METABASE_API_KEY is required")


def api(method: str, path: str, payload: dict | list | None = None) -> dict | list:
    data = None
    headers = {"x-api-key": API_KEY, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def find_dashboard_by_name(name: str) -> dict | None:
    for dashboard in api("GET", "/dashboard"):
        if dashboard.get("name") == name and not dashboard.get("archived"):
            return dashboard
    return None


def list_cards() -> list[dict]:
    return list(api("GET", "/card"))


def archive_card(card_id: int) -> None:
    api("PUT", f"/card/{card_id}", {"archived": True})


def cleanup_previous_pnp_cards() -> None:
    prefix = "PNP 2024 - "
    for card in list_cards():
        if card.get("archived"):
            continue
        name = card.get("name") or ""
        if name.startswith(prefix):
            archive_card(int(card["id"]))


def ensure_dashboard() -> int:
    existing = find_dashboard_by_name(DASHBOARD_NAME)
    if existing:
        dashboard_id = int(existing["id"])
        api(
            "PUT",
            f"/dashboard/{dashboard_id}",
            {
                "name": DASHBOARD_NAME,
                "description": DASHBOARD_DESCRIPTION,
                "width": "fixed",
                "auto_apply_filters": True,
                "parameters": DASHBOARD_PARAMETERS,
                "tabs": [],
                "dashcards": [],
            },
        )
        return dashboard_id

    response = api(
        "POST",
        "/dashboard",
        {
            "name": DASHBOARD_NAME,
            "description": DASHBOARD_DESCRIPTION,
            "width": "fixed",
            "auto_apply_filters": True,
            "collection_id": None,
            "parameters": DASHBOARD_PARAMETERS,
        },
    )
    return int(response["id"])


def create_card(card: "CardDef") -> int:
    response = api(
        "POST",
        "/card",
        {
            "name": card.name,
            "description": card.description,
            "display": card.display,
            "database_id": DATABASE_ID,
            "collection_id": None,
            "dataset_query": {
                "type": "native",
                "database": DATABASE_ID,
                "native": {
                    "query": card.sql,
                    "template-tags": card.template_tags(),
                },
            },
            "visualization_settings": card.visualization_settings,
        },
    )
    return int(response["id"])


def update_dashboard(dashboard_id: int, tabs: list[dict], dashcards: list[dict]) -> None:
    api(
        "PUT",
        f"/dashboard/{dashboard_id}",
        {
            "name": DASHBOARD_NAME,
            "description": DASHBOARD_DESCRIPTION,
            "width": "fixed",
            "auto_apply_filters": True,
            "parameters": DASHBOARD_PARAMETERS,
            "tabs": tabs,
            "dashcards": dashcards,
        },
    )


@dataclass(frozen=True)
class CardDef:
    name: str
    description: str
    tab: str
    row: int
    col: int
    size_x: int
    size_y: int
    sql: str
    display: str
    filters: tuple[str, ...]
    visualization_settings: dict

    def template_tags(self) -> dict:
        return {
            slug: {
                **TEMPLATE_TAGS[slug],
                # Metabase requires template tag ids so the SQL editor can persist
                # card parameter definitions on subsequent edits.
                "id": md5(f"{self.name}:{slug}".encode("utf-8")).hexdigest()[:12],
            }
            for slug in self.filters
        }

    def parameter_mappings(self) -> list[dict]:
        return [
            {
                "parameter_id": PARAM_ID_BY_SLUG[slug],
                "target": ["variable", ["template-tag", slug]],
            }
            for slug in self.filters
        ]


@dataclass(frozen=True)
class VirtualCardDef:
    tab: str
    text: str
    row: int
    col: int
    size_x: int
    size_y: int


DASHBOARD_DESCRIPTION = (
    "Painel da PNP organizado em guias tematicas leves, com filtros do cabecalho "
    "ligados apenas aos conjuntos de perguntas correspondentes."
)

TAB_LAYOUT = ["Matriculas", "Eficiencia Academica", "Servidores", "Financeiro", "Qualidade e Ingestao"]

DASHBOARD_PARAMETERS = [
    {"id": "p_ano", "name": "Ano", "slug": "ano", "type": "number/=", "sectionId": "number"},
    {"id": "p_instituicao", "name": "Instituicao", "slug": "instituicao", "type": "string/=", "sectionId": "string"},
    {"id": "p_regiao", "name": "Regiao", "slug": "regiao", "type": "string/=", "sectionId": "string"},
    {"id": "p_uf", "name": "UF", "slug": "uf", "type": "string/=", "sectionId": "string"},
    {"id": "p_municipio", "name": "Municipio", "slug": "municipio", "type": "string/=", "sectionId": "string"},
    {"id": "p_sexo", "name": "Sexo", "slug": "sexo", "type": "string/=", "sectionId": "string"},
    {"id": "p_cor_raca", "name": "Cor / Raca", "slug": "cor_raca", "type": "string/=", "sectionId": "string"},
    {"id": "p_renda_familiar", "name": "Renda Familiar", "slug": "renda_familiar", "type": "string/=", "sectionId": "string"},
    {"id": "p_faixa_etaria", "name": "Faixa Etaria", "slug": "faixa_etaria", "type": "string/=", "sectionId": "string"},
    {"id": "p_situacao_matricula", "name": "Situacao de Matricula", "slug": "situacao_matricula", "type": "string/=", "sectionId": "string"},
    {"id": "p_modalidade_ensino", "name": "Modalidade de Ensino", "slug": "modalidade_ensino", "type": "string/=", "sectionId": "string"},
    {"id": "p_tipo_curso", "name": "Tipo de Curso", "slug": "tipo_curso", "type": "string/=", "sectionId": "string"},
    {"id": "p_tipo_oferta", "name": "Tipo de Oferta", "slug": "tipo_oferta", "type": "string/=", "sectionId": "string"},
    {"id": "p_turno", "name": "Turno", "slug": "turno", "type": "string/=", "sectionId": "string"},
    {"id": "p_nome_curso", "name": "Nome do Curso", "slug": "nome_curso", "type": "string/=", "sectionId": "string"},
    {"id": "p_matricula_atendida", "name": "Matricula Atendida", "slug": "matricula_atendida", "type": "string/=", "sectionId": "string"},
    {"id": "p_classe", "name": "Classe", "slug": "classe", "type": "string/=", "sectionId": "string"},
    {"id": "p_jornada_trabalho", "name": "Jornada de Trabalho", "slug": "jornada_trabalho", "type": "string/=", "sectionId": "string"},
    {"id": "p_titulacao", "name": "Titulacao", "slug": "titulacao", "type": "string/=", "sectionId": "string"},
    {"id": "p_vinculo_carreira", "name": "Vinculo de Carreira", "slug": "vinculo_carreira", "type": "string/=", "sectionId": "string"},
    {"id": "p_vinculo_contrato", "name": "Vinculo de Contrato", "slug": "vinculo_contrato", "type": "string/=", "sectionId": "string"},
    {"id": "p_vinculo_professor", "name": "Vinculo Professor", "slug": "vinculo_professor", "type": "string/=", "sectionId": "string"},
    {"id": "p_nome_uo", "name": "Nome UO", "slug": "nome_uo", "type": "string/=", "sectionId": "string"},
    {"id": "p_grupo_despesa", "name": "Grupo de Despesa", "slug": "grupo_despesa", "type": "string/=", "sectionId": "string"},
    {"id": "p_cod_acao", "name": "Codigo da Acao", "slug": "cod_acao", "type": "string/=", "sectionId": "string"},
    {"id": "p_nome_acao", "name": "Nome da Acao", "slug": "nome_acao", "type": "string/=", "sectionId": "string"},
]

PARAM_ID_BY_SLUG = {item["slug"]: item["id"] for item in DASHBOARD_PARAMETERS}

TEMPLATE_TAGS = {
    slug: {
        "name": slug,
        "display-name": next(item["name"] for item in DASHBOARD_PARAMETERS if item["slug"] == slug),
        "type": "number" if slug == "ano" else "text",
        "required": False,
    }
    for slug in PARAM_ID_BY_SLUG
}


def where_clause(filters: tuple[str, ...]) -> str:
    clauses = {
        "ano": "ano = {{ano}}",
        "instituicao": "instituicao = {{instituicao}}",
        "regiao": "regiao = {{regiao}}",
        "uf": "uf = {{uf}}",
        "municipio": "municipio = {{municipio}}",
        "sexo": "sexo = {{sexo}}",
        "cor_raca": "cor_raca = {{cor_raca}}",
        "renda_familiar": "renda_familiar = {{renda_familiar}}",
        "faixa_etaria": "faixa_etaria = {{faixa_etaria}}",
        "situacao_matricula": "situacao_matricula = {{situacao_matricula}}",
        "modalidade_ensino": "modalidade_ensino = {{modalidade_ensino}}",
        "tipo_curso": "tipo_curso = {{tipo_curso}}",
        "tipo_oferta": "tipo_oferta = {{tipo_oferta}}",
        "turno": "turno = {{turno}}",
        "nome_curso": "nome_curso = {{nome_curso}}",
        "matricula_atendida": "matricula_atendida = {{matricula_atendida}}",
        "classe": "classe = {{classe}}",
        "jornada_trabalho": "jornada_trabalho = {{jornada_trabalho}}",
        "titulacao": "titulacao = {{titulacao}}",
        "vinculo_carreira": "vinculo_carreira = {{vinculo_carreira}}",
        "vinculo_contrato": "vinculo_contrato = {{vinculo_contrato}}",
        "vinculo_professor": "vinculo_professor = {{vinculo_professor}}",
        "nome_uo": "nome_uo = {{nome_uo}}",
        "grupo_despesa": "grupo_despesa = {{grupo_despesa}}",
        "cod_acao": "cod_acao = {{cod_acao}}",
        "nome_acao": "nome_acao = {{nome_acao}}",
    }
    parts = ["WHERE 1=1"]
    for slug in filters:
        parts.append(f"[[ AND {clauses[slug]} ]]")
    return "\n".join(parts)


MATRICULAS_FILTERS = (
    "ano",
    "instituicao",
    "regiao",
    "uf",
    "municipio",
    "sexo",
    "cor_raca",
    "renda_familiar",
    "faixa_etaria",
    "situacao_matricula",
    "modalidade_ensino",
    "tipo_curso",
    "tipo_oferta",
    "turno",
    "nome_curso",
)

EFICIENCIA_FILTERS = (
    "ano",
    "instituicao",
    "regiao",
    "uf",
    "municipio",
    "sexo",
    "cor_raca",
    "renda_familiar",
    "faixa_etaria",
    "situacao_matricula",
    "matricula_atendida",
)

SERVIDORES_FILTERS = (
    "ano",
    "instituicao",
    "regiao",
    "classe",
    "jornada_trabalho",
    "titulacao",
    "vinculo_carreira",
    "vinculo_contrato",
    "vinculo_professor",
)

FINANCEIRO_FILTERS = ("ano", "nome_uo", "grupo_despesa", "cod_acao", "nome_acao")

MATRICULAS_SOURCE = "curated.mv_pnp_dashboard_matriculas"
EFICIENCIA_SOURCE = "curated.mv_pnp_dashboard_eficiencia"
SERVIDORES_SOURCE = "curated.mv_pnp_dashboard_servidores"
FINANCEIRO_SOURCE = "curated.mv_pnp_dashboard_financeiro"
QUALIDADE_SOURCE = "curated.mv_pnp_dashboard_qualidade"
INGESTAO_SOURCE = "curated.mv_pnp_dashboard_ingestao"

VIRTUALS = [
    VirtualCardDef("Matriculas", "Oferta, procura, perfil discente e situacao das matriculas.", 0, 0, 24, 1),
    VirtualCardDef("Eficiencia Academica", "Permanencia, conclusao e evasao por perfil e territorio.", 0, 0, 24, 1),
    VirtualCardDef("Servidores", "Composicao do quadro por instituicao, titulacao, jornada e vinculos.", 0, 0, 24, 1),
    VirtualCardDef("Financeiro", "Execucao financeira por UO, acao e grupo de despesa.", 0, 0, 24, 1),
    VirtualCardDef("Qualidade e Ingestao", "Qualidade basica dos microdados e trilha operacional da carga.", 0, 0, 24, 1),
]

CARDS = [
    CardDef(
        name="PNP 2024 - KPI Matriculas",
        description="Total de matriculas no recorte.",
        tab="Matriculas",
        row=1,
        col=0,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(matriculas), 0) AS matriculas FROM {MATRICULAS_SOURCE}\n{where_clause(MATRICULAS_FILTERS)}",
        display="scalar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Inscritos",
        description="Total de inscritos no recorte.",
        tab="Matriculas",
        row=1,
        col=6,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(inscritos), 0) AS inscritos FROM {MATRICULAS_SOURCE}\n{where_clause(MATRICULAS_FILTERS)}",
        display="scalar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Vagas Ofertadas",
        description="Total de vagas ofertadas no recorte.",
        tab="Matriculas",
        row=1,
        col=12,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(vagas_ofertadas), 0) AS vagas_ofertadas FROM {MATRICULAS_SOURCE}\n{where_clause(MATRICULAS_FILTERS)}",
        display="scalar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Relacao Inscritos por Vaga",
        description="Razao entre inscritos e vagas ofertadas.",
        tab="Matriculas",
        row=1,
        col=18,
        size_x=6,
        size_y=4,
        sql=f"""SELECT
  ROUND(COALESCE(SUM(inscritos), 0) / NULLIF(COALESCE(SUM(vagas_ofertadas), 0), 0), 2) AS inscritos_por_vaga
FROM {MATRICULAS_SOURCE}
{where_clause(MATRICULAS_FILTERS)}""",
        display="scalar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Matriculas por Situacao",
        description="Distribuicao das matriculas por situacao.",
        tab="Matriculas",
        row=5,
        col=0,
        size_x=8,
        size_y=6,
        sql=f"""SELECT situacao_matricula, SUM(matriculas) AS matriculas
FROM {MATRICULAS_SOURCE}
{where_clause(MATRICULAS_FILTERS)}
GROUP BY situacao_matricula
ORDER BY matriculas DESC NULLS LAST""",
        display="bar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={"graph.dimensions": ["situacao_matricula"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        name="PNP 2024 - Matriculas por Sexo",
        description="Perfil por sexo.",
        tab="Matriculas",
        row=5,
        col=8,
        size_x=8,
        size_y=6,
        sql=f"""SELECT sexo, SUM(matriculas) AS matriculas
FROM {MATRICULAS_SOURCE}
{where_clause(MATRICULAS_FILTERS)}
GROUP BY sexo
ORDER BY matriculas DESC NULLS LAST""",
        display="bar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={"graph.dimensions": ["sexo"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        name="PNP 2024 - Matriculas por Tipo de Curso",
        description="Distribuicao por tipo de curso.",
        tab="Matriculas",
        row=5,
        col=16,
        size_x=8,
        size_y=6,
        sql=f"""SELECT tipo_curso, SUM(matriculas) AS matriculas
FROM {MATRICULAS_SOURCE}
{where_clause(MATRICULAS_FILTERS)}
GROUP BY tipo_curso
ORDER BY matriculas DESC NULLS LAST""",
        display="bar",
        filters=MATRICULAS_FILTERS,
        visualization_settings={"graph.dimensions": ["tipo_curso"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        name="PNP 2024 - Oferta por Curso",
        description="Oferta, inscritos e matriculas por curso.",
        tab="Matriculas",
        row=11,
        col=0,
        size_x=24,
        size_y=7,
        sql=f"""SELECT
  nome_curso,
  tipo_curso,
  modalidade_ensino,
  tipo_oferta,
  turno,
  SUM(matriculas) AS matriculas,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(inscritos) AS inscritos
FROM {MATRICULAS_SOURCE}
{where_clause(MATRICULAS_FILTERS)}
GROUP BY nome_curso, tipo_curso, modalidade_ensino, tipo_oferta, turno
ORDER BY matriculas DESC NULLS LAST
LIMIT 20""",
        display="table",
        filters=MATRICULAS_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Registros de Eficiencia",
        description="Total de registros de eficiencia academica.",
        tab="Eficiencia Academica",
        row=1,
        col=0,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(registros), 0) AS registros_eficiencia FROM {EFICIENCIA_SOURCE}\n{where_clause(EFICIENCIA_FILTERS)}",
        display="scalar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Concluintes",
        description="Total de concluintes no recorte.",
        tab="Eficiencia Academica",
        row=1,
        col=6,
        size_x=6,
        size_y=4,
        sql=f"""SELECT COALESCE(SUM(registros), 0) AS concluintes
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
AND categoria_situacao = 'Concluintes'""",
        display="scalar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Evadidos",
        description="Total de evadidos no recorte.",
        tab="Eficiencia Academica",
        row=1,
        col=12,
        size_x=6,
        size_y=4,
        sql=f"""SELECT COALESCE(SUM(registros), 0) AS evadidos
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
AND categoria_situacao = 'Evadidos'""",
        display="scalar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Em Curso",
        description="Total de registros em curso.",
        tab="Eficiencia Academica",
        row=1,
        col=18,
        size_x=6,
        size_y=4,
        sql=f"""SELECT COALESCE(SUM(registros), 0) AS em_curso
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
AND categoria_situacao = 'Em curso'""",
        display="scalar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Eficiencia por Categoria",
        description="Distribuicao por categoria.",
        tab="Eficiencia Academica",
        row=5,
        col=0,
        size_x=12,
        size_y=6,
        sql=f"""SELECT categoria_situacao, SUM(registros) AS registros
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
GROUP BY categoria_situacao
ORDER BY registros DESC NULLS LAST""",
        display="bar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={"graph.dimensions": ["categoria_situacao"], "graph.metrics": ["registros"]},
    ),
    CardDef(
        name="PNP 2024 - Eficiencia por UF",
        description="Distribuicao territorial.",
        tab="Eficiencia Academica",
        row=5,
        col=12,
        size_x=12,
        size_y=6,
        sql=f"""SELECT uf, SUM(registros) AS registros
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
GROUP BY uf
ORDER BY registros DESC NULLS LAST""",
        display="bar",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={"graph.dimensions": ["uf"], "graph.metrics": ["registros"]},
    ),
    CardDef(
        name="PNP 2024 - Situacao Academica por Instituicao",
        description="Detalhamento por instituicao e categoria.",
        tab="Eficiencia Academica",
        row=11,
        col=0,
        size_x=24,
        size_y=7,
        sql=f"""SELECT instituicao, categoria_situacao, SUM(registros) AS registros
FROM {EFICIENCIA_SOURCE}
{where_clause(EFICIENCIA_FILTERS)}
GROUP BY instituicao, categoria_situacao
ORDER BY registros DESC NULLS LAST
LIMIT 25""",
        display="table",
        filters=EFICIENCIA_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Total de Servidores",
        description="Total de servidores no recorte.",
        tab="Servidores",
        row=1,
        col=0,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(servidores), 0) AS servidores FROM {SERVIDORES_SOURCE}\n{where_clause(SERVIDORES_FILTERS)}",
        display="scalar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Instituicoes com Servidores",
        description="Quantidade de instituicoes no recorte.",
        tab="Servidores",
        row=1,
        col=6,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT instituicao) AS instituicoes FROM {SERVIDORES_SOURCE}\n{where_clause(SERVIDORES_FILTERS)}",
        display="scalar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Titulacoes Distintas",
        description="Quantidade de titulacoes distintas.",
        tab="Servidores",
        row=1,
        col=12,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT titulacao) AS titulacoes_distintas FROM {SERVIDORES_SOURCE}\n{where_clause(SERVIDORES_FILTERS)}",
        display="scalar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Vinculos Distintos",
        description="Quantidade de vinculos distintos.",
        tab="Servidores",
        row=1,
        col=18,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT vinculo_carreira) AS vinculos_distintos FROM {SERVIDORES_SOURCE}\n{where_clause(SERVIDORES_FILTERS)}",
        display="scalar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Servidores por Titulacao",
        description="Distribuicao por titulacao.",
        tab="Servidores",
        row=5,
        col=0,
        size_x=8,
        size_y=6,
        sql=f"""SELECT titulacao, SUM(servidores) AS servidores
FROM {SERVIDORES_SOURCE}
{where_clause(SERVIDORES_FILTERS)}
GROUP BY titulacao
ORDER BY servidores DESC NULLS LAST""",
        display="bar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={"graph.dimensions": ["titulacao"], "graph.metrics": ["servidores"]},
    ),
    CardDef(
        name="PNP 2024 - Servidores por Jornada",
        description="Distribuicao por jornada.",
        tab="Servidores",
        row=5,
        col=8,
        size_x=8,
        size_y=6,
        sql=f"""SELECT jornada_trabalho, SUM(servidores) AS servidores
FROM {SERVIDORES_SOURCE}
{where_clause(SERVIDORES_FILTERS)}
GROUP BY jornada_trabalho
ORDER BY servidores DESC NULLS LAST""",
        display="bar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={"graph.dimensions": ["jornada_trabalho"], "graph.metrics": ["servidores"]},
    ),
    CardDef(
        name="PNP 2024 - Servidores por Vinculo",
        description="Distribuicao por vinculo de carreira.",
        tab="Servidores",
        row=5,
        col=16,
        size_x=8,
        size_y=6,
        sql=f"""SELECT vinculo_carreira, SUM(servidores) AS servidores
FROM {SERVIDORES_SOURCE}
{where_clause(SERVIDORES_FILTERS)}
GROUP BY vinculo_carreira
ORDER BY servidores DESC NULLS LAST""",
        display="bar",
        filters=SERVIDORES_FILTERS,
        visualization_settings={"graph.dimensions": ["vinculo_carreira"], "graph.metrics": ["servidores"]},
    ),
    CardDef(
        name="PNP 2024 - Servidores por Instituicao",
        description="Ranking institucional.",
        tab="Servidores",
        row=11,
        col=0,
        size_x=24,
        size_y=7,
        sql=f"""SELECT instituicao, SUM(servidores) AS servidores
FROM {SERVIDORES_SOURCE}
{where_clause(SERVIDORES_FILTERS)}
GROUP BY instituicao
ORDER BY servidores DESC NULLS LAST
LIMIT 20""",
        display="table",
        filters=SERVIDORES_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Liquidacoes Totais",
        description="Total liquidado no recorte.",
        tab="Financeiro",
        row=1,
        col=0,
        size_x=6,
        size_y=4,
        sql=f"SELECT COALESCE(SUM(liquidacoes_totais), 0) AS liquidacoes_totais FROM {FINANCEIRO_SOURCE}\n{where_clause(FINANCEIRO_FILTERS)}",
        display="scalar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI UOs Distintas",
        description="Quantidade de UOs distintas.",
        tab="Financeiro",
        row=1,
        col=6,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT nome_uo) AS uos_distintas FROM {FINANCEIRO_SOURCE}\n{where_clause(FINANCEIRO_FILTERS)}",
        display="scalar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Acoes Distintas",
        description="Quantidade de acoes distintas.",
        tab="Financeiro",
        row=1,
        col=12,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT cod_acao) AS acoes_distintas FROM {FINANCEIRO_SOURCE}\n{where_clause(FINANCEIRO_FILTERS)}",
        display="scalar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - KPI Grupos de Despesa Distintos",
        description="Quantidade de grupos de despesa distintos.",
        tab="Financeiro",
        row=1,
        col=18,
        size_x=6,
        size_y=4,
        sql=f"SELECT COUNT(DISTINCT grupo_despesa) AS grupos_despesa_distintos FROM {FINANCEIRO_SOURCE}\n{where_clause(FINANCEIRO_FILTERS)}",
        display="scalar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Liquidacoes por Grupo de Despesa",
        description="Distribuicao por grupo de despesa.",
        tab="Financeiro",
        row=5,
        col=0,
        size_x=10,
        size_y=6,
        sql=f"""SELECT grupo_despesa, SUM(liquidacoes_totais) AS liquidacoes_totais
FROM {FINANCEIRO_SOURCE}
{where_clause(FINANCEIRO_FILTERS)}
GROUP BY grupo_despesa
ORDER BY liquidacoes_totais DESC NULLS LAST""",
        display="bar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={"graph.dimensions": ["grupo_despesa"], "graph.metrics": ["liquidacoes_totais"]},
    ),
    CardDef(
        name="PNP 2024 - Top UOs por Liquidacoes",
        description="Ranking de UOs por liquidacoes.",
        tab="Financeiro",
        row=5,
        col=10,
        size_x=14,
        size_y=6,
        sql=f"""SELECT nome_uo, SUM(liquidacoes_totais) AS liquidacoes_totais
FROM {FINANCEIRO_SOURCE}
{where_clause(FINANCEIRO_FILTERS)}
GROUP BY nome_uo
ORDER BY liquidacoes_totais DESC NULLS LAST
LIMIT 15""",
        display="bar",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={"graph.dimensions": ["nome_uo"], "graph.metrics": ["liquidacoes_totais"]},
    ),
    CardDef(
        name="PNP 2024 - Execucao por Acao",
        description="Detalhamento financeiro por acao.",
        tab="Financeiro",
        row=11,
        col=0,
        size_x=24,
        size_y=7,
        sql=f"""SELECT
  nome_uo,
  cod_acao,
  nome_acao,
  grupo_despesa,
  SUM(liquidacoes_totais) AS liquidacoes_totais
FROM {FINANCEIRO_SOURCE}
{where_clause(FINANCEIRO_FILTERS)}
GROUP BY nome_uo, cod_acao, nome_acao, grupo_despesa
ORDER BY liquidacoes_totais DESC NULLS LAST
LIMIT 25""",
        display="table",
        filters=FINANCEIRO_FILTERS,
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Qualidade por Tipo de Microdado",
        description="Cobertura basica dos microdados.",
        tab="Qualidade e Ingestao",
        row=1,
        col=0,
        size_x=14,
        size_y=8,
        sql=f"""SELECT
  tipo_microdados,
  registros,
  registros_sem_instituicao,
  registros_sem_uf,
  registros_sem_sexo,
  registros_sem_cor_raca,
  registros_sem_renda_familiar,
  registros_sem_faixa_etaria,
  registros_financeiros_sem_valor,
  registros_servidores_sem_quantidade,
  pct_sem_instituicao,
  pct_sem_uf
FROM {QUALIDADE_SOURCE}
ORDER BY tipo_microdados""",
        display="table",
        filters=(),
        visualization_settings={},
    ),
    CardDef(
        name="PNP 2024 - Execucoes de Ingestao",
        description="Trilha operacional das execucoes da carga.",
        tab="Qualidade e Ingestao",
        row=1,
        col=14,
        size_x=10,
        size_y=8,
        sql=f"""SELECT
  run_id,
  status,
  endpoint_key,
  loaded_count,
  registros_raw,
  downloads_total,
  manifests_total,
  started_at,
  finished_at
FROM {INGESTAO_SOURCE}
ORDER BY started_at DESC NULLS LAST
LIMIT 20""",
        display="table",
        filters=(),
        visualization_settings={},
    ),
]


def build_virtual_dashcard(card: VirtualCardDef, tab_id: int, dashcard_id: int) -> dict:
    return {
        "id": dashcard_id,
        "card_id": None,
        "dashboard_tab_id": tab_id,
        "row": card.row,
        "col": card.col,
        "size_x": card.size_x,
        "size_y": card.size_y,
        "parameter_mappings": [],
        "visualization_settings": {
            "dashcard.background": False,
            "text": card.text,
            "virtual_card": {
                "archived": False,
                "dataset_query": {},
                "display": "text",
                "visualization_settings": {},
            },
        },
    }


def build_real_dashcard(card: CardDef, tab_id: int, dashcard_id: int, card_id: int) -> dict:
    return {
        "id": dashcard_id,
        "card_id": card_id,
        "dashboard_tab_id": tab_id,
        "row": card.row,
        "col": card.col,
        "size_x": card.size_x,
        "size_y": card.size_y,
        "parameter_mappings": card.parameter_mappings(),
    }


def main() -> int:
    cleanup_previous_pnp_cards()
    dashboard_id = ensure_dashboard()

    next_tab_id = -1
    tabs_payload = []
    tab_ids: dict[str, int] = {}
    for position, tab_name in enumerate(TAB_LAYOUT):
        tab_ids[tab_name] = next_tab_id
        tabs_payload.append({"id": next_tab_id, "name": tab_name, "position": position})
        next_tab_id -= 1

    next_dashcard_id = -1
    dashcards = []

    for virtual in VIRTUALS:
        dashcards.append(build_virtual_dashcard(virtual, tab_ids[virtual.tab], next_dashcard_id))
        next_dashcard_id -= 1

    created_cards = []
    for card in CARDS:
        card_id = create_card(card)
        created_cards.append(card_id)
        dashcards.append(build_real_dashcard(card, tab_ids[card.tab], next_dashcard_id, card_id))
        next_dashcard_id -= 1

    update_dashboard(dashboard_id, tabs_payload, dashcards)
    dashboard = api("GET", f"/dashboard/{dashboard_id}")

    print(
        json.dumps(
            {
                "dashboard_id": dashboard_id,
                "tabs_total": len(dashboard.get("tabs", [])),
                "dashcards_total": len(dashboard.get("dashcards", [])),
                "cards_created": len(created_cards),
                "filters_total": len(dashboard.get("parameters", [])),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
