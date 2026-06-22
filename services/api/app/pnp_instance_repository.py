from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json, RealDictCursor, execute_values
from . import pnp_dag_provisioner

PNP_INTERNAL_CONNECTOR_ID = "nilo_pecanha"
PNP_POWERBI_GROUP_LABEL = "Microdados Publicos"
PNP_POWERBI_SOURCE_LABEL = "Catalogo publico de microdados via Power BI"

_CONNECTION_ENTITY = "connection"
_PIPELINE_ENTITY = "pipeline"
_PIPELINE_ENDPOINT_SOURCE = "pipeline_selection"


class PnpConnectionNotFoundError(LookupError):
    pass

_ENDPOINT_TABLE_CATALOG: tuple[dict[str, str | None], ...] = (
    {
        "endpoint_key": "matriculas",
        "endpoint_name": "Matrículas",
        "tipo_microdados": "Matrículas",
        "raw_table_schema": "raw",
        "raw_table_name": "pnp_matriculas_src",
        "staging_table_schema": "staging",
        "staging_table_name": "pnp_matriculas",
        "curated_relation_schema": "curated",
        "curated_relation_name": "vw_pnp_matriculas_perfil",
    },
    {
        "endpoint_key": "eficiencia_academica",
        "endpoint_name": "Eficiência Acadêmica",
        "tipo_microdados": "Eficiência Acadêmica",
        "raw_table_schema": "raw",
        "raw_table_name": "pnp_eficiencia_academica_src",
        "staging_table_schema": "staging",
        "staging_table_name": "pnp_eficiencia_academica",
        "curated_relation_schema": "curated",
        "curated_relation_name": "vw_pnp_eficiencia_situacao",
    },
    {
        "endpoint_key": "servidores",
        "endpoint_name": "Servidores",
        "tipo_microdados": "Servidores",
        "raw_table_schema": "raw",
        "raw_table_name": "pnp_servidores_src",
        "staging_table_schema": "staging",
        "staging_table_name": "pnp_servidores",
        "curated_relation_schema": "curated",
        "curated_relation_name": "vw_pnp_servidores_quadro",
    },
    {
        "endpoint_key": "financeiro",
        "endpoint_name": "Financeiro",
        "tipo_microdados": "Financeiro",
        "raw_table_schema": "raw",
        "raw_table_name": "pnp_financeiro_src",
        "staging_table_schema": "staging",
        "staging_table_name": "pnp_financeiro",
        "curated_relation_schema": "curated",
        "curated_relation_name": "vw_pnp_financeiro_execucao",
    },
)


def _connect(connect_factory: Callable[[], Any]):
    conn = connect_factory()
    if getattr(conn, "cursor_factory", None) is None and not isinstance(conn, psycopg2.extensions.connection):
        return conn
    return conn


def _normalize_selected_downloads(items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in items or []:
        if not isinstance(item, dict):
            continue
        ano_base = str(item.get("ano_base") or "").strip()
        tipo_microdados = str(item.get("tipo_microdados") or "").strip()
        microdados_url = str(item.get("microdados_url") or "").strip()
        if not ano_base or not tipo_microdados or not microdados_url:
            continue
        key = (ano_base, tipo_microdados, microdados_url)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "ano_base": ano_base,
                "tipo_microdados": tipo_microdados,
                "microdados_url": microdados_url,
            }
        )
    return normalized


def _build_connection_request_params(connection_key: str, connection_name: str) -> dict[str, Any]:
    return {
        "mode": "powerbi_microdados",
        "entity_type": _CONNECTION_ENTITY,
        "connection_key": connection_key,
        "connection_name": connection_name,
        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
        "source_path": "powerbi_microdados",
    }


def _build_pipeline_request_params(
    *,
    pipeline_id: str,
    instance_key: str,
    instance_name: str,
    connection_key: str,
    connection_name: str,
    selected_years: list[str],
    selected_microdados_types: list[str],
    selected_downloads: list[dict[str, str]],
    schedule: str | None,
) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "mode": "powerbi_microdados",
        "pipeline_id": pipeline_id,
        "entity_type": _PIPELINE_ENTITY,
        "pipeline_key": instance_key,
        "pipeline_name": instance_name,
        "connection_key": connection_key,
        "connection_name": connection_name,
        "instance_key": instance_key,
        "instance_name": instance_name,
        "selected_years": list(selected_years),
        "selected_microdados_types": list(selected_microdados_types),
        "selected_downloads": _normalize_selected_downloads(selected_downloads),
        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
        "source_path": "powerbi_microdados",
    }
    if schedule and schedule.strip():
        request_params["schedule"] = schedule.strip()
    return request_params


