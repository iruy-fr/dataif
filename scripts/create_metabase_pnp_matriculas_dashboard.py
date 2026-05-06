from __future__ import annotations

import hashlib
import json
import os
import random
import string
from dataclasses import dataclass

import psycopg2
from psycopg2.extras import RealDictCursor


APP_DB_HOST = os.getenv("METABASE_APP_DB_HOST", "localhost")
APP_DB_PORT = int(os.getenv("METABASE_APP_DB_PORT", "5433"))
APP_DB_NAME = os.getenv("METABASE_APP_DB_NAME", "metabaseapp")
APP_DB_USER = os.getenv("METABASE_APP_DB_USER", "postgres")
APP_DB_PASSWORD = os.getenv("METABASE_APP_DB_PASSWORD", "postgres")

TARGET_YEAR = int(os.getenv("PNP_TARGET_YEAR", "2024"))
DATABASE_ID = int(os.getenv("METABASE_DATABASE_ID", "2"))
SOURCE_SCHEMA = os.getenv("PNP_SOURCE_SCHEMA", "curated")
SOURCE_TABLE = os.getenv("PNP_SOURCE_TABLE", "mv_pnp_dashboard_matriculas")
SOURCE_TABLE_ID = int(os.getenv("METABASE_SOURCE_TABLE_ID", "35"))
COLLECTION_ID = int(os.getenv("METABASE_COLLECTION_ID", "5"))
CREATOR_ID = int(os.getenv("METABASE_CREATOR_ID", "1"))

DASHBOARD_NAME = os.getenv(
    "METABASE_DASHBOARD_NAME",
    f"PNP {TARGET_YEAR} - Painel de Matrículas",
)
DASHBOARD_DESCRIPTION = (
    f"Painel temático de matrículas da PNP {TARGET_YEAR}, com indicadores de oferta, procura "
    "e composição do corpo discente a partir da view curada de matrículas."
)

SOURCE_FQN = f"{SOURCE_SCHEMA}.{SOURCE_TABLE}"

FILTER_SPECS = [
    ("instituicao", "Instituição", "string/="),
    ("regiao", "Região", "string/="),
    ("uf", "UF", "string/="),
    ("municipio", "Município", "string/contains"),
    ("sexo", "Sexo", "string/="),
    ("cor_raca", "Cor / Raça", "string/="),
    ("renda_familiar", "Renda Familiar", "string/="),
    ("faixa_etaria", "Faixa Etária", "string/="),
    ("situacao_matricula", "Situação de Matrícula", "string/="),
    ("modalidade_ensino", "Modalidade de Ensino", "string/="),
    ("tipo_curso", "Tipo de Curso", "string/="),
    ("tipo_oferta", "Tipo de Oferta", "string/="),
    ("turno", "Turno", "string/="),
    ("nome_curso", "Nome do Curso", "string/contains"),
]

FILTER_SLUGS = tuple(slug for slug, _, _ in FILTER_SPECS)


def random_entity_id(size: int = 21) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(size))


def stable_id(seed: str) -> str:
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def fixed_year_where() -> str:
    parts = [f"WHERE ano = {TARGET_YEAR}"]
    for slug in FILTER_SLUGS:
        parts.append(f"[[ AND {{{{{slug}}}}} ]]")
    return "\n".join(parts)


@dataclass(frozen=True)
class CardDef:
    name: str
    description: str
    row: int
    col: int
    size_x: int
    size_y: int
    sql: str
    display: str
    visualization_settings: dict
    filters: tuple[str, ...] = FILTER_SLUGS


