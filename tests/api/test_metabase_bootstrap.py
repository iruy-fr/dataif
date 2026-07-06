from __future__ import annotations

import sys
from pathlib import Path

from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app import metabase_bootstrap
from app.metabase_admin import MetabaseAdminClient


def test_ensure_postgres_database_updates_existing_database(monkeypatch) -> None:
    client = MetabaseAdminClient(
        base_url="http://metabase:3000",
        admin_email="admin@dataif.local",
        admin_password="secret",
        timeout_seconds=30,
    )
    calls: list[tuple[str, str, object | None]] = []

    def fake_request(method: str, path: str, *, json: object | None = None, expected_status: set[int]) -> object:
        calls.append((method, path, json))
        assert expected_status
        if method == "GET" and path == "/api/database":
            return {
                "data": [
                    {
                        "id": 2,
                        "name": "DataIF Postgres",
                        "engine": "postgres",
                        "details": {"host": "postgres", "dbname": "dataif", "user": "old_user"},
                    }
                ]
            }
        if method == "PUT" and path == "/api/database/2":
            assert isinstance(json, dict)
            assert json["details"]["user"] == "metabase_user"
            return {"id": 2, **json}
        return None

    monkeypatch.setattr(client, "_request", fake_request)

    outcome = client.ensure_postgres_database(
        name="DataIF Postgres",
        host="postgres",
        port=5432,
        dbname="dataif",
        user="metabase_user",
        password="metabase_password",
    )

    assert outcome["created"] is False
    assert outcome["updated"] is True
    assert outcome["database"]["id"] == 2
    assert [call[:2] for call in calls] == [
        ("GET", "/api/database"),
        ("PUT", "/api/database/2"),
        ("POST", "/api/database/2/sync_schema"),
        ("POST", "/api/database/2/rescan_values"),
    ]


def test_ensure_postgres_database_creates_and_syncs_when_missing(monkeypatch) -> None:
    client = MetabaseAdminClient(
        base_url="http://metabase:3000",
        admin_email="admin@dataif.local",
        admin_password="secret",
        timeout_seconds=30,
    )
    calls: list[tuple[str, str, object | None]] = []

    def fake_request(method: str, path: str, *, json: object | None = None, expected_status: set[int]) -> object:
        calls.append((method, path, json))
        assert expected_status
        if method == "GET" and path == "/api/database":
            return {"data": []}
        if method == "POST" and path == "/api/database":
            assert isinstance(json, dict)
            assert json["name"] == "DataIF Postgres"
            assert json["engine"] == "postgres"
            assert json["details"] == {
                "host": "postgres",
                "port": 5432,
                "dbname": "dataif",
                "user": "metabase_user",
                "password": "metabase_password",
                "ssl": False,
            }
            return {"id": 2, **json}
        return None

    monkeypatch.setattr(client, "_request", fake_request)

    outcome = client.ensure_postgres_database(
        name="DataIF Postgres",
        host="postgres",
        port=5432,
        dbname="dataif",
        user="metabase_user",
        password="metabase_password",
    )

    assert outcome["created"] is True
    assert [call[:2] for call in calls] == [
        ("GET", "/api/database"),
        ("POST", "/api/database"),
        ("POST", "/api/database/2/sync_schema"),
        ("POST", "/api/database/2/rescan_values"),
    ]


def test_sync_database_ignores_rescan_endpoint_incompatibility(monkeypatch) -> None:
    client = MetabaseAdminClient(
        base_url="http://metabase:3000",
        admin_email="admin@dataif.local",
        admin_password="secret",
        timeout_seconds=30,
    )
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, *, json: object | None = None, expected_status: set[int]) -> object:
        calls.append((method, path))
        assert json is None
        assert expected_status
        if path.endswith("/rescan_values"):
            raise HTTPException(status_code=404, detail="not found")
        return None

    monkeypatch.setattr(client, "_request", fake_request)

    client.sync_database(2)

    assert calls == [
        ("POST", "/api/database/2/sync_schema"),
        ("POST", "/api/database/2/rescan_values"),
    ]


class FakeCursor:
    def __init__(self, queries: list[str]) -> None:
        self.queries = queries

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: object) -> None:
        self.queries.append(repr(query))


class FakeConnection:
    def __init__(self, queries: list[str]) -> None:
        self.queries = queries

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.queries)


def test_ensure_metabase_postgres_grants_covers_raw_staging_and_curated(monkeypatch) -> None:
    queries: list[str] = []

    monkeypatch.setattr(metabase_bootstrap.settings, "warehouse_dsn", "postgresql://etl@postgres:5432/dataif")
    monkeypatch.setattr(metabase_bootstrap.settings, "dataif_metabase_user", "metabase_user")
    monkeypatch.setattr(metabase_bootstrap.psycopg2, "connect", lambda dsn: FakeConnection(queries))

    metabase_bootstrap.ensure_metabase_postgres_grants()

    rendered = "\n".join(queries)
    assert "Identifier('raw')" in rendered
    assert "Identifier('staging')" in rendered
    assert "Identifier('curated')" in rendered
    assert rendered.count("ALTER DEFAULT PRIVILEGES IN SCHEMA ") == 3
    assert "Identifier('metabase_user')" in rendered
