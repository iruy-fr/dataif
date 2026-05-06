from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[2] / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app import main


def test_get_pnp_connector_definition_exposes_powerbi_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_load_pnp_powerbi_catalog_or_502",
        lambda: {
            "page_url": "https://app.powerbi.com/view?r=fake",
            "available_years": ["2024", "2023"],
            "available_microdados_types": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
            "types_by_year": {
                "2024": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
                "2023": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
            },
            "items": [
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Matrículas",
                    "microdados_url": "https://example.test/microdados_2024_matriculas.csv.gz",
                },
                {
                    "ano_base": "2023",
                    "tipo_microdados": "Servidores",
                    "microdados_url": "https://example.test/microdados_2023_servidores.csv.gz",
                },
            ],
        },
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}
    try:
        client = TestClient(main.app)
        response = client.get("/api/admin/connector-definitions/pnp")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["connector_id"] == "pnp"
    assert body["ingestion_mode"] == "powerbi_microdados"
    assert body["selection_catalog"]["available_years"] == ["2024", "2023"]
    assert body["selection_catalog"]["available_microdados_types"] == [
        "Eficiência Acadêmica",
        "Financeiro",
        "Matrículas",
        "Servidores",
    ]
    assert body["selection_catalog"]["items"][0]["ano_base"] == "2024"


