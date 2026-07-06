from __future__ import annotations

import sys
import time

from fastapi import HTTPException
import psycopg2
from psycopg2 import sql

from .config import settings
from .metabase_admin import MetabaseAdminClient

METABASE_DATABASE_NAME = "DataIF Postgres"
METABASE_DATABASE_HOST = "postgres"
METABASE_DATABASE_PORT = 5432
METABASE_READ_SCHEMAS = ("raw", "staging", "curated")


def ensure_metabase_postgres_grants() -> None:
    if not settings.warehouse_dsn:
        raise HTTPException(status_code=500, detail="WAREHOUSE_DSN not configured")

    with psycopg2.connect(settings.warehouse_dsn) as conn, conn.cursor() as cur:
        schema_list = sql.SQL(", ").join(sql.Identifier(schema) for schema in METABASE_READ_SCHEMAS)
        metabase_user = sql.Identifier(settings.dataif_metabase_user)

        cur.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                schema_list,
                metabase_user,
            )
        )
        cur.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                schema_list,
                metabase_user,
            )
        )
        for schema in METABASE_READ_SCHEMAS:
            cur.execute(
                sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
                    sql.Identifier(schema),
                    metabase_user,
                )
            )


def main() -> int:
    client = MetabaseAdminClient(
        base_url=settings.metabase_api_url,
        admin_email=settings.metabase_admin_email,
        admin_password=settings.metabase_admin_password,
        timeout_seconds=max(settings.nilo_timeout_seconds, 30.0),
    )

    deadline = time.monotonic() + 180
    last_error = "Metabase did not become ready"
    while time.monotonic() < deadline:
        try:
            outcome = client.ensure_initial_admin(
                first_name=settings.metabase_admin_first_name,
                last_name=settings.metabase_admin_last_name,
                site_name=settings.metabase_site_name,
                allow_tracking=settings.metabase_allow_tracking,
            )
            state = "bootstrapped" if outcome.get("bootstrapped") else "already_configured"
            ensure_metabase_postgres_grants()
            database_outcome = client.ensure_postgres_database(
                name=METABASE_DATABASE_NAME,
                host=METABASE_DATABASE_HOST,
                port=METABASE_DATABASE_PORT,
                dbname=settings.dataif_db_name,
                user=settings.dataif_metabase_user,
                password=settings.dataif_metabase_password,
                ssl=False,
            )
            if database_outcome.get("created"):
                database_state = "created"
            elif database_outcome.get("updated"):
                database_state = "updated"
            else:
                database_state = "already_configured"
            print(f"metabase_bootstrap={state} postgres_grants=ok postgres_database={database_state}")
            return 0
        except HTTPException as exc:
            last_error = str(exc.detail)
        except Exception as exc:  # pragma: no cover - defensive bootstrap path
            last_error = str(exc)
        time.sleep(3)

    print(f"metabase_bootstrap_failed={last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
