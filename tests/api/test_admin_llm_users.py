from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app import main
from app.keycloak_admin import KeycloakAdminClient


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


class FakeKeycloakAdmin:
    def __init__(self) -> None:
        self.users = {
            "user-1": {
                "id": "user-1",
                "username": "ana",
                "email": "ana@example.test",
                "first_name": "Ana",
                "last_name": "Admin",
                "enabled": True,
                "email_verified": False,
            }
        }

    def get_admin_user(self, user_id: str) -> dict[str, object] | None:
        return self.users.get(user_id)


class FakeMetabaseAdmin:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def find_user_by_email(self, email: str) -> dict[str, object] | None:
        return None

    def create_admin_user(self, *, email: str, password: str, first_name: str, last_name: str) -> dict[str, object]:
        user = {
            "id": 42,
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "is_superuser": True,
        }
        self.created.append(user)
        return user


def test_admin_llm_settings_store_maritaca_key_per_admin(monkeypatch) -> None:
    storage: dict[str, object] = {}
    monkeypatch.setattr(main, "_db_connect", lambda: FakeConnection(storage))
    main.app.dependency_overrides[main._require_admin] = lambda: {"sub": "admin-a", "realm_access": {"roles": ["admin"]}}

    try:
        response = TestClient(main.app).patch(
            "/api/admin/settings/llm",
            json={
                "provider": "maritaca",
                "ollama": {"base_url": "http://ollama:11434", "model": "sabia-7b"},
                "maritaca": {
                    "api_url": "https://chat.maritaca.ai/api/chat/completions",
                    "model": "sabia-4",
                    "timeout_seconds": 60,
                    "api_key": "personal-secret",
                    "clear_api_key": False,
                },
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["maritaca"]["api_key_scope"] == "personal"
    assert storage[main.VANNA_LLM_SETTING_KEY]["maritaca"]["api_key"] == ""
    assert storage[f"{main.VANNA_USER_LLM_SETTING_PREFIX}admin-a"]["maritaca"]["api_key"] == "personal-secret"


def test_vanna_ask_sends_personal_maritaca_override(monkeypatch) -> None:
    storage: dict[str, object] = {
        main.VANNA_LLM_SETTING_KEY: {
            "provider": "maritaca",
            "ollama": {"base_url": "http://ollama:11434", "model": "sabia-7b"},
            "maritaca": {
                "api_url": "https://chat.maritaca.ai/api/chat/completions",
                "api_key": "",
                "model": "sabia-4",
                "timeout_seconds": 60,
            },
        },
        f"{main.VANNA_USER_LLM_SETTING_PREFIX}admin-a": {"maritaca": {"api_key": "personal-secret"}},
    }
    captured: dict[str, object] = {}

    async def fake_ask_vanna(_url: str, question: str, llm_override: dict[str, object] | None = None) -> dict[str, object]:
        captured["question"] = question
        captured["llm_override"] = llm_override
        return {"question": question, "rows": []}

    monkeypatch.setattr(main, "_db_connect", lambda: FakeConnection(storage))
    monkeypatch.setattr(main, "ask_vanna", fake_ask_vanna)
    main.app.dependency_overrides[main.verify_optional_bearer] = lambda: {"sub": "admin-a", "realm_access": {"roles": ["admin"]}}

    try:
        response = TestClient(main.app).post("/api/vanna/ask", json={"question": "total de matriculas"})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    override = captured["llm_override"]
    assert isinstance(override, dict)
    assert override["provider"] == "maritaca"
    assert override["maritaca"]["api_key"] == "personal-secret"


def test_sync_admin_user_metabase_creates_missing_user(monkeypatch) -> None:
    keycloak = FakeKeycloakAdmin()
    metabase = FakeMetabaseAdmin()
    monkeypatch.setattr(main, "_keycloak_admin_client", lambda: keycloak)
    monkeypatch.setattr(main, "_metabase_admin_client", lambda: metabase)
    main.app.dependency_overrides[main._require_admin] = lambda: {"sub": "root-admin", "realm_access": {"roles": ["admin"]}}

    try:
        response = TestClient(main.app).post(
            "/api/admin/users/user-1/metabase-sync",
            json={"password": "metabase-secret"},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["user"]["metabase_synced"] is True
    assert metabase.created[0]["email"] == "ana@example.test"
    assert metabase.created[0]["password"] == "metabase-secret"


def test_keycloak_upsert_admin_user_updates_existing_user_and_assigns_admin_role(monkeypatch) -> None:
    client = KeycloakAdminClient(
        base_url="http://keycloak:8080",
        realm="dataif",
        admin_realm="master",
        admin_client_id="admin-cli",
        admin_username="root",
        admin_password="secret",
        timeout_seconds=30,
    )
    lookups = [
        {"id": "user-1", "username": "dataif", "email": "old@example.test", "enabled": True},
        {"id": "user-1", "username": "dataif", "email": "dataif@dataif.com", "enabled": True},
    ]
    requests: list[tuple[str, str, object | None]] = []

    monkeypatch.setattr(client, "_lookup_user_by_username", lambda _username: lookups.pop(0))
    monkeypatch.setattr(client, "_realm_role", lambda role_name: {"id": "role-1", "name": role_name})

    def fake_request(method: str, path: str, **kwargs: object) -> object:
        requests.append((method, path, kwargs.get("json")))
        if path.endswith("/role-mappings/realm") and method == "GET":
            return []
        return None

    monkeypatch.setattr(client, "_request", fake_request)

    user = client.upsert_admin_user(
        username="dataif",
        email="dataif@dataif.com",
        password="StrongPass123",
        first_name="DataIF",
        last_name="Admin",
    )

    assert user["id"] == "user-1"
    assert user["email"] == "dataif@dataif.com"
    assert any(item[0] == "PUT" and item[1].endswith("/users/user-1") for item in requests)
    assert any(item[0] == "PUT" and item[1].endswith("/reset-password") for item in requests)
    assert any(item[0] == "POST" and item[1].endswith("/role-mappings/realm") for item in requests)
