from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from fastapi.testclient import TestClient

from app import main
from app.metabase_embed import build_signed_dashboard_url


def test_signed_url_contains_embed_path() -> None:
    url = build_signed_dashboard_url(
        site_url="http://metabase:3000",
        embed_secret="secret",
        dashboard_id=12,
        params={},
    )
    assert "/embed/dashboard/" in url
    assert url.startswith("http://metabase:3000")


class FakeCursor:
    def __init__(self, storage: dict[str, object]):
        self.storage = storage
        self.row: dict[str, object] | None = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        normalized = " ".join(query.lower().split())
        if normalized.startswith("select setting_value"):
            key = str(params[0])
            value = self.storage.get(key)
            self.row = {"setting_value": value} if value is not None else None
            return
        if normalized.startswith("insert into config.app_settings"):
            key = str(params[0])
            self.storage[key] = json.loads(str(params[1]))

    def fetchone(self) -> dict[str, object] | None:
        return self.row


class FakeConnection:
    def __init__(self, storage: dict[str, object]):
        self.storage = storage

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.storage)


def test_get_default_metabase_embed_uses_configured_fallback(monkeypatch) -> None:
    storage: dict[str, object] = {}
    monkeypatch.setattr(main.settings, "metabase_allowed_dashboard_ids", "2,3")
    monkeypatch.setattr(main.settings, "metabase_default_dashboard_id", "3")
    monkeypatch.setattr(main, "_db_connect", lambda: FakeConnection(storage))

    response = TestClient(main.app).get("/api/embed/metabase-default")

    assert response.status_code == 200
    body = response.json()
    assert body["dashboard_id"] == 3
    assert "/embed/dashboard/" in body["signed_url"]


def test_admin_set_default_metabase_embed_persists_global_dashboard(monkeypatch) -> None:
    storage: dict[str, object] = {}
    monkeypatch.setattr(main.settings, "metabase_allowed_dashboard_ids", "2,3")
    monkeypatch.setattr(main.settings, "metabase_default_dashboard_id", "2")
    monkeypatch.setattr(main, "_db_connect", lambda: FakeConnection(storage))
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        save_response = client.post("/api/admin/embed/metabase-default", json={"dashboard_id": 3, "params": {}})
        get_response = client.get("/api/embed/metabase-default")
    finally:
        main.app.dependency_overrides.clear()

    assert save_response.status_code == 200
    assert save_response.json()["dashboard_id"] == 3
    assert get_response.status_code == 200
    assert get_response.json()["dashboard_id"] == 3


def test_admin_set_default_metabase_embed_requires_admin() -> None:
    response = TestClient(main.app).post("/api/admin/embed/metabase-default", json={"dashboard_id": 2, "params": {}})

    assert response.status_code == 401


def test_admin_set_default_metabase_embed_rejects_unallowed_dashboard(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "metabase_allowed_dashboard_ids", "2")
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        response = TestClient(main.app).post(
            "/api/admin/embed/metabase-default",
            json={"dashboard_id": 3, "params": {}},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 403