def _endpoint_table_ref(schema_name: str | None, relation_name: str | None) -> str | None:
    if not schema_name or not relation_name:
        return None
    return f"{schema_name}.{relation_name}"


def _ensure_endpoint_catalog(cur) -> None:
    execute_values(
        cur,
        """
        INSERT INTO raw.pnp_endpoint_tables (
          endpoint_key,
          endpoint_name,
          tipo_microdados,
          raw_table_schema,
          raw_table_name,
          staging_table_schema,
          staging_table_name,
          curated_relation_schema,
          curated_relation_name,
          metadata
        ) VALUES %s
        ON CONFLICT (endpoint_key) DO UPDATE
        SET
          endpoint_name = EXCLUDED.endpoint_name,
          tipo_microdados = EXCLUDED.tipo_microdados,
          raw_table_schema = EXCLUDED.raw_table_schema,
          raw_table_name = EXCLUDED.raw_table_name,
          staging_table_schema = EXCLUDED.staging_table_schema,
          staging_table_name = EXCLUDED.staging_table_name,
          curated_relation_schema = EXCLUDED.curated_relation_schema,
          curated_relation_name = EXCLUDED.curated_relation_name,
          is_active = TRUE,
          metadata = EXCLUDED.metadata,
          updated_at = NOW()
        """,
        [
            (
                item["endpoint_key"],
                item["endpoint_name"],
                item["tipo_microdados"],
                item["raw_table_schema"],
                item["raw_table_name"],
                item["staging_table_schema"],
                item["staging_table_name"],
                item["curated_relation_schema"],
                item["curated_relation_name"],
                Json({"domain_key": item["endpoint_key"]}),
            )
            for item in _ENDPOINT_TABLE_CATALOG
        ],
    )


def _sync_pipeline_endpoints(
    cur,
    *,
    pipeline_id: str,
    instance_key: str,
    connection_key: str | None,
    is_active: bool,
) -> None:
    _ensure_endpoint_catalog(cur)
    cur.execute(
        """
        WITH selected_types AS (
          SELECT DISTINCT tipo_microdados
          FROM raw.pnp_instance_selection
          WHERE instance_key = %s
            AND is_active = TRUE
        )
        INSERT INTO raw.pnp_pipeline_endpoints (
          pipeline_id,
          instance_key,
          connection_key,
          endpoint_key,
          selection_source,
          is_active,
          metadata
        )
        SELECT
          %s,
          %s,
          %s,
          et.endpoint_key,
          %s,
          %s,
          jsonb_build_object(
            'tipo_microdados', et.tipo_microdados,
            'raw_table', concat_ws('.', et.raw_table_schema, et.raw_table_name),
            'staging_table', CASE
              WHEN et.staging_table_name IS NULL THEN NULL
              ELSE concat_ws('.', et.staging_table_schema, et.staging_table_name)
            END
          )
        FROM selected_types st
        JOIN raw.pnp_endpoint_tables et
          ON et.tipo_microdados = st.tipo_microdados
        ON CONFLICT (instance_key, endpoint_key) DO UPDATE
        SET
          pipeline_id = EXCLUDED.pipeline_id,
          connection_key = EXCLUDED.connection_key,
          selection_source = EXCLUDED.selection_source,
          is_active = EXCLUDED.is_active,
          metadata = EXCLUDED.metadata,
          updated_at = NOW()
        """,
        (
            instance_key,
            pipeline_id,
            instance_key,
            connection_key,
            _PIPELINE_ENDPOINT_SOURCE,
            is_active,
        ),
    )
    cur.execute(
        """
        UPDATE raw.pnp_pipeline_endpoints
        SET
          connection_key = %s,
          is_active = FALSE,
          updated_at = NOW()
        WHERE instance_key = %s
          AND endpoint_key NOT IN (
            SELECT et.endpoint_key
            FROM raw.pnp_instance_selection s
            JOIN raw.pnp_endpoint_tables et
              ON et.tipo_microdados = s.tipo_microdados
            WHERE s.instance_key = %s
              AND s.is_active = TRUE
          )
        """,
        (connection_key, instance_key, instance_key),
    )


