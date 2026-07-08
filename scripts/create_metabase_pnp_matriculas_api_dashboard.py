from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import md5
from typing import Any


API_BASE = os.getenv("METABASE_API_URL", "http://localhost:3001/api").rstrip("/")
API_KEY = os.getenv("METABASE_API_KEY", "").strip()
SESSION_TOKEN = os.getenv("METABASE_SESSION_TOKEN", "").strip()
ADMIN_EMAIL = os.getenv("METABASE_ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.getenv("METABASE_ADMIN_PASSWORD", "")
DATABASE_ID = int(os.getenv("METABASE_DATABASE_ID", "2"))
SOURCE_SCHEMA = os.getenv("PNP_SOURCE_SCHEMA", "curated")
SOURCE_TABLE = os.getenv("PNP_SOURCE_TABLE", "mv_pnp_dashboard_matriculas")
DASHBOARD_NAME = os.getenv("METABASE_DASHBOARD_NAME", "PNP - Painel de Matriculas")
DASHBOARD_DESCRIPTION = (
    "Painel de exemplo com recorte exclusivo da fonte de matriculas da PNP, "
    "organizado por visao geral, territorio, perfil discente, cursos e situacao."
)


def _request(method: str, path: str, payload: dict[str, Any] | list[Any] | None = None) -> dict[str, Any] | list[Any]:
    data = None
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    elif SESSION_TOKEN:
        headers["X-Metabase-Session"] = SESSION_TOKEN
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: {exc.code} {body}") from exc


def _login() -> str:
    if API_KEY or SESSION_TOKEN:
        return SESSION_TOKEN
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise SystemExit("Set METABASE_API_KEY, METABASE_SESSION_TOKEN, or METABASE_ADMIN_EMAIL/METABASE_ADMIN_PASSWORD")

    data = json.dumps({"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/session",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Metabase login failed: {exc.code} {body}") from exc
    token = payload.get("id")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Metabase login response did not include a session id")
    return token


def api(method: str, path: str, payload: dict[str, Any] | list[Any] | None = None) -> dict[str, Any] | list[Any]:
    global SESSION_TOKEN
    if not API_KEY and not SESSION_TOKEN:
        SESSION_TOKEN = _login()
    return _request(method, path, payload)


def stable_id(seed: str) -> str:
    return md5(seed.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class FilterDef:
    slug: str
    label: str
    widget_type: str


FILTERS = {
    item.slug: item
    for item in (
        FilterDef("ano", "Ano", "number/="),
        FilterDef("instituicao", "Instituicao", "string/="),
        FilterDef("regiao", "Regiao", "string/="),
        FilterDef("uf", "UF", "string/="),
        FilterDef("municipio", "Municipio", "string/contains"),
        FilterDef("sexo", "Sexo", "string/="),
        FilterDef("cor_raca", "Cor / Raca", "string/="),
        FilterDef("renda_familiar", "Renda Familiar", "string/="),
        FilterDef("faixa_etaria", "Faixa Etaria", "string/="),
        FilterDef("situacao_matricula", "Situacao de Matricula", "string/="),
        FilterDef("modalidade_ensino", "Modalidade de Ensino", "string/="),
        FilterDef("tipo_curso", "Tipo de Curso", "string/="),
        FilterDef("tipo_oferta", "Tipo de Oferta", "string/="),
        FilterDef("turno", "Turno", "string/="),
        FilterDef("nome_curso", "Nome do Curso", "string/contains"),
    )
}

ORG_FILTERS = ("ano", "instituicao", "regiao", "uf", "municipio")
PROFILE_FILTERS = ORG_FILTERS + ("sexo", "cor_raca", "faixa_etaria", "renda_familiar")
COURSE_FILTERS = ORG_FILTERS + ("modalidade_ensino", "tipo_curso", "tipo_oferta", "turno", "nome_curso")
STATUS_FILTERS = ORG_FILTERS + ("situacao_matricula", "tipo_curso", "modalidade_ensino")


def where_clause(filters: tuple[str, ...]) -> str:
    lines = ["WHERE 1=1"]
    for slug in filters:
        lines.append(f"[[ AND {{{{{slug}}}}} ]]")
    return "\n".join(lines)


SOURCE_FQN = f"{SOURCE_SCHEMA}.{SOURCE_TABLE}"


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
    visualization_settings: dict[str, Any]

    def template_tags(self, field_map: dict[str, int]) -> dict[str, Any]:
        tags = {}
        for slug in self.filters:
            spec = FILTERS[slug]
            tag: dict[str, Any] = {
                "id": stable_id(f"{self.name}:{slug}"),
                "name": slug,
                "display-name": spec.label,
                "type": "dimension",
                "widget-type": spec.widget_type,
                "required": False,
                "dimension": ["field", field_map[slug], None],
            }
            if spec.widget_type == "string/contains":
                tag["options"] = {"case-sensitive": False}
            tags[slug] = tag
        return tags

    def parameter_mappings(self) -> list[dict[str, Any]]:
        return [
            {
                "parameter_id": f"p_{slug}",
                "target": ["dimension", ["template-tag", slug], {"stage-number": 0}],
            }
            for slug in self.filters
        ]


@dataclass(frozen=True)
class TextDef:
    tab: str
    text: str
    row: int
    col: int
    size_x: int
    size_y: int


TAB_LAYOUT = ["Visao Geral", "Organizacao e Territorio", "Perfil Discente", "Cursos e Oferta", "Situacao da Matricula"]

TEXT_CARDS = [
    TextDef("Visao Geral", "Indicadores gerais de oferta, procura e matriculas ao longo dos anos.", 0, 0, 24, 1),
    TextDef("Organizacao e Territorio", "Recortes por instituicao, regiao, UF e municipio.", 0, 0, 24, 1),
    TextDef("Perfil Discente", "Distribuicao das matriculas por atributos declarados dos estudantes.", 0, 0, 24, 1),
    TextDef("Cursos e Oferta", "Organizacao da oferta por curso, modalidade, tipo de curso, turno e vagas.", 0, 0, 24, 1),
    TextDef("Situacao da Matricula", "Situacao das matriculas por territorio, instituicao e tipo de curso.", 0, 0, 24, 1),
]

CARDS = [
    CardDef(
        "PNP - Matriculas - KPI Matriculas",
        "Total de matriculas no recorte.",
        "Visao Geral",
        1,
        0,
        6,
        4,
        f"SELECT COALESCE(SUM(matriculas), 0) AS matriculas FROM {SOURCE_FQN}\n{where_clause(ORG_FILTERS)}",
        "scalar",
        ORG_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - KPI Inscritos",
        "Total de inscritos no recorte.",
        "Visao Geral",
        1,
        6,
        6,
        4,
        f"SELECT COALESCE(SUM(inscritos), 0) AS inscritos FROM {SOURCE_FQN}\n{where_clause(ORG_FILTERS)}",
        "scalar",
        ORG_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - KPI Vagas",
        "Total de vagas ofertadas no recorte.",
        "Visao Geral",
        1,
        12,
        6,
        4,
        f"SELECT COALESCE(SUM(vagas_ofertadas), 0) AS vagas_ofertadas FROM {SOURCE_FQN}\n{where_clause(ORG_FILTERS)}",
        "scalar",
        ORG_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - KPI Inscritos por Vaga",
        "Razao entre inscritos e vagas ofertadas.",
        "Visao Geral",
        1,
        18,
        6,
        4,
        f"""SELECT ROUND(COALESCE(SUM(inscritos), 0) / NULLIF(COALESCE(SUM(vagas_ofertadas), 0), 0), 2) AS inscritos_por_vaga
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}""",
        "scalar",
        ORG_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - Serie Historica",
        "Evolucao anual de matriculas, inscritos e vagas.",
        "Visao Geral",
        5,
        0,
        24,
        8,
        f"""SELECT
  ano,
  SUM(matriculas) AS matriculas,
  SUM(inscritos) AS inscritos,
  SUM(vagas_ofertadas) AS vagas_ofertadas
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}
GROUP BY ano
ORDER BY ano""",
        "line",
        ORG_FILTERS,
        {"graph.dimensions": ["ano"], "graph.metrics": ["matriculas", "inscritos", "vagas_ofertadas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Instituicao",
        "Ranking de instituicoes por matriculas.",
        "Organizacao e Territorio",
        1,
        0,
        12,
        7,
        f"""SELECT instituicao, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}
GROUP BY instituicao
ORDER BY matriculas DESC NULLS LAST
LIMIT 20""",
        "bar",
        ORG_FILTERS,
        {"graph.dimensions": ["instituicao"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Regiao",
        "Distribuicao de matriculas por regiao.",
        "Organizacao e Territorio",
        1,
        12,
        6,
        7,
        f"""SELECT regiao, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}
GROUP BY regiao
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        ORG_FILTERS,
        {"graph.dimensions": ["regiao"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por UF",
        "Distribuicao de matriculas por UF.",
        "Organizacao e Territorio",
        1,
        18,
        6,
        7,
        f"""SELECT uf, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}
GROUP BY uf
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        ORG_FILTERS,
        {"graph.dimensions": ["uf"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Tabela Institucional",
        "Oferta, procura e matriculas por instituicao.",
        "Organizacao e Territorio",
        8,
        0,
        24,
        8,
        f"""SELECT
  instituicao,
  regiao,
  uf,
  SUM(matriculas) AS matriculas,
  SUM(inscritos) AS inscritos,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  ROUND(COALESCE(SUM(inscritos), 0) / NULLIF(COALESCE(SUM(vagas_ofertadas), 0), 0), 2) AS inscritos_por_vaga
FROM {SOURCE_FQN}
{where_clause(ORG_FILTERS)}
GROUP BY instituicao, regiao, uf
ORDER BY matriculas DESC NULLS LAST
LIMIT 50""",
        "table",
        ORG_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - Por Sexo",
        "Distribuicao de matriculas por sexo.",
        "Perfil Discente",
        1,
        0,
        6,
        7,
        f"""SELECT sexo, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(PROFILE_FILTERS)}
GROUP BY sexo
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        PROFILE_FILTERS,
        {"graph.dimensions": ["sexo"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Cor Raca",
        "Distribuicao de matriculas por cor/raca.",
        "Perfil Discente",
        1,
        6,
        6,
        7,
        f"""SELECT cor_raca, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(PROFILE_FILTERS)}
GROUP BY cor_raca
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        PROFILE_FILTERS,
        {"graph.dimensions": ["cor_raca"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Faixa Etaria",
        "Distribuicao de matriculas por faixa etaria.",
        "Perfil Discente",
        1,
        12,
        6,
        7,
        f"""SELECT faixa_etaria, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(PROFILE_FILTERS)}
GROUP BY faixa_etaria
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        PROFILE_FILTERS,
        {"graph.dimensions": ["faixa_etaria"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Renda Familiar",
        "Distribuicao de matriculas por renda familiar.",
        "Perfil Discente",
        1,
        18,
        6,
        7,
        f"""SELECT renda_familiar, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(PROFILE_FILTERS)}
GROUP BY renda_familiar
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        PROFILE_FILTERS,
        {"graph.dimensions": ["renda_familiar"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Tipo de Curso",
        "Matriculas por tipo de curso.",
        "Cursos e Oferta",
        1,
        0,
        8,
        7,
        f"""SELECT tipo_curso, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(COURSE_FILTERS)}
GROUP BY tipo_curso
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        COURSE_FILTERS,
        {"graph.dimensions": ["tipo_curso"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Modalidade",
        "Matriculas por modalidade de ensino.",
        "Cursos e Oferta",
        1,
        8,
        8,
        7,
        f"""SELECT modalidade_ensino, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(COURSE_FILTERS)}
GROUP BY modalidade_ensino
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        COURSE_FILTERS,
        {"graph.dimensions": ["modalidade_ensino"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Por Turno",
        "Matriculas por turno.",
        "Cursos e Oferta",
        1,
        16,
        8,
        7,
        f"""SELECT turno, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(COURSE_FILTERS)}
GROUP BY turno
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        COURSE_FILTERS,
        {"graph.dimensions": ["turno"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Top Cursos",
        "Oferta, procura e matriculas por curso.",
        "Cursos e Oferta",
        8,
        0,
        24,
        8,
        f"""SELECT
  nome_curso,
  tipo_curso,
  modalidade_ensino,
  tipo_oferta,
  turno,
  SUM(matriculas) AS matriculas,
  SUM(inscritos) AS inscritos,
  SUM(vagas_ofertadas) AS vagas_ofertadas
FROM {SOURCE_FQN}
{where_clause(COURSE_FILTERS)}
GROUP BY nome_curso, tipo_curso, modalidade_ensino, tipo_oferta, turno
ORDER BY matriculas DESC NULLS LAST
LIMIT 50""",
        "table",
        COURSE_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - Por Situacao",
        "Matriculas por situacao.",
        "Situacao da Matricula",
        1,
        0,
        10,
        7,
        f"""SELECT situacao_matricula, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(STATUS_FILTERS)}
GROUP BY situacao_matricula
ORDER BY matriculas DESC NULLS LAST""",
        "bar",
        STATUS_FILTERS,
        {"graph.dimensions": ["situacao_matricula"], "graph.metrics": ["matriculas"]},
    ),
    CardDef(
        "PNP - Matriculas - Situacao por Tipo de Curso",
        "Matriculas por situacao e tipo de curso.",
        "Situacao da Matricula",
        1,
        10,
        14,
        7,
        f"""SELECT tipo_curso, situacao_matricula, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(STATUS_FILTERS)}
GROUP BY tipo_curso, situacao_matricula
ORDER BY matriculas DESC NULLS LAST
LIMIT 30""",
        "table",
        STATUS_FILTERS,
        {},
    ),
    CardDef(
        "PNP - Matriculas - Situacao por Instituicao",
        "Situacao das matriculas por instituicao.",
        "Situacao da Matricula",
        8,
        0,
        24,
        8,
        f"""SELECT instituicao, situacao_matricula, SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{where_clause(STATUS_FILTERS)}
GROUP BY instituicao, situacao_matricula
ORDER BY matriculas DESC NULLS LAST
LIMIT 50""",
        "table",
        STATUS_FILTERS,
        {},
    ),
]


def dashboard_parameters() -> list[dict[str, Any]]:
    return [
        {
            "id": f"p_{spec.slug}",
            "name": spec.label,
            "slug": spec.slug,
            "type": spec.widget_type,
            "sectionId": "number" if spec.widget_type.startswith("number") else "string",
        }
        for spec in FILTERS.values()
    ]


def find_dashboard_by_name(name: str) -> dict[str, Any] | None:
    dashboards = api("GET", "/dashboard")
    if not isinstance(dashboards, list):
        return None
    for dashboard in dashboards:
        if isinstance(dashboard, dict) and dashboard.get("name") == name and not dashboard.get("archived"):
            return dashboard
    return None


def list_cards() -> list[dict[str, Any]]:
    cards = api("GET", "/card")
    return cards if isinstance(cards, list) else []


def archive_previous_cards() -> None:
    for card in list_cards():
        if card.get("archived"):
            continue
        name = str(card.get("name") or "")
        if name.startswith("PNP - Matriculas -"):
            api("PUT", f"/card/{int(card['id'])}", {"archived": True})


def ensure_dashboard() -> int:
    existing = find_dashboard_by_name(DASHBOARD_NAME)
    payload = {
        "name": DASHBOARD_NAME,
        "description": DASHBOARD_DESCRIPTION,
        "width": "fixed",
        "auto_apply_filters": True,
        "parameters": dashboard_parameters(),
        "tabs": [],
        "dashcards": [],
    }
    if existing:
        dashboard_id = int(existing["id"])
        api("PUT", f"/dashboard/{dashboard_id}", payload)
        return dashboard_id
    created = api("POST", "/dashboard", {**payload, "collection_id": None})
    if not isinstance(created, dict) or "id" not in created:
        raise RuntimeError(f"Unexpected dashboard creation response: {created}")
    return int(created["id"])


def database_metadata() -> dict[str, Any]:
    metadata = api("GET", f"/database/{DATABASE_ID}/metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("Metabase database metadata response was not an object")
    return metadata


def source_field_map() -> dict[str, int]:
    tables = database_metadata().get("tables") or []
    source_table = None
    for table in tables:
        if not isinstance(table, dict):
            continue
        if table.get("schema") == SOURCE_SCHEMA and table.get("name") == SOURCE_TABLE:
            source_table = table
            break
    if not source_table:
        raise RuntimeError(f"Metabase table not found in metadata: {SOURCE_SCHEMA}.{SOURCE_TABLE}")
    fields = source_table.get("fields") or []
    field_map = {
        str(field["name"]): int(field["id"])
        for field in fields
        if isinstance(field, dict) and field.get("name") and field.get("id")
    }
    missing = sorted(slug for slug in FILTERS if slug not in field_map)
    if missing:
        raise RuntimeError(f"Metabase field ids missing for filters: {', '.join(missing)}")
    return field_map


def create_card(card: CardDef, field_map: dict[str, int]) -> int:
    created = api(
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
                    "template-tags": card.template_tags(field_map),
                },
            },
            "visualization_settings": card.visualization_settings,
        },
    )
    if not isinstance(created, dict) or "id" not in created:
        raise RuntimeError(f"Unexpected card creation response for {card.name}: {created}")
    return int(created["id"])


def build_text_dashcard(text_card: TextDef, tab_id: int, dashcard_id: int) -> dict[str, Any]:
    return {
        "id": dashcard_id,
        "card_id": None,
        "dashboard_tab_id": tab_id,
        "row": text_card.row,
        "col": text_card.col,
        "size_x": text_card.size_x,
        "size_y": text_card.size_y,
        "parameter_mappings": [],
        "visualization_settings": {
            "dashcard.background": False,
            "text": text_card.text,
            "virtual_card": {
                "archived": False,
                "dataset_query": {},
                "display": "text",
                "visualization_settings": {},
            },
        },
    }


def build_card_dashcard(card: CardDef, tab_id: int, dashcard_id: int, card_id: int) -> dict[str, Any]:
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


def update_dashboard(dashboard_id: int, tabs: list[dict[str, Any]], dashcards: list[dict[str, Any]]) -> None:
    api(
        "PUT",
        f"/dashboard/{dashboard_id}",
        {
            "name": DASHBOARD_NAME,
            "description": DASHBOARD_DESCRIPTION,
            "width": "fixed",
            "auto_apply_filters": True,
            "parameters": dashboard_parameters(),
            "tabs": tabs,
            "dashcards": dashcards,
        },
    )


def main() -> int:
    field_map = source_field_map()
    archive_previous_cards()
    dashboard_id = ensure_dashboard()

    tab_ids: dict[str, int] = {}
    tabs = []
    next_tab_id = -1
    for position, tab_name in enumerate(TAB_LAYOUT):
        tab_ids[tab_name] = next_tab_id
        tabs.append({"id": next_tab_id, "name": tab_name, "position": position})
        next_tab_id -= 1

    next_dashcard_id = -1
    dashcards = []
    for text_card in TEXT_CARDS:
        dashcards.append(build_text_dashcard(text_card, tab_ids[text_card.tab], next_dashcard_id))
        next_dashcard_id -= 1

    created_cards = []
    for card in CARDS:
        card_id = create_card(card, field_map)
        created_cards.append({"id": card_id, "name": card.name})
        dashcards.append(build_card_dashcard(card, tab_ids[card.tab], next_dashcard_id, card_id))
        next_dashcard_id -= 1

    update_dashboard(dashboard_id, tabs, dashcards)
    dashboard = api("GET", f"/dashboard/{dashboard_id}")
    result = {
        "dashboard_id": dashboard_id,
        "dashboard_name": DASHBOARD_NAME,
        "tabs_total": len(dashboard.get("tabs", [])) if isinstance(dashboard, dict) else 0,
        "dashcards_total": len(dashboard.get("dashcards", [])) if isinstance(dashboard, dict) else 0,
        "cards_created": len(created_cards),
        "filters_total": len(dashboard.get("parameters", [])) if isinstance(dashboard, dict) else 0,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