def test_admin_login_proxies_keycloak_token(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_request_keycloak_token",
        lambda form_fields: {
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "token_type": "Bearer",
            "expires_in": 300,
            "refresh_expires_in": 1800,
        }
        if form_fields["grant_type"] == "password"
        else {},
    )

    client = TestClient(main.app)
    response = client.post("/api/admin/login", json={"username": "dataif-admin", "password": "admin"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "token-1"
    assert body["refresh_token"] == "refresh-1"


def test_admin_refresh_proxies_keycloak_token(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_request_keycloak_token",
        lambda form_fields: {
            "access_token": "token-2",
            "refresh_token": "refresh-2",
            "token_type": "Bearer",
            "expires_in": 300,
            "refresh_expires_in": 1800,
        }
        if form_fields["grant_type"] == "refresh_token"
        else {},
    )

    client = TestClient(main.app)
    response = client.post("/api/admin/refresh", json={"refresh_token": "refresh-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "token-2"
    assert body["refresh_token"] == "refresh-2"


def test_create_pnp_instance_persists_exact_powerbi_download_links(monkeypatch) -> None:
    state: dict[str, list[dict[str, object]]] = {"rows": []}

    def _load_all_rows(_connect_factory, *, include_deleted: bool = False) -> list[dict[str, object]]:
        if include_deleted:
            return [dict(row) for row in state["rows"]]
        return [
            dict(row)
            for row in state["rows"]
            if not bool(dict(row.get("request_params") or {}).get("deleted"))
        ]

    def _create_connection(
        _connect_factory,
        *,
        connection_key: str,
        connection_name: str,
        page_url: str,
        is_active: bool,
    ) -> None:
        payload = main._build_pnp_connection_payload(
            connection_key=connection_key,
            connection_name=connection_name,
            page_url=page_url,
        )
        state["rows"].append(
            {
                "id": len(state["rows"]) + 1,
                "connector_id": main.PNP_INTERNAL_CONNECTOR_ID,
                "endpoint_key": payload["endpoint_key"],
                "description": payload["description"],
                "page_url": payload["page_url"],
                "api_endpoint_url": payload["api_endpoint_url"],
                "csv_url": payload["csv_url"],
                "dictionary_url": payload["dictionary_url"],
                "request_params": payload["request_params"],
                "is_active": is_active,
                "created_at": "2026-03-09T00:00:00Z",
                "updated_at": "2026-03-09T00:00:00Z",
            }
        )

    def _create_instance(
        _connect_factory,
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
        payload = main._build_pnp_pipeline_payload(
            pipeline_key=instance_key,
            pipeline_name=instance_name,
            connection_key=connection_key,
            connection_name="PNP Principal",
            page_url="https://app.powerbi.com/view?r=fake",
            selected_years=selected_years,
            selected_microdados_types=selected_microdados_types,
            selected_downloads=selected_downloads,
            schedule=schedule,
        )
        state["rows"].append(
            {
                "id": len(state["rows"]) + 1,
                "connector_id": main.PNP_INTERNAL_CONNECTOR_ID,
                "endpoint_key": payload["endpoint_key"],
                "description": payload["description"],
                "page_url": payload["page_url"],
                "api_endpoint_url": payload["api_endpoint_url"],
                "csv_url": payload["csv_url"],
                "dictionary_url": payload["dictionary_url"],
                "request_params": payload["request_params"],
                "is_active": is_active,
                "created_at": "2026-03-09T00:00:01Z",
                "updated_at": "2026-03-09T00:00:01Z",
            }
        )

    def _load_connection(_connect_factory, connection_key: str, *, include_deleted: bool = False) -> dict[str, object]:
        for row in state["rows"]:
            request_params = dict(row.get("request_params") or {})
            if request_params.get("entity_type") != "connection":
                continue
            if request_params.get("connection_key") != connection_key:
                continue
            if not include_deleted and request_params.get("deleted"):
                continue
            return dict(row)
        raise LookupError(connection_key)

    monkeypatch.setattr(main.pnp_instance_repository, "load_all_rows", _load_all_rows)
    monkeypatch.setattr(main.pnp_instance_repository, "load_connection", _load_connection)
    monkeypatch.setattr(main.pnp_instance_repository, "create_connection", _create_connection)
    monkeypatch.setattr(main.pnp_instance_repository, "create_instance", _create_instance)
    monkeypatch.setattr(
        main,
        "_load_pnp_powerbi_catalog_or_502",
        lambda: {
            "page_url": "https://app.powerbi.com/view?r=fake",
            "available_years": ["2024", "2023"],
            "available_microdados_types": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
            "types_by_year": {
                "2024": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
                "2023": ["Eficiência Acadêmica", "Financeiro", "Matrículas", "Servidores"],
            },
            "items": [
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Matrículas",
                    "microdados_url": "https://example.test/microdados_2024_matriculas.csv.gz",
                },
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Servidores",
                    "microdados_url": "https://example.test/microdados_2024_servidores.csv.gz",
                },
                {
                    "ano_base": "2023",
                    "tipo_microdados": "Matrículas",
                    "microdados_url": "https://example.test/microdados_2023_matriculas.csv.gz",
                },
                {
                    "ano_base": "2023",
                    "tipo_microdados": "Servidores",
                    "microdados_url": "https://example.test/microdados_2023_servidores.csv.gz",
                },
            ],
        },
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/admin/connectors/pnp/instances",
            json={
                "instance_name": "PNP IFB",
                "selected_years": ["2024", "2023"],
                "selected_microdados_types": ["Matrículas", "Servidores"],
                "schedule": "0 3 * * *",
                "is_active": False,
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["instance_key"] == "pnp_pipe_pnp_ifb"
    assert body["source_count"] == 4
    assert body["download_count"] == 4
    assert body["selected_years"] == ["2024", "2023"]
    assert body["selected_microdados_types"] == ["Matrículas", "Servidores"]
    assert len(body["selected_downloads"]) == 4
    connection_rows = [row for row in state["rows"] if row["request_params"].get("entity_type") == "connection"]
    pipeline_rows = [row for row in state["rows"] if row["request_params"].get("entity_type") == "pipeline"]
    assert len(connection_rows) == 1
    assert connection_rows[0]["page_url"] == "https://app.powerbi.com/view?r=fake"
    assert len(pipeline_rows) == 1
    assert len(pipeline_rows[0]["request_params"]["selected_downloads"]) == 4


def test_create_pnp_pipeline_uses_existing_connection(monkeypatch) -> None:
    connection_row = {
        "id": 1,
        "connector_id": main.PNP_INTERNAL_CONNECTOR_ID,
        "endpoint_key": "pnp_conn_principal__connection",
        "description": "PNP Principal - conexao PNP",
        "page_url": "https://app.powerbi.com/view?r=fake",
        "api_endpoint_url": None,
        "csv_url": None,
        "dictionary_url": None,
        "request_params": {
            "mode": "powerbi_microdados",
            "entity_type": "connection",
            "connection_key": "pnp_conn_principal",
            "connection_name": "PNP Principal",
        },
        "is_active": True,
        "created_at": "2026-03-09T00:00:00Z",
        "updated_at": "2026-03-09T00:00:00Z",
    }
    created: dict[str, object] = {}

    monkeypatch.setattr(
        main.pnp_instance_repository,
        "load_connection",
        lambda _connect_factory, connection_key, *, include_deleted=False: dict(connection_row)
        if connection_key == "pnp_conn_principal"
        else (_ for _ in ()).throw(LookupError(connection_key)),
    )
    monkeypatch.setattr(
        main,
        "_load_pnp_powerbi_catalog_or_502",
        lambda: {
            "page_url": "https://app.powerbi.com/view?r=fake",
            "available_years": ["2024"],
            "available_microdados_types": ["Matrículas", "Servidores"],
            "types_by_year": {"2024": ["Matrículas", "Servidores"]},
            "items": [
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Matrículas",
                    "microdados_url": "https://example.test/microdados_2024_matriculas.csv.gz",
                },
                {
                    "ano_base": "2024",
                    "tipo_microdados": "Servidores",
                    "microdados_url": "https://example.test/microdados_2024_servidores.csv.gz",
                },
            ],
        },
    )

    def _create_instance(
        _connect_factory,
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
        created.update(
            {
                "instance_key": instance_key,
                "instance_name": instance_name,
                "connection_key": connection_key,
                "selected_years": list(selected_years),
                "selected_microdados_types": list(selected_microdados_types),
                "selected_downloads": list(selected_downloads),
                "schedule": schedule,
                "is_active": is_active,
            }
        )

    monkeypatch.setattr(main.pnp_instance_repository, "create_instance", _create_instance)
    monkeypatch.setattr(
        main,
        "_load_pnp_instance",
        lambda instance_key: {
            "instance_key": instance_key,
            "connection_key": created["connection_key"],
            "download_count": len(created["selected_downloads"]),
        },
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/admin/pipelines/pnp",
            json={
                "pipeline_name": "Pipeline Principal",
                "connection_key": "pnp_conn_principal",
                "selected_years": ["2024"],
                "selected_microdados_types": ["Matrículas", "Servidores"],
                "schedule": "0 3 * * *",
                "is_active": True,
            },
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert created["connection_key"] == "pnp_conn_principal"
    assert created["instance_key"] == "pnp_pipe_pipeline_principal"
    assert len(created["selected_downloads"]) == 2


def test_list_pnp_instances_groups_internal_endpoints(monkeypatch) -> None:
    rows = [
        {
            "id": 10,
            "connector_id": "nilo_pecanha",
            "endpoint_key": "pnp_ifb__powerbi_microdados",
            "description": "PNP IFB - Catálogo público de microdados via Power BI",
            "page_url": "https://app.powerbi.com/view?r=fake",
            "request_params": {
                "instance_key": "pnp_ifb",
                "instance_name": "PNP IFB",
                "mode": "powerbi_microdados",
                "selected_years": ["2024", "2023"],
                "selected_microdados_types": ["Matrículas", "Servidores"],
                "selected_downloads": [
                    {
                        "ano_base": "2024",
                        "tipo_microdados": "Matrículas",
                        "microdados_url": "https://example.test/microdados_2024_matriculas.csv.gz",
                    },
                    {
                        "ano_base": "2023",
                        "tipo_microdados": "Servidores",
                        "microdados_url": "https://example.test/microdados_2023_servidores.csv.gz",
                    },
                ],
            },
            "is_active": True,
            "created_at": "2026-03-09T00:00:00Z",
            "updated_at": "2026-03-09T00:00:10Z",
        },
    ]
    monkeypatch.setattr(main, "_db_connect", lambda: _ListConnection(rows))
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.get("/api/admin/connectors/pnp/instances")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    instance = body["items"][0]
    assert instance["instance_key"] == "pnp_ifb"
    assert instance["ingestion_mode"] == "powerbi_microdados"
    assert instance["source_count"] == 2


def test_get_pnp_instance_admin_overview(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_load_pnp_instance",
        lambda instance_key: {
            "instance_key": instance_key,
            "instance_name": "PNP IFB",
            "source_count": 2,
            "ingestion_mode": "powerbi_microdados",
        },
    )
    monkeypatch.setattr(
        main,
        "_load_pnp_instance_diagnostics",
        lambda instance_key: [
            {"endpoint_key": "pnp_ifb__powerbi_microdados", "status": "ok", "operational_status": "raw_loaded"},
            {"endpoint_key": "pnp_ifb__powerbi_microdados_secundario", "status": "error", "operational_status": "error"},
        ],
    )
    monkeypatch.setattr(
        main,
        "_load_pnp_instance_run_events",
        lambda instance_key: [
            {
                "run_id": "run-1",
                "stage": "extract_raw",
                "stage_label": "Extracao de microdados",
                "state": "success",
                "message": "A extração e a carga bruta dos microdados foram concluídas.",
                "timestamp": "2026-03-15T12:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(
        main,
        "_load_pnp_instance_integrations",
        lambda instance_key: [
            {"run_id": "run-1", "integration_type": "source_validation"},
            {"run_id": "run-2", "integration_type": "extract_raw"},
        ],
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.get("/api/admin/connectors/pnp/instances/pnp_ifb/admin-overview")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["instance"]["instance_key"] == "pnp_ifb"
    assert len(body["diagnostics"]) == 2
    assert body["diagnostics_summary"]["raw_loaded"] == 1
    assert body["diagnostics_summary"]["attention"] == 1
    assert body["ingestion"]["status"] == "raw_loaded"
    assert len(body["run_events"]) == 1
    assert len(body["integrations"]) == 2
    assert "auth_history" not in body


def test_build_pnp_ingestion_summary_prefers_latest_successful_stage() -> None:
    summary = main._build_pnp_ingestion_summary(
        [
            {
                "run_id": "run-1",
                "stage": "extract_raw",
                "stage_label": "Carga em raw",
                "state": "success",
                "message": "A extração e a carga bruta foram concluídas.",
                "timestamp": "2026-03-15T12:00:00Z",
            },
        ]
    )

    assert summary["status"] == "raw_loaded"
    assert summary["latest_success_stage"] == "extract_raw"
    assert summary["last_event_at"] == "2026-03-15T12:00:00Z"


def test_list_pnp_instance_dag_runs(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_load_pnp_instance_dag_runs",
        lambda instance_key: [
            {
                "dag_id": "pnp_pipeline",
                "dag_run_id": f"pnp_pipeline__{instance_key}__validate__20260315T000000Z",
                "state": "running",
                "conf": {"instance_key": instance_key, "operation": "validate"},
            },
            {
                "dag_id": "pnp_pipeline",
                "dag_run_id": f"pnp_pipeline__{instance_key}__sync__20260315T010000Z",
                "state": "success",
                "conf": {"instance_key": instance_key, "operation": "sync"},
            },
        ],
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.get("/api/admin/connectors/pnp/instances/pnp_ifb/dag-runs")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["state"] == "running"
    assert body["items"][1]["dag_id"] == "pnp_pipeline"


def test_trigger_pnp_instance_operations_proxy_airflow(monkeypatch) -> None:
    captured: list[tuple[str, str, str]] = []

    def fake_trigger(dag_id: str, instance_key: str, *, operation: str) -> dict[str, object]:
        captured.append((dag_id, instance_key, operation))
        return {"dag_id": dag_id, "instance_key": instance_key, "dag_run": {"dag_run_id": "run-1"}}

    monkeypatch.setattr(main, "_trigger_pnp_airflow_dag", fake_trigger)
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        validate_response = client.post("/api/admin/connectors/pnp/instances/pnp_ifb/operations/validate-sources")
        sync_response = client.post("/api/admin/connectors/pnp/instances/pnp_ifb/operations/full-sync")
    finally:
        main.app.dependency_overrides.clear()

    assert validate_response.status_code == 200
    assert sync_response.status_code == 200
    assert captured == [
        ("pnp_pipeline", "pnp_ifb", "validate"),
        ("pnp_pipeline", "pnp_ifb", "sync"),
    ]


def test_update_pnp_instance_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "_load_pnp_instance",
        lambda instance_key: {"instance_key": instance_key, "instance_name": "PNP IFB", "is_active": False},
    )
    monkeypatch.setattr(
        main,
        "_persist_pnp_instance_settings",
        lambda instance_key, schedule=None, is_active=None: {
            "instance_key": instance_key,
            "instance_name": "PNP IFB",
            "schedule": schedule,
            "is_active": is_active,
        },
    )
    main.app.dependency_overrides[main._require_admin] = lambda: {"realm_access": {"roles": ["admin"]}}

    try:
        client = TestClient(main.app)
        response = client.patch(
            "/api/admin/connectors/pnp/instances/pnp_ifb",
            json={"schedule": "0 6 * * *", "is_active": True},
        )
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["instance_key"] == "pnp_ifb"
    assert body["schedule"] == "0 6 * * *"
    assert body["is_active"] is True