CARDS = [
    CardDef(
        name=f"PNP {TARGET_YEAR} - KPI Matriculas",
        description=f"Total de matrículas no ano de {TARGET_YEAR}.",
        row=0,
        col=0,
        size_x=6,
        size_y=4,
        sql=f"""
SELECT COALESCE(SUM(matriculas), 0) AS matriculas
FROM {SOURCE_FQN}
{fixed_year_where()}
""".strip(),
        display="scalar",
        visualization_settings={},
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - KPI Inscritos",
        description=f"Total de inscritos no ano de {TARGET_YEAR}.",
        row=0,
        col=6,
        size_x=6,
        size_y=4,
        sql=f"""
SELECT COALESCE(SUM(inscritos), 0) AS inscritos
FROM {SOURCE_FQN}
{fixed_year_where()}
""".strip(),
        display="scalar",
        visualization_settings={},
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - KPI Vagas Ofertadas",
        description=f"Total de vagas ofertadas no ano de {TARGET_YEAR}.",
        row=0,
        col=12,
        size_x=6,
        size_y=4,
        sql=f"""
SELECT COALESCE(SUM(vagas_ofertadas), 0) AS vagas_ofertadas
FROM {SOURCE_FQN}
{fixed_year_where()}
""".strip(),
        display="scalar",
        visualization_settings={},
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - KPI Relacao Inscritos por Vaga",
        description=f"Relação entre inscritos e vagas ofertadas no ano de {TARGET_YEAR}.",
        row=0,
        col=18,
        size_x=6,
        size_y=4,
        sql=f"""
SELECT ROUND(
  COALESCE(SUM(inscritos), 0) / NULLIF(COALESCE(SUM(vagas_ofertadas), 0), 0),
  2
) AS inscritos_por_vaga
FROM {SOURCE_FQN}
{fixed_year_where()}
""".strip(),
        display="scalar",
        visualization_settings={},
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - Matriculas por Situacao",
        description=f"Distribuição das matrículas por situação em {TARGET_YEAR}.",
        row=4,
        col=0,
        size_x=10,
        size_y=7,
        sql=f"""
SELECT
  situacao_matricula,
  SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{fixed_year_where()}
GROUP BY situacao_matricula
ORDER BY matriculas DESC NULLS LAST
""".strip(),
        display="bar",
        visualization_settings={
            "graph.dimensions": ["situacao_matricula"],
            "graph.metrics": ["matriculas"],
        },
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - Matriculas por Sexo",
        description=f"Distribuição das matrículas por sexo em {TARGET_YEAR}.",
        row=4,
        col=10,
        size_x=6,
        size_y=7,
        sql=f"""
SELECT
  sexo,
  SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{fixed_year_where()}
GROUP BY sexo
ORDER BY matriculas DESC NULLS LAST
""".strip(),
        display="pie",
        visualization_settings={
            "graph.dimensions": ["sexo"],
            "graph.metrics": ["matriculas"],
        },
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - Matriculas por Tipo de Curso",
        description=f"Distribuição das matrículas por tipo de curso em {TARGET_YEAR}.",
        row=4,
        col=16,
        size_x=8,
        size_y=7,
        sql=f"""
SELECT
  tipo_curso,
  SUM(matriculas) AS matriculas
FROM {SOURCE_FQN}
{fixed_year_where()}
GROUP BY tipo_curso
ORDER BY matriculas DESC NULLS LAST
""".strip(),
        display="row",
        visualization_settings={
            "graph.dimensions": ["tipo_curso"],
            "graph.metrics": ["matriculas"],
        },
    ),
    CardDef(
        name=f"PNP {TARGET_YEAR} - Oferta por Curso",
        description=f"Oferta, procura e matrículas por curso no ano de {TARGET_YEAR}.",
        row=11,
        col=0,
        size_x=24,
        size_y=8,
        sql=f"""
SELECT
  nome_curso,
  tipo_curso,
  modalidade_ensino,
  tipo_oferta,
  turno,
  SUM(vagas_ofertadas) AS vagas_ofertadas,
  SUM(inscritos) AS inscritos,
  SUM(matriculas) AS matriculas,
  ROUND(
    COALESCE(SUM(inscritos), 0) / NULLIF(COALESCE(SUM(vagas_ofertadas), 0), 0),
    2
  ) AS inscritos_por_vaga
FROM {SOURCE_FQN}
{fixed_year_where()}
GROUP BY nome_curso, tipo_curso, modalidade_ensino, tipo_oferta, turno
ORDER BY matriculas DESC NULLS LAST, inscritos DESC NULLS LAST
LIMIT 25
""".strip(),
        display="table",
        visualization_settings={},
    ),
]