def _build_connection_row(row: dict[str, Any]) -> dict[str, Any]:
    request_params = _build_connection_request_params(
        connection_key=str(row["connection_key"]),
        connection_name=str(row["connection_name"]),
    )
    return {
        "id": None,
        "connector_id": PNP_INTERNAL_CONNECTOR_ID,
        "endpoint_key": f"{row['connection_key']}__connection",
        "description": f"{row['connection_name']} - conexão PNP",
        "page_url": row.get("page_url"),
        "api_endpoint_url": None,
        "csv_url": None,
        "dictionary_url": None,
        "request_params": request_params,
        "is_active": row.get("is_active"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "_raw_metadata": dict(row.get("metadata") or {}),
    }


def _group_instance_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for row in rows:
        instance_key = str(row["instance_key"])
        pipeline_id = str(row["pipeline_id"])
        instance = grouped.setdefault(
            instance_key,
            {
                "id": row.get("legacy_endpoint_id"),
                "connector_id": PNP_INTERNAL_CONNECTOR_ID,
                "endpoint_key": row.get("legacy_endpoint_key") or f"{instance_key}__powerbi_microdados",
                "description": f"{row['instance_name']} - {PNP_POWERBI_SOURCE_LABEL}",
                "page_url": row.get("page_url"),
                "api_endpoint_url": None,
                "csv_url": None,
                "dictionary_url": None,
                "request_params": {
                    "mode": "powerbi_microdados",
                    "pipeline_id": pipeline_id,
                    "entity_type": _PIPELINE_ENTITY,
                    "pipeline_key": instance_key,
                    "pipeline_name": row["instance_name"],
                    "connection_key": row.get("connection_key") or instance_key,
                    "connection_name": row.get("connection_name") or row["instance_name"],
                    "instance_key": instance_key,
                    "instance_name": row["instance_name"],
                    "selected_years": [],
                    "selected_microdados_types": [],
                    "selected_downloads": [],
                    "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
                    "selected_source_group": PNP_POWERBI_GROUP_LABEL,
                    "source_path": "powerbi_microdados",
                },
                "is_active": row.get("is_active"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "_raw_metadata": dict(row.get("metadata") or {}),
            },
        )
        if row.get("schedule"):
            instance["request_params"]["schedule"] = row["schedule"]
        instance["request_params"]["pipeline_id"] = pipeline_id
        if row.get("deleted_at"):
            instance["_raw_metadata"] = {
                **instance["_raw_metadata"],
                "deleted": True,
                "deleted_at": row["deleted_at"].isoformat(),
            }

        ano_base = row.get("ano_base")
        tipo_microdados = row.get("tipo_microdados")
        microdados_url = row.get("configured_microdados_url")

        if isinstance(ano_base, str) and ano_base.strip():
            years = instance["request_params"]["selected_years"]
            if ano_base not in years:
                years.append(ano_base)
        if isinstance(tipo_microdados, str) and tipo_microdados.strip():
            types = instance["request_params"]["selected_microdados_types"]
            if tipo_microdados not in types:
                types.append(tipo_microdados)
        if isinstance(microdados_url, str) and microdados_url.strip() and isinstance(ano_base, str) and isinstance(tipo_microdados, str):
            downloads = instance["request_params"]["selected_downloads"]
            candidate = {
                "ano_base": ano_base,
                "tipo_microdados": tipo_microdados,
                "microdados_url": microdados_url,
            }
            if candidate not in downloads:
                downloads.append(candidate)

    return list(grouped.values())


def _attach_pipeline_endpoint_catalog(
    connect_factory: Callable[[], Any],
    instances: list[dict[str, Any]],
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    if not instances:
        return instances

    instance_keys = [str(item["request_params"]["instance_key"]) for item in instances]
    active_filter = "" if include_deleted else "AND pe.is_active = TRUE AND et.is_active = TRUE"
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
              pe.instance_key,
              pe.connection_key,
              pe.endpoint_key,
              pe.selection_source,
              pe.is_active,
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
            WHERE pe.instance_key = ANY(%s)
              {active_filter}
            ORDER BY pe.instance_key, et.endpoint_name
            """,
            (instance_keys,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    rows_by_instance: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_instance.setdefault(str(row["instance_key"]), []).append(row)

    for instance in instances:
        request_params = instance.setdefault("request_params", {})
        endpoint_rows = rows_by_instance.get(str(request_params.get("instance_key") or ""), [])
        endpoint_tables = [
            {
                "endpoint_key": str(row["endpoint_key"]),
                "endpoint_name": str(row["endpoint_name"]),
                "tipo_microdados": str(row["tipo_microdados"]),
                "selection_source": row.get("selection_source"),
                "raw_table": _endpoint_table_ref(row.get("raw_table_schema"), row.get("raw_table_name")),
                "staging_table": _endpoint_table_ref(row.get("staging_table_schema"), row.get("staging_table_name")),
                "curated_relation": _endpoint_table_ref(
                    row.get("curated_relation_schema"),
                    row.get("curated_relation_name"),
                ),
                "metadata": {
                    **dict(row.get("endpoint_metadata") or {}),
                    **dict(row.get("pipeline_endpoint_metadata") or {}),
                },
            }
            for row in endpoint_rows
        ]
        request_params["selected_endpoints"] = [item["endpoint_key"] for item in endpoint_tables]
        request_params["endpoint_tables"] = endpoint_tables
    return instances


def _load_connection_rows(connect_factory: Callable[[], Any], *, include_deleted: bool = False) -> list[dict[str, Any]]:
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              connection_key,
              connection_name,
              page_url,
              is_active,
              metadata,
              created_at,
              updated_at
            FROM raw.pnp_connections
            ORDER BY connection_name, connection_key
            """
        )
        return [dict(row) for row in cur.fetchall()]


def _load_instance_source_rows(
    connect_factory: Callable[[], Any],
    *,
    instance_key: str | None = None,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    deleted_filter = "" if include_deleted else "AND i.deleted_at IS NULL"
    selection_filter = "" if include_deleted else "AND COALESCE(s.is_active, TRUE) = TRUE"
    params: list[Any] = []
    instance_filter = ""
    if instance_key is not None:
        instance_filter = "AND i.instance_key = %s"
        params.append(instance_key)

    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
              i.pipeline_id,
              i.instance_key,
              i.instance_name,
              i.connection_key,
              i.connection_name,
              i.page_url,
              i.schedule,
              i.is_active,
              i.legacy_mode,
              i.legacy_endpoint_id,
              i.legacy_endpoint_key,
              i.metadata,
              i.created_at,
              i.updated_at,
              i.deleted_at,
              s.selection_id,
              s.ano_base,
              s.tipo_microdados,
              s.configured_microdados_url,
              s.is_active AS selection_is_active,
              s.selection_rank
            FROM raw.pnp_instances i
            LEFT JOIN raw.pnp_instance_selection s
              ON s.instance_key = i.instance_key
             {selection_filter}
            WHERE 1 = 1
              {deleted_filter}
              {instance_filter}
            ORDER BY
              i.instance_name,
              i.instance_key,
              COALESCE(s.selection_rank, 2147483647),
              s.ano_base DESC NULLS LAST,
              s.tipo_microdados NULLS LAST
            """,
            tuple(params),
        )
        return [dict(row) for row in cur.fetchall()]


def load_all_rows(connect_factory: Callable[[], Any], *, include_deleted: bool = False) -> list[dict[str, Any]]:
    rows = [_build_connection_row(row) for row in _load_connection_rows(connect_factory, include_deleted=include_deleted)]
    rows.extend(
        _attach_pipeline_endpoint_catalog(
            connect_factory,
            _group_instance_records(_load_instance_source_rows(connect_factory, include_deleted=include_deleted)),
            include_deleted=include_deleted,
        )
    )
    return rows


def load_instance_rows(
    connect_factory: Callable[[], Any],
    instance_key: str,
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    rows = _attach_pipeline_endpoint_catalog(
        connect_factory,
        _group_instance_records(
            _load_instance_source_rows(
                connect_factory,
                instance_key=instance_key,
                include_deleted=include_deleted,
            )
        ),
        include_deleted=include_deleted,
    )
    if not rows:
        raise LookupError(instance_key)
    return rows


def create_connection(
    connect_factory: Callable[[], Any],
    *,
    connection_key: str,
    connection_name: str,
    page_url: str,
    is_active: bool,
) -> None:
    with _connect(connect_factory) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.pnp_connections (
              connection_key,
              connection_name,
              page_url,
              is_active,
              metadata
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                connection_key,
                connection_name,
                page_url,
                is_active,
                Json(
                    {
                        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
                        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
                        "source_path": "powerbi_microdados",
                    }
                ),
            ),
        )


def load_connection(
    connect_factory: Callable[[], Any],
    connection_key: str,
    *,
    include_deleted: bool = False,
) -> dict[str, Any]:
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        row = _load_connection_record(cur, connection_key, include_deleted=include_deleted)
    if not row:
        raise PnpConnectionNotFoundError(connection_key)
    return _build_connection_row(row)


def _load_connection_record(
    cur,
    connection_key: str,
    *,
    include_deleted: bool = False,
) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT
          connection_key,
          connection_name,
          page_url,
          is_active,
          metadata,
          created_at,
          updated_at
        FROM raw.pnp_connections
        WHERE connection_key = %s
        """,
        (connection_key,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def create_instance(
    connect_factory: Callable[[], Any],
    *,
    instance_key: str,
    instance_name: str,
    connection_key: str,
    selected_years: list[str],
    selected_microdados_types: list[str],
    selected_downloads: list[dict[str, str]],
    schedule: str | None,
    is_active: bool,
) -> None:
    normalized_downloads = _normalize_selected_downloads(selected_downloads)
    pipeline_id = str(uuid4())

    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        connection = _load_connection_record(cur, connection_key)
        if not connection:
            raise PnpConnectionNotFoundError(connection_key)

        cur.execute(
            """
            DELETE FROM raw.pnp_instances
            WHERE instance_key = %s
              AND deleted_at IS NOT NULL
            """,
            (instance_key,),
        )

        cur.execute(
            """
            INSERT INTO raw.pnp_instances (
              pipeline_id,
              instance_key,
              instance_name,
              connection_key,
              connection_name,
              page_url,
              schedule,
              is_active,
              legacy_mode,
              metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pipeline_id,
                instance_key,
                instance_name,
                connection_key,
                connection["connection_name"],
                connection["page_url"],
                schedule,
                is_active,
                "powerbi_microdados",
                Json(
                    {
                        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
                        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
                        "source_path": "powerbi_microdados",
                    }
                ),
            ),
        )

        selection_rows = [
                (
                    pipeline_id,
                    instance_key,
                    item["ano_base"],
                item["tipo_microdados"],
                item["microdados_url"],
                True,
                index,
                Json({"selection_source": "selected_downloads"}),
            )
            for index, item in enumerate(normalized_downloads, start=1)
        ]
        if not selection_rows:
            selection_rows = [
                (
                    pipeline_id,
                    instance_key,
                    year,
                    microdados_type,
                    None,
                    True,
                    index,
                    Json({"selection_source": "year_type_matrix"}),
                )
                for index, (year, microdados_type) in enumerate(
                    [(year, microdados_type) for year in selected_years for microdados_type in selected_microdados_types],
                    start=1,
                )
            ]
        execute_values(
            cur,
            """
            INSERT INTO raw.pnp_instance_selection (
              pipeline_id,
              instance_key,
              ano_base,
              tipo_microdados,
              configured_microdados_url,
              is_active,
              selection_rank,
              metadata
            ) VALUES %s
            """,
            selection_rows,
        )

        _sync_pipeline_endpoints(
            cur,
            pipeline_id=pipeline_id,
            instance_key=instance_key,
            connection_key=str(connection["connection_key"]),
            is_active=is_active,
        )

        cur.execute(
            """
            UPDATE raw.pnp_instances
            SET
              legacy_endpoint_id = NULL,
              legacy_endpoint_key = NULL
            WHERE instance_key = %s
            """,
            (instance_key,),
        )

    pnp_dag_provisioner.provision_pipeline_dag(
        pipeline_id=pipeline_id,
        instance_key=instance_key,
        schedule=schedule,
        is_active=is_active,
    )


def update_instance_settings(
    connect_factory: Callable[[], Any],
    *,
    instance_key: str,
    schedule: str | None = None,
    is_active: bool | None = None,
) -> None:
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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
              deleted_at
            FROM raw.pnp_instances
            WHERE instance_key = %s
              AND deleted_at IS NULL
            """,
            (instance_key,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(instance_key)

        next_schedule = schedule if schedule is not None else row["schedule"]
        next_is_active = is_active if is_active is not None else row["is_active"]

        cur.execute(
            """
            UPDATE raw.pnp_instances
            SET
              schedule = %s,
              is_active = %s,
              updated_at = NOW()
            WHERE instance_key = %s
            """,
            (next_schedule, next_is_active, instance_key),
        )

        _sync_pipeline_endpoints(
            cur,
            pipeline_id=str(row["pipeline_id"]),
            instance_key=instance_key,
            connection_key=str(row["connection_key"]),
            is_active=bool(next_is_active),
        )

        cur.execute(
            """
            SELECT
              ano_base,
              tipo_microdados,
              configured_microdados_url
            FROM raw.pnp_instance_selection
            WHERE instance_key = %s
              AND is_active = TRUE
            ORDER BY COALESCE(selection_rank, 2147483647), ano_base DESC, tipo_microdados
            """,
            (instance_key,),
        )
        selections = [dict(item) for item in cur.fetchall()]
        selected_years = list(OrderedDict((str(item["ano_base"]), None) for item in selections).keys())
        selected_microdados_types = list(OrderedDict((str(item["tipo_microdados"]), None) for item in selections).keys())
        selected_downloads = _normalize_selected_downloads(
            [
                {
                    "ano_base": item["ano_base"],
                    "tipo_microdados": item["tipo_microdados"],
                    "microdados_url": item["configured_microdados_url"],
                }
                for item in selections
                if item.get("configured_microdados_url")
            ]
        )

    pnp_dag_provisioner.provision_pipeline_dag(
        pipeline_id=str(row["pipeline_id"]),
        instance_key=instance_key,
        schedule=next_schedule,
        is_active=bool(next_is_active),
    )


def delete_instance(connect_factory: Callable[[], Any], *, instance_key: str) -> dict[str, Any]:
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
              pipeline_id,
              instance_key,
              instance_name,
              legacy_endpoint_id,
              deleted_at
            FROM raw.pnp_instances
            WHERE instance_key = %s
            """,
            (instance_key,),
        )
        row = cur.fetchone()
        if not row:
            raise LookupError(instance_key)
        cur.execute(
            """
            DELETE FROM raw.pnp_instances
            WHERE instance_key = %s
            """,
            (instance_key,),
        )
        deleted_count = cur.rowcount

    pnp_dag_provisioner.remove_pipeline_dag(
        instance_key=instance_key,
        pipeline_id=str(row["pipeline_id"]),
    )

    return {
        "pipeline_id": str(row["pipeline_id"]),
        "instance_key": str(row["instance_key"]),
        "instance_name": str(row["instance_name"]),
        "deleted_endpoint_count": deleted_count,
        "mode": "physical_delete",
        "already_deleted": deleted_count == 0,
    }


def delete_connection(connect_factory: Callable[[], Any], *, connection_key: str) -> dict[str, Any]:
    with _connect(connect_factory) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        connection = _load_connection_record(cur, connection_key, include_deleted=True)
        if not connection:
            raise PnpConnectionNotFoundError(connection_key)

        cur.execute(
            """
            SELECT instance_key
            FROM raw.pnp_instances
            WHERE connection_key = %s
              AND deleted_at IS NULL
            ORDER BY instance_key
            """,
            (connection_key,),
        )
        instance_keys = [str(item["instance_key"]) for item in cur.fetchall()]

    deleted_instances = 0
    for instance_key in instance_keys:
        result = delete_instance(connect_factory, instance_key=instance_key)
        deleted_instances += int(result.get("deleted_endpoint_count") or 0)

    with _connect(connect_factory) as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM raw.pnp_connections
            WHERE connection_key = %s
            """,
            (connection_key,),
        )
        deleted_connection_rows = cur.rowcount

    return {
        "connection_key": str(connection["connection_key"]),
        "connection_name": str(connection["connection_name"]),
        "deleted_endpoint_count": deleted_instances + deleted_connection_rows,
        "mode": "physical_delete",
        "already_deleted": deleted_connection_rows == 0,
    }