class Publisher:
    def __init__(self) -> None:
        self.conn = psycopg2.connect(
            host=APP_DB_HOST,
            port=APP_DB_PORT,
            dbname=APP_DB_NAME,
            user=APP_DB_USER,
            password=APP_DB_PASSWORD,
        )
        self.conn.autocommit = False

    def close(self) -> None:
        self.conn.close()

    def fetchone(self, sql: str, params: tuple | None = None) -> dict | None:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, sql: str, params: tuple | None = None) -> list[dict]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def execute(self, sql: str, params: tuple | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def insert_returning_id(self, sql: str, params: tuple) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Insert did not return an id")
            return int(row[0])

    def field_map(self) -> dict[str, int]:
        rows = self.fetchall(
            """
            SELECT f.name, f.id
            FROM metabase_field f
            JOIN metabase_table t ON t.id = f.table_id
            WHERE t.id = %s
            ORDER BY f.id
            """,
            (SOURCE_TABLE_ID,),
        )
        return {row["name"]: int(row["id"]) for row in rows}

    def template_tags(self, card: CardDef, field_map: dict[str, int]) -> dict:
        tags = {}
        for slug in card.filters:
            label = next(label for current_slug, label, _ in FILTER_SPECS if current_slug == slug)
            widget = next(widget for current_slug, _, widget in FILTER_SPECS if current_slug == slug)
            tag = {
                "id": stable_id(f"{card.name}:{slug}"),
                "name": slug,
                "display-name": label,
                "type": "dimension",
                "widget-type": widget,
                "required": False,
                "dimension": ["field", field_map[slug], None],
            }
            if widget == "string/contains":
                tag["options"] = {"case-sensitive": False}
            tags[slug] = tag
        return tags

    def card_parameters(self, template_tags: dict) -> list[dict]:
        parameters = []
        for slug, tag in template_tags.items():
            parameter = {
                "id": tag["id"],
                "type": tag["widget-type"],
                "target": ["dimension", ["template-tag", slug]],
                "name": tag["display-name"],
                "slug": slug,
                "required": False,
                "isMultiSelect": True,
            }
            if "options" in tag:
                parameter["options"] = tag["options"]
            parameters.append(parameter)
        return parameters

    def dashboard_parameters(self) -> list[dict]:
        return [
            {
                "id": f"p_{slug}",
                "name": label,
                "slug": slug,
                "type": widget,
                "sectionId": "number" if widget.startswith("number") else "string",
            }
            for slug, label, widget in FILTER_SPECS
        ]

    def dashcard_parameter_mappings(self, card: CardDef) -> list[dict]:
        return [
            {
                "parameter_id": f"p_{slug}",
                "card_id": None,
                "target": ["dimension", ["template-tag", slug], {"stage-number": 0}],
            }
            for slug in card.filters
        ]

    def archive_existing_cards(self) -> None:
        self.execute(
            """
            UPDATE report_card
            SET archived = TRUE,
                archived_directly = TRUE,
                updated_at = NOW()
            WHERE name = ANY(%s)
            """,
            ([card.name for card in CARDS],),
        )

    def delete_existing_dashboard(self) -> None:
        dashboard = self.fetchone(
            "SELECT id FROM report_dashboard WHERE name = %s AND archived = FALSE ORDER BY id DESC LIMIT 1",
            (DASHBOARD_NAME,),
        )
        if not dashboard:
            return

        dashboard_id = int(dashboard["id"])
        self.execute("DELETE FROM report_dashboardcard WHERE dashboard_id = %s", (dashboard_id,))
        self.execute("DELETE FROM dashboard_tab WHERE dashboard_id = %s", (dashboard_id,))
        self.execute("DELETE FROM report_dashboard WHERE id = %s", (dashboard_id,))

    def create_dashboard(self) -> int:
        return self.insert_returning_id(
            """
            INSERT INTO report_dashboard (
                created_at,
                updated_at,
                name,
                description,
                creator_id,
                parameters,
                archived,
                collection_id,
                entity_id,
                auto_apply_filters,
                width,
                last_viewed_at
            ) VALUES (
                NOW(),
                NOW(),
                %s,
                %s,
                %s,
                %s,
                FALSE,
                %s,
                %s,
                TRUE,
                'fixed',
                NOW()
            )
            RETURNING id
            """,
            (
                DASHBOARD_NAME,
                DASHBOARD_DESCRIPTION,
                CREATOR_ID,
                json_text(self.dashboard_parameters()),
                COLLECTION_ID,
                random_entity_id(),
            ),
        )

    def create_card(self, card: CardDef, field_map: dict[str, int]) -> int:
        template_tags = self.template_tags(card, field_map)
        dataset_query = {
            "database": DATABASE_ID,
            "type": "native",
            "native": {
                "query": card.sql,
                "template-tags": template_tags,
            },
        }
        return self.insert_returning_id(
            """
            INSERT INTO report_card (
                created_at,
                updated_at,
                name,
                description,
                display,
                dataset_query,
                visualization_settings,
                creator_id,
                database_id,
                table_id,
                query_type,
                archived,
                collection_id,
                entity_id,
                parameters,
                parameter_mappings,
                last_used_at
            ) VALUES (
                NOW(),
                NOW(),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'native',
                FALSE,
                %s,
                %s,
                %s,
                '[]',
                NOW()
            )
            RETURNING id
            """,
            (
                card.name,
                card.description,
                card.display,
                json_text(dataset_query),
                json_text(card.visualization_settings),
                CREATOR_ID,
                DATABASE_ID,
                SOURCE_TABLE_ID,
                COLLECTION_ID,
                random_entity_id(),
                json_text(self.card_parameters(template_tags)),
            ),
        )

    def attach_card(self, dashboard_id: int, card_id: int, card: CardDef) -> int:
        parameter_mappings = self.dashcard_parameter_mappings(card)
        for mapping in parameter_mappings:
            mapping["card_id"] = card_id
        return self.insert_returning_id(
            """
            INSERT INTO report_dashboardcard (
                created_at,
                updated_at,
                size_x,
                size_y,
                row,
                col,
                card_id,
                dashboard_id,
                parameter_mappings,
                visualization_settings,
                entity_id
            ) VALUES (
                NOW(),
                NOW(),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                '{}',
                %s
            )
            RETURNING id
            """,
            (
                card.size_x,
                card.size_y,
                card.row,
                card.col,
                card_id,
                dashboard_id,
                json_text(parameter_mappings),
                random_entity_id(),
            ),
        )

    def publish(self) -> dict:
        field_map = self.field_map()
        missing = [slug for slug in FILTER_SLUGS if slug not in field_map]
        if missing:
            raise RuntimeError(f"Missing Metabase field ids for filters: {', '.join(missing)}")

        self.archive_existing_cards()
        self.delete_existing_dashboard()
        dashboard_id = self.create_dashboard()

        created = []
        for card in CARDS:
            card_id = self.create_card(card, field_map)
            dashcard_id = self.attach_card(dashboard_id, card_id, card)
            created.append({"card_id": card_id, "dashcard_id": dashcard_id, "name": card.name})

        self.conn.commit()
        return {
            "dashboard_id": dashboard_id,
            "dashboard_name": DASHBOARD_NAME,
            "cards_created": len(created),
            "collection_id": COLLECTION_ID,
        }


def main() -> int:
    publisher = Publisher()
    try:
        result = publisher.publish()
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        publisher.conn.rollback()
        raise
    finally:
        publisher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
