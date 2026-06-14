from __future__ import annotations

import json
import re
from threading import Lock
from datetime import datetime, timezone
from time import monotonic, sleep
from typing import Any

import httpx
import psycopg2
from croniter import croniter
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from psycopg2.extras import RealDictCursor

from .auth import require_admin, verify_optional_bearer
from .config import settings
from .keycloak_admin import KeycloakAdminClient
from .metabase_admin import MetabaseAdminClient
from .metabase_embed import build_signed_dashboard_url
from . import pnp_dag_provisioner, pnp_instance_repository
from .pnp_powerbi import DEFAULT_PNP_POWERBI_REPORT_URL, PNP_MICRODADOS_TYPES, load_public_microdados_catalog
from .vanna_client import ask_vanna

PNP_INTERNAL_CONNECTOR_ID = "nilo_pecanha"
PNP_POWERBI_GROUP_LABEL = "Microdados Publicos"
PNP_POWERBI_SOURCE_LABEL = "Catalogo publico de microdados via Power BI"
PNP_CONNECTION_ENTITY = "connection"
PNP_PIPELINE_ENTITY = "pipeline"
METABASE_DEFAULT_DASHBOARD_SETTING_KEY = "metabase.default_dashboard_id"
VANNA_LLM_SETTING_KEY = "vanna.llm_config"
VANNA_USER_LLM_SETTING_PREFIX = "vanna.llm_config.user."
PNP_RUNTIME_TASK_META = {
    "load_instance_config": {
        "stage": "load_instance_config",
        "stage_label": "Carregamento da configuracao",
        "message": "A configuracao da pipeline foi carregada.",
    },
    "resolve_powerbi_catalog": {
        "stage": "resolve_powerbi_catalog",
        "stage_label": "Resolucao do catalogo",
        "message": "O catalogo Power BI foi resolvido.",
    },
    "extract_raw": {
        "stage": "extract_raw",
        "stage_label": "Extracao de microdados",
        "message": "A extração e a carga bruta dos microdados foram concluídas.",
    },
    "materialize_staging": {
        "stage": "materialize_staging",
        "stage_label": "Materializacao de staging",
        "message": "A staging deduplicada foi materializada.",
    },
    "build_curated_views": {
        "stage": "build_curated_views",
        "stage_label": "Publicacao de curated",
        "message": "As views e materialized views curadas foram publicadas.",
    },
    "run_quality_checks": {
        "stage": "run_quality_checks",
        "stage_label": "Checagens de qualidade",
        "message": "As checagens operacionais e de qualidade foram executadas.",
    },
    "finalize_run": {
        "stage": "finalize_run",
        "stage_label": "Encerramento da execucao",
        "message": "A execucao da pipeline foi finalizada.",
    },
}

_PNP_CATALOG_CACHE: dict[str, Any] = {"value": None, "loaded_at": 0.0}
_PNP_CATALOG_CACHE_LOCK = Lock()


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized and normalized.lstrip("-").isdigit():
            return int(normalized)
    return None


def _parse_iso_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class EmbedRequest(BaseModel):
    dashboard_id: int = Field(..., ge=1)
    params: dict[str, object] = Field(default_factory=dict)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)


class AdminSqlQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1, max_length=100_000)
    max_rows: int = Field(default=500, ge=1, le=5_000)


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=255)


class AdminRefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1, max_length=4096)


class LlmProviderOllamaRequest(BaseModel):
    base_url: str = Field(default="http://ollama:11434", min_length=1, max_length=255)
    model: str = Field(default="sabia-7b", min_length=1, max_length=120)


class LlmProviderMaritacaRequest(BaseModel):
    api_url: str = Field(default="https://chat.maritaca.ai/api/chat/completions", min_length=1, max_length=255)
    model: str = Field(default="sabia-4", min_length=1, max_length=120)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


class AdminLlmSettingsUpdateRequest(BaseModel):
    provider: str = Field(..., pattern="^(ollama|maritaca)$")
    ollama: LlmProviderOllamaRequest
    maritaca: LlmProviderMaritacaRequest


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=120)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)
    first_name: str = Field(default="", max_length=120)
    last_name: str = Field(default="", max_length=120)
    enabled: bool = True


class AdminUserMetabaseSyncRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=255)


class PnpInstanceCreateRequest(BaseModel):
    instance_name: str = Field(..., min_length=3, max_length=120)
    selected_years: list[str] = Field(..., min_length=1)
    selected_microdados_types: list[str] = Field(..., min_length=1)
    schedule: str | None = Field(default=None, max_length=120)
    is_active: bool = False

    @model_validator(mode="after")
    def validate_sources(self) -> "PnpInstanceCreateRequest":
        normalized_years = [item.strip() for item in self.selected_years if isinstance(item, str) and item.strip()]
        normalized_types: list[str] = []
        for item in self.selected_microdados_types:
            cleaned = item.strip()
            if not cleaned:
                continue
            if cleaned not in PNP_MICRODADOS_TYPES:
                raise ValueError(f"Unsupported PNP microdados type: {cleaned}")
            normalized_types.append(cleaned)

        if not normalized_years:
            raise ValueError("At least one selected_years entry is required")
        if not normalized_types:
            raise ValueError("At least one selected_microdados_types entry is required")

        self.selected_years = list(dict.fromkeys(normalized_years))
        self.selected_microdados_types = list(dict.fromkeys(normalized_types))
        return self


class PnpInstanceUpdateRequest(BaseModel):
    schedule: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class PnpConnectionCreateRequest(BaseModel):
    connection_name: str = Field(..., min_length=3, max_length=120)
    is_active: bool = True


class PnpPipelineCreateRequest(BaseModel):
    pipeline_name: str = Field(..., min_length=3, max_length=120)
    connection_key: str = Field(..., min_length=3, max_length=120)
    selected_years: list[str] = Field(..., min_length=1)
    selected_microdados_types: list[str] = Field(..., min_length=1)
    schedule: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_sources(self) -> "PnpPipelineCreateRequest":
        normalized_years = [item.strip() for item in self.selected_years if isinstance(item, str) and item.strip()]
        normalized_types: list[str] = []
        for item in self.selected_microdados_types:
            cleaned = item.strip()
            if not cleaned:
                continue
            if cleaned not in PNP_MICRODADOS_TYPES:
                raise ValueError(f"Unsupported PNP microdados type: {cleaned}")
            normalized_types.append(cleaned)

        if not normalized_years:
            raise ValueError("At least one selected_years entry is required")
        if not normalized_types:
            raise ValueError("At least one selected_microdados_types entry is required")

        self.selected_years = list(dict.fromkeys(normalized_years))
        self.selected_microdados_types = list(dict.fromkeys(normalized_types))
        return self


app = FastAPI(title="dataif-api", version="0.4.0")

allowed_origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_admin(payload: dict[str, object] | None = Depends(verify_optional_bearer)) -> dict[str, object]:
    require_admin(payload)
    return payload or {}


def _db_connect():
    if not settings.warehouse_dsn:
        raise HTTPException(status_code=500, detail="WAREHOUSE_DSN not configured")
    return psycopg2.connect(settings.warehouse_dsn, cursor_factory=RealDictCursor)


def _compact_sql(statement: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", statement, flags=re.DOTALL)
    without_line_comments = re.sub(r"--.*?$", " ", without_block_comments, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", without_line_comments).strip()


def _validate_admin_sql(statement: str) -> str:
    compact = _compact_sql(statement)
    normalized = compact.lower()

    if not normalized:
        raise HTTPException(status_code=422, detail="SQL vazio.")
    if not (normalized.startswith("select") or normalized.startswith("with")):
        raise HTTPException(status_code=422, detail="Apenas SELECT ou WITH sao permitidos.")
    if ";" in compact.rstrip(";"):
        raise HTTPException(status_code=422, detail="Apenas uma instrucao SQL e permitida.")

    forbidden_patterns = [
        r"\binsert\b",
        r"\bupdate\b",
        r"\bdelete\b",
        r"\bdrop\b",
        r"\balter\b",
        r"\btruncate\b",
        r"\bcreate\b",
        r"\bgrant\b",
        r"\brevoke\b",
        r"\bcopy\b",
        r"\bcall\b",
        r"\bdo\b",
        r"\bexecute\b",
        r"\bvacuum\b",
        r"\banalyze\b",
        r"\bset\b",
        r"\breset\b",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, normalized):
            raise HTTPException(status_code=422, detail="A consulta contem palavra-chave nao permitida.")

    return compact.rstrip(";")


def _admin_sql_catalog() -> list[dict[str, object]]:
    with _db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH relations AS (
              SELECT
                table_schema AS schema_name,
                table_name AS relation_name,
                CASE table_type
                  WHEN 'VIEW' THEN 'view'
                  ELSE 'table'
                END AS relation_type
              FROM information_schema.tables
              WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                AND table_type IN ('BASE TABLE', 'VIEW')
              UNION ALL
              SELECT
                schemaname AS schema_name,
                matviewname AS relation_name,
                'materialized_view' AS relation_type
              FROM pg_catalog.pg_matviews
              WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            )
            SELECT
              relations.schema_name,
              relations.relation_name,
              relations.relation_type,
              columns.column_name
            FROM relations
            LEFT JOIN information_schema.columns AS columns
              ON columns.table_schema = relations.schema_name
             AND columns.table_name = relations.relation_name
            ORDER BY relations.schema_name, relations.relation_name, columns.ordinal_position NULLS LAST;
            """
        )
        return list(cur.fetchall())


def _metabase_dashboard_id_list() -> list[int]:
    allowed: list[int] = []
    for item in settings.metabase_allowed_dashboard_ids.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        try:
            dashboard_id = int(cleaned)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="METABASE_ALLOWED_DASHBOARD_IDS is invalid") from exc
        if dashboard_id not in allowed:
            allowed.append(dashboard_id)
    if not allowed:
        raise HTTPException(status_code=500, detail="METABASE_ALLOWED_DASHBOARD_IDS is empty")
    return allowed


def _allowed_metabase_dashboard_ids() -> set[int]:
    return set(_metabase_dashboard_id_list())


def _fallback_metabase_dashboard_id(allowed_ids: list[int]) -> int:
    allowed = set(allowed_ids)
    configured = _coerce_int(settings.metabase_default_dashboard_id)
    if configured is not None:
        if configured not in allowed:
            raise HTTPException(status_code=500, detail="METABASE_DEFAULT_DASHBOARD_ID is not allowed")
        return configured
    return allowed_ids[0]


def _validate_metabase_dashboard_id(dashboard_id: int) -> None:
    if dashboard_id not in _allowed_metabase_dashboard_ids():
        raise HTTPException(status_code=403, detail="Dashboard id is not allowed for public embed")


def _ensure_app_settings_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config.app_settings (
              setting_key TEXT PRIMARY KEY,
              setting_value JSONB NOT NULL,
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def _read_metabase_default_dashboard_id() -> int:
    allowed_ids = _metabase_dashboard_id_list()
    allowed = set(allowed_ids)
    try:
        with _db_connect() as conn:
            _ensure_app_settings_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT setting_value FROM config.app_settings WHERE setting_key = %s",
                    (METABASE_DEFAULT_DASHBOARD_SETTING_KEY,),
                )
                row = cur.fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read default Metabase dashboard: {exc}") from exc

    if row:
        value = row["setting_value"]
        dashboard_id = _coerce_int(value.get("dashboard_id") if isinstance(value, dict) else value)
        if dashboard_id is not None and dashboard_id in allowed:
            return dashboard_id
    return _fallback_metabase_dashboard_id(allowed_ids)


def _write_metabase_default_dashboard_id(dashboard_id: int) -> None:
    _validate_metabase_dashboard_id(dashboard_id)
    try:
        with _db_connect() as conn:
            _ensure_app_settings_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO config.app_settings (setting_key, setting_value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (setting_key) DO UPDATE
                    SET setting_value = EXCLUDED.setting_value,
                        updated_at = NOW()
                    """,
                    (
                        METABASE_DEFAULT_DASHBOARD_SETTING_KEY,
                        json.dumps({"dashboard_id": dashboard_id}),
                    ),
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save default Metabase dashboard: {exc}") from exc


def _signed_metabase_dashboard_payload(dashboard_id: int, params: dict[str, object] | None = None) -> dict[str, object]:
    _validate_metabase_dashboard_id(dashboard_id)
    signed_url = build_signed_dashboard_url(
        site_url=settings.metabase_site_url,
        embed_secret=settings.metabase_embed_secret,
        dashboard_id=dashboard_id,
        params=params or {},
    )
    return {"dashboard_id": dashboard_id, "signed_url": signed_url}


def _read_app_setting(setting_key: str) -> dict[str, Any] | None:
    try:
        with _db_connect() as conn:
            _ensure_app_settings_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT setting_value FROM config.app_settings WHERE setting_key = %s",
                    (setting_key,),
                )
                row = cur.fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read app setting {setting_key}: {exc}") from exc

    if not row:
        return None
    value = row["setting_value"]
    return value if isinstance(value, dict) else None


def _write_app_setting(setting_key: str, setting_value: dict[str, Any]) -> None:
    try:
        with _db_connect() as conn:
            _ensure_app_settings_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO config.app_settings (setting_key, setting_value)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (setting_key) DO UPDATE
                    SET setting_value = EXCLUDED.setting_value,
                        updated_at = NOW()
                    """,
                    (setting_key, json.dumps(setting_value)),
                )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save app setting {setting_key}: {exc}") from exc


def _default_vanna_llm_settings() -> dict[str, Any]:
    return {
        "provider": "ollama",
        "ollama": {
            "base_url": "http://ollama:11434",
            "model": "sabia-7b",
        },
        "maritaca": {
            "api_url": "https://chat.maritaca.ai/api/chat/completions",
            "api_key": "",
            "model": "sabia-4",
            "timeout_seconds": 60,
        },
    }


def _vanna_llm_settings_from_env() -> dict[str, Any]:
    defaults = _default_vanna_llm_settings()
    return {
        "provider": str(settings.vanna_llm_provider).strip().lower() or defaults["provider"],
        "ollama": {
            "base_url": str(settings.vanna_ollama_base_url).strip() or defaults["ollama"]["base_url"],
            "model": str(settings.vanna_ollama_model).strip() or defaults["ollama"]["model"],
        },
        "maritaca": {
            "api_url": str(settings.vanna_maritaca_api_url).strip() or defaults["maritaca"]["api_url"],
            "api_key": str(settings.vanna_maritaca_api_key),
            "model": str(settings.vanna_maritaca_model).strip() or defaults["maritaca"]["model"],
            "timeout_seconds": _coerce_positive_int(
                settings.vanna_maritaca_timeout_seconds,
                defaults["maritaca"]["timeout_seconds"],
            ),
        },
    }


def _effective_vanna_llm_settings() -> dict[str, Any]:
    return _effective_global_vanna_llm_settings()


def _effective_global_vanna_llm_settings() -> dict[str, Any]:
    effective = _vanna_llm_settings_from_env()
    persisted = _read_app_setting(VANNA_LLM_SETTING_KEY)
    if not isinstance(persisted, dict):
        return effective

    provider = str(persisted.get("provider") or effective["provider"]).strip().lower() or effective["provider"]
    ollama = persisted.get("ollama") if isinstance(persisted.get("ollama"), dict) else {}
    maritaca = persisted.get("maritaca") if isinstance(persisted.get("maritaca"), dict) else {}
    return {
        "provider": provider,
        "ollama": {
            "base_url": str(ollama.get("base_url") or effective["ollama"]["base_url"]).strip() or effective["ollama"]["base_url"],
            "model": str(ollama.get("model") or effective["ollama"]["model"]).strip() or effective["ollama"]["model"],
        },
        "maritaca": {
            "api_url": str(maritaca.get("api_url") or effective["maritaca"]["api_url"]).strip()
            or effective["maritaca"]["api_url"],
            "api_key": str(maritaca.get("api_key") or effective["maritaca"]["api_key"]),
            "model": str(maritaca.get("model") or effective["maritaca"]["model"]).strip() or effective["maritaca"]["model"],
            "timeout_seconds": _coerce_positive_int(
                maritaca.get("timeout_seconds"),
                effective["maritaca"]["timeout_seconds"],
            ),
        },
    }


def _user_vanna_llm_setting_key(payload: dict[str, object] | None) -> str | None:
    if not payload:
        return None
    subject = str(payload.get("sub") or "").strip()
    if subject:
        return f"{VANNA_USER_LLM_SETTING_PREFIX}{subject}"

    fallback = str(payload.get("preferred_username") or payload.get("email") or "").strip().lower()
    if not fallback:
        return None
    safe_fallback = re.sub(r"[^a-z0-9_.@-]+", "_", fallback)
    return f"{VANNA_USER_LLM_SETTING_PREFIX}{safe_fallback}"


def _read_user_vanna_llm_settings(payload: dict[str, object] | None) -> dict[str, Any] | None:
    setting_key = _user_vanna_llm_setting_key(payload)
    if not setting_key:
        return None
    value = _read_app_setting(setting_key)
    return value if isinstance(value, dict) else None


def _effective_vanna_llm_settings_for_user(payload: dict[str, object] | None) -> dict[str, Any]:
    config = _effective_global_vanna_llm_settings()
    scope = "global" if str(config["maritaca"].get("api_key") or "").strip() else "empty"
    personal = _read_user_vanna_llm_settings(payload)
    if isinstance(personal, dict):
        maritaca = personal.get("maritaca") if isinstance(personal.get("maritaca"), dict) else {}
        personal_key = str(maritaca.get("api_key") or "")
        if personal_key.strip():
            config = {
                **config,
                "maritaca": {
                    **config["maritaca"],
                    "api_key": personal_key,
                },
            }
            scope = "personal"
    config["_maritaca_api_key_scope"] = scope
    return config


def _serialize_vanna_llm_settings_public(config: dict[str, Any]) -> dict[str, Any]:
    maritaca = config["maritaca"]
    masked_key = _mask_secret(str(maritaca.get("api_key") or ""))
    key_scope = str(config.get("_maritaca_api_key_scope") or ("configured" if masked_key else "empty"))
    return {
        "provider": config["provider"],
        "ollama": {
            "base_url": config["ollama"]["base_url"],
            "model": config["ollama"]["model"],
        },
        "maritaca": {
            "api_url": maritaca["api_url"],
            "model": maritaca["model"],
            "timeout_seconds": maritaca["timeout_seconds"],
            "has_api_key": bool(str(maritaca.get("api_key") or "").strip()),
            "api_key_scope": key_scope,
            "has_personal_api_key": key_scope == "personal",
            "masked_api_key": masked_key,
        },
    }


def _persist_vanna_llm_settings(
    payload: AdminLlmSettingsUpdateRequest,
    admin_payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    current_global = _effective_global_vanna_llm_settings()
    next_global = {
        "provider": payload.provider.strip().lower(),
        "ollama": {
            "base_url": payload.ollama.base_url.strip(),
            "model": payload.ollama.model.strip(),
        },
        "maritaca": {
            "api_url": payload.maritaca.api_url.strip(),
            "model": payload.maritaca.model.strip(),
            "timeout_seconds": int(payload.maritaca.timeout_seconds),
            "api_key": current_global["maritaca"]["api_key"],
        },
    }
    _write_app_setting(VANNA_LLM_SETTING_KEY, next_global)

    user_setting_key = _user_vanna_llm_setting_key(admin_payload)
    if user_setting_key:
        if payload.maritaca.clear_api_key:
            _write_app_setting(user_setting_key, {"maritaca": {"api_key": ""}})
        elif payload.maritaca.api_key is not None:
            _write_app_setting(user_setting_key, {"maritaca": {"api_key": payload.maritaca.api_key.strip()}})
    elif payload.maritaca.clear_api_key:
        next_global["maritaca"]["api_key"] = ""
        _write_app_setting(VANNA_LLM_SETTING_KEY, next_global)
    elif payload.maritaca.api_key is not None:
        next_global["maritaca"]["api_key"] = payload.maritaca.api_key.strip()
        _write_app_setting(VANNA_LLM_SETTING_KEY, next_global)

    return _effective_vanna_llm_settings_for_user(admin_payload)


def _vanna_llm_override_payload(config: dict[str, Any]) -> dict[str, object]:
    return {
        "provider": config["provider"],
        "ollama": {
            "base_url": config["ollama"]["base_url"],
            "model": config["ollama"]["model"],
        },
        "maritaca": {
            "api_url": config["maritaca"]["api_url"],
            "api_key": config["maritaca"]["api_key"],
            "model": config["maritaca"]["model"],
            "timeout_seconds": config["maritaca"]["timeout_seconds"],
        },
    }


def _vanna_provider_status(config: dict[str, Any]) -> dict[str, Any]:
    provider = str(config["provider"]).strip().lower()
    if provider == "maritaca":
        has_key = bool(str(config["maritaca"].get("api_key") or "").strip())
        return {
            "provider": provider,
            "available": has_key,
            "detail": "Maritaca API key configured" if has_key else "Maritaca API key is not configured",
        }

    target_url = f"{str(config['ollama']['base_url']).rstrip('/')}/api/tags"
    try:
        with httpx.Client(timeout=5, follow_redirects=True) as client:
            response = client.get(target_url)
    except httpx.RequestError as exc:
        return {"provider": provider, "available": False, "detail": f"Ollama is not reachable: {exc}"}

    available = response.status_code < 500
    return {
        "provider": provider,
        "available": available,
        "detail": f"Ollama responded with HTTP {response.status_code}" if available else f"Ollama returned HTTP {response.status_code}",
    }


def _mask_secret(value: str) -> str:
    secret = value.strip()
    if not secret:
        return ""
    if len(secret) <= 6:
        return "*" * len(secret)
    return f"{secret[:3]}{'*' * max(len(secret) - 6, 1)}{secret[-3:]}"


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value) or default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, float):
        parsed = int(value)
        return parsed if parsed > 0 else default
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            parsed = int(normalized)
            return parsed if parsed > 0 else default
    return default


def _keycloak_admin_client() -> KeycloakAdminClient:
    return KeycloakAdminClient(
        base_url=settings.keycloak_url,
        realm=settings.keycloak_realm,
        admin_realm=settings.keycloak_admin_realm,
        admin_client_id=settings.keycloak_admin_client_id,
        admin_username=settings.keycloak_admin_username,
        admin_password=settings.keycloak_admin_password,
        timeout_seconds=max(settings.nilo_timeout_seconds, 30.0),
    )


def _metabase_admin_client() -> MetabaseAdminClient:
    return MetabaseAdminClient(
        base_url=settings.metabase_api_url,
        admin_email=settings.metabase_admin_email,
        admin_password=settings.metabase_admin_password,
        timeout_seconds=max(settings.nilo_timeout_seconds, 30.0),
    )


def _list_admin_users_with_metabase_state() -> list[dict[str, Any]]:
    keycloak_users = _keycloak_admin_client().list_admin_users()
    metabase_users = {
        str(item.get("email") or "").strip().lower(): item
        for item in _metabase_admin_client().list_admin_users()
        if str(item.get("email") or "").strip()
    }
    items: list[dict[str, Any]] = []
    for user in keycloak_users:
        email_key = str(user.get("email") or "").strip().lower()
        metabase_user = metabase_users.get(email_key)
        items.append(
            {
                **user,
                "metabase_synced": metabase_user is not None,
                "metabase_user_id": metabase_user.get("id") if metabase_user else None,
            }
        )
    return items


def _keycloak_openid_url(path: str) -> str:
    return f"{settings.keycloak_url.rstrip('/')}/realms/{settings.keycloak_realm}/protocol/openid-connect/{path.lstrip('/')}"


def _request_keycloak_token(form_fields: dict[str, str]) -> dict[str, Any]:
    payload = {"client_id": settings.keycloak_client_id, **form_fields}
    if settings.keycloak_client_secret:
        payload["client_secret"] = settings.keycloak_client_secret

    try:
        with httpx.Client(timeout=max(settings.nilo_timeout_seconds, 30.0), follow_redirects=True) as client:
            response = client.post(
                _keycloak_openid_url("token"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Keycloak unavailable: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text
        try:
            error_payload = response.json()
        except ValueError:
            error_payload = None
        if isinstance(error_payload, dict):
            detail = str(error_payload.get("error_description") or error_payload.get("error") or detail)
        status_code = 401 if response.status_code in {400, 401} else response.status_code
        raise HTTPException(status_code=status_code, detail=f"Falha ao autenticar no Keycloak: {detail}")

    try:
        token_payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Keycloak returned a non-JSON token payload") from exc

    if not isinstance(token_payload, dict) or not token_payload.get("access_token"):
        raise HTTPException(status_code=502, detail="Keycloak returned an invalid token payload")
    return token_payload


def _slugify_instance_name(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    collapsed = "_".join(part for part in normalized.split("_") if part)
    return collapsed[:80] or "pnp_instance"


def _build_pnp_instance_key(instance_name: str) -> str:
    return f"pnp_{_slugify_instance_name(instance_name)}"


def _build_pnp_connection_key(connection_name: str) -> str:
    return f"pnp_conn_{_slugify_instance_name(connection_name)}"


def _build_pnp_pipeline_key(pipeline_name: str) -> str:
    return f"pnp_pipe_{_slugify_instance_name(pipeline_name)}"


def _normalize_pipeline_schedule(schedule: str | None) -> str | None:
    if schedule is None:
        return None
    normalized = schedule.strip()
    if not normalized:
        return None
    if not croniter.is_valid(normalized):
        raise HTTPException(status_code=422, detail="Invalid pipeline schedule cron expression")
    return normalized


def _load_pnp_powerbi_catalog_or_502() -> dict[str, Any]:
    ttl_seconds = max(float(settings.pnp_catalog_cache_ttl_seconds), 0.0)
    cached_catalog = _PNP_CATALOG_CACHE.get("value")
    loaded_at = float(_PNP_CATALOG_CACHE.get("loaded_at") or 0.0)
    now = monotonic()

    if cached_catalog is not None and ttl_seconds > 0 and (now - loaded_at) < ttl_seconds:
        return cached_catalog

    try:
        with _PNP_CATALOG_CACHE_LOCK:
            cached_catalog = _PNP_CATALOG_CACHE.get("value")
            loaded_at = float(_PNP_CATALOG_CACHE.get("loaded_at") or 0.0)
            now = monotonic()

            if cached_catalog is not None and ttl_seconds > 0 and (now - loaded_at) < ttl_seconds:
                return cached_catalog

            catalog = load_public_microdados_catalog(timeout_seconds=max(float(settings.nilo_timeout_seconds), 30.0))
            _PNP_CATALOG_CACHE["value"] = catalog
            _PNP_CATALOG_CACHE["loaded_at"] = monotonic()
            return catalog
    except Exception as exc:
        stale_catalog = _PNP_CATALOG_CACHE.get("value")
        if stale_catalog is not None:
            return stale_catalog
        raise HTTPException(status_code=502, detail=f"Falha ao consultar o catálogo público de microdados da PNP: {exc}") from exc


def _validate_pnp_selection_against_catalog(
    *,
    selected_years: list[str],
    selected_microdados_types: list[str],
    catalog: dict[str, Any],
) -> None:
    available_years = {str(item).strip() for item in (catalog.get("available_years") or []) if isinstance(item, str)}
    missing_years = [item for item in selected_years if item not in available_years]
    if missing_years:
        raise HTTPException(
            status_code=422,
            detail=f"Anos indisponiveis no catalogo publico da PNP: {', '.join(missing_years)}",
        )

    types_by_year = {
        str(year): {str(item).strip() for item in items if isinstance(item, str)}
        for year, items in dict(catalog.get("types_by_year") or {}).items()
    }
    for year in selected_years:
        missing_types = [item for item in selected_microdados_types if item not in types_by_year.get(year, set())]
        if missing_types:
            raise HTTPException(
                status_code=422,
                detail=f"Tipos de microdados indisponiveis para o ano {year}: {', '.join(missing_types)}",
            )


def _normalize_pnp_selected_downloads(items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, str]]:
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


def _resolve_pnp_selected_downloads(
    *,
    selected_years: list[str],
    selected_microdados_types: list[str],
    catalog: dict[str, Any],
) -> list[dict[str, str]]:
    year_rank = {str(item).strip(): index for index, item in enumerate(catalog.get("available_years") or [])}
    type_rank = {item: index for index, item in enumerate(PNP_MICRODADOS_TYPES)}
    selected_years_set = set(selected_years)
    selected_types_set = set(selected_microdados_types)

    filtered = _normalize_pnp_selected_downloads(
        [
            item
            for item in (catalog.get("items") or [])
            if isinstance(item, dict)
            and str(item.get("ano_base") or "").strip() in selected_years_set
            and str(item.get("tipo_microdados") or "").strip() in selected_types_set
        ]
    )
    filtered.sort(
        key=lambda item: (
            year_rank.get(item["ano_base"], len(year_rank)),
            type_rank.get(item["tipo_microdados"], 999),
            item["microdados_url"],
        )
    )

    expected_pairs = {(year, microdados_type) for year in selected_years for microdados_type in selected_microdados_types}
    resolved_pairs = {(item["ano_base"], item["tipo_microdados"]) for item in filtered}
    missing_pairs = sorted(expected_pairs - resolved_pairs)
    if missing_pairs:
        detail = ", ".join(f"{year} / {microdados_type}" for year, microdados_type in missing_pairs)
        raise HTTPException(
            status_code=422,
            detail=f"O catálogo público nao expôs links de download para o recorte selecionado: {detail}",
        )

    return filtered


def _build_pnp_connection_payload(
    connection_key: str,
    connection_name: str,
    page_url: str,
) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "mode": "powerbi_microdados",
        "entity_type": PNP_CONNECTION_ENTITY,
        "connection_key": connection_key,
        "connection_name": connection_name,
        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
        "source_path": "powerbi_microdados",
    }

    return {
        "endpoint_key": f"{connection_key}__connection",
        "description": f"{connection_name} - conexao PNP",
        "page_url": page_url,
        "api_endpoint_url": None,
        "csv_url": None,
        "dictionary_url": None,
        "request_params": request_params,
    }


def _build_pnp_pipeline_payload(
    pipeline_key: str,
    pipeline_name: str,
    connection_key: str,
    connection_name: str,
    page_url: str,
    selected_years: list[str],
    selected_microdados_types: list[str],
    selected_downloads: list[dict[str, str]],
    schedule: str | None,
) -> dict[str, Any]:
    request_params: dict[str, Any] = {
        "mode": "powerbi_microdados",
        "entity_type": PNP_PIPELINE_ENTITY,
        "pipeline_key": pipeline_key,
        "pipeline_name": pipeline_name,
        "connection_key": connection_key,
        "connection_name": connection_name,
        "instance_key": pipeline_key,
        "instance_name": pipeline_name,
        "selected_years": list(selected_years),
        "selected_microdados_types": list(selected_microdados_types),
        "selected_downloads": _normalize_pnp_selected_downloads(selected_downloads),
        "selected_source_label": PNP_POWERBI_SOURCE_LABEL,
        "selected_source_group": PNP_POWERBI_GROUP_LABEL,
        "source_path": "powerbi_microdados",
    }
    if schedule and schedule.strip():
        request_params["schedule"] = schedule.strip()

    return {
        "endpoint_key": f"{pipeline_key}__powerbi_microdados",
        "description": f"{pipeline_name} - {PNP_POWERBI_SOURCE_LABEL}",
        "page_url": page_url,
        "api_endpoint_url": None,
        "csv_url": None,
        "dictionary_url": None,
        "request_params": request_params,
    }


def _row_entity_type(request_params: dict[str, Any]) -> str:
    entity_type = str(request_params.get("entity_type") or "").strip().lower()
    if entity_type in {PNP_CONNECTION_ENTITY, PNP_PIPELINE_ENTITY}:
        return entity_type
    if request_params.get("selected_years") or request_params.get("selected_microdados_types"):
        return PNP_PIPELINE_ENTITY
    return PNP_CONNECTION_ENTITY


def _is_deleted_row(request_params: dict[str, Any]) -> bool:
    return bool(request_params.get("deleted"))


def _group_pnp_connections(
    rows: list[dict[str, Any]],
    *,
    include_deleted: bool = False,
    include_virtual: bool = True,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        request_params = dict(row.get("request_params") or {})
        if str(request_params.get("mode") or "").strip().lower() != "powerbi_microdados":
            continue
        if not include_deleted and _is_deleted_row(request_params):
            continue

        entity_type = _row_entity_type(request_params)
        if entity_type == PNP_CONNECTION_ENTITY:
            connection_key = str(request_params.get("connection_key") or "").strip()
            connection_name = str(request_params.get("connection_name") or connection_key).strip()
        elif include_virtual:
            connection_key = str(request_params.get("connection_key") or request_params.get("instance_key") or "").strip()
            connection_name = str(
                request_params.get("connection_name") or request_params.get("instance_name") or connection_key
            ).strip()
        else:
            continue

        if not connection_key:
            continue

        connection = grouped.setdefault(
            connection_key,
            {
                "connection_key": connection_key,
                "connection_name": connection_name or connection_key,
                "connector_id": "pnp",
                "page_url": row.get("page_url"),
                "is_active": False,
                "validation_status": "pending",
                "validation_message": "Conexao sem validacao recente.",
                "pipeline_count": 0,
                "pipelines": [],
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
        )

        connection["is_active"] = bool(connection["is_active"] or row.get("is_active"))
        if row.get("page_url"):
            connection["page_url"] = row.get("page_url")
        if row.get("updated_at") and (connection["updated_at"] is None or row.get("updated_at") > connection["updated_at"]):
            connection["updated_at"] = row.get("updated_at")

        if entity_type == PNP_PIPELINE_ENTITY:
            pipeline_key = str(request_params.get("pipeline_key") or request_params.get("instance_key") or "").strip()
            pipeline_id = str(request_params.get("pipeline_id") or "").strip()
            pipeline_name = str(request_params.get("pipeline_name") or request_params.get("instance_name") or pipeline_key).strip()
            if pipeline_key and pipeline_key not in {item["pipeline_key"] for item in connection["pipelines"]}:
                connection["pipelines"].append(
                    {
                        "pipeline_id": pipeline_id or None,
                        "pipeline_key": pipeline_key,
                        "pipeline_name": pipeline_name or pipeline_key,
                    }
                )

    for connection in grouped.values():
        connection["pipelines"].sort(key=lambda item: item["pipeline_name"].lower())
        connection["pipeline_count"] = len(connection["pipelines"])

    return sorted(grouped.values(), key=lambda item: item["connection_name"].lower())


def _group_pnp_instances(rows: list[dict[str, Any]], *, include_deleted: bool = False) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        request_params = dict(row.get("request_params") or {})
        ingestion_mode = str(request_params.get("mode") or "").strip().lower()
        if ingestion_mode != "powerbi_microdados":
            continue
        if _row_entity_type(request_params) != PNP_PIPELINE_ENTITY:
            continue
        if not include_deleted and _is_deleted_row(request_params):
            continue

        instance_key = str(request_params.get("pipeline_key") or request_params.get("instance_key") or "").strip()
        if not instance_key:
            continue

        instance = grouped.setdefault(
            instance_key,
            {
                "pipeline_id": str(request_params.get("pipeline_id") or "").strip() or None,
                "instance_key": instance_key,
                "instance_name": str(request_params.get("pipeline_name") or request_params.get("instance_name") or instance_key),
                "connector_id": "pnp",
                "ingestion_mode": "powerbi_microdados",
                "connection_key": str(request_params.get("connection_key") or instance_key),
                "connection_name": str(
                    request_params.get("connection_name") or request_params.get("instance_name") or instance_key
                ),
                "schedule": request_params.get("schedule"),
                "is_active": False,
                "source_count": 0,
                "selection_count": 0,
                "download_count": 0,
                "selected_years": [],
                "selected_microdados_types": [],
                "selected_downloads": [],
                "selected_endpoints": [],
                "endpoint_tables": [],
                "endpoints": [],
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
        )

        selected_years = [
            str(item).strip()
            for item in (request_params.get("selected_years") or [])
            if isinstance(item, str) and item.strip()
        ]
        selected_microdados_types = [
            str(item).strip()
            for item in (request_params.get("selected_microdados_types") or [])
            if isinstance(item, str) and item.strip()
        ]
        selected_downloads = _normalize_pnp_selected_downloads(request_params.get("selected_downloads"))
        selected_endpoints = [
            str(item).strip()
            for item in (request_params.get("selected_endpoints") or [])
            if isinstance(item, str) and item.strip()
        ]
        endpoint_tables = [
            dict(item)
            for item in (request_params.get("endpoint_tables") or [])
            if isinstance(item, dict)
        ]

        instance["is_active"] = bool(instance["is_active"] or row.get("is_active"))
        if request_params.get("pipeline_id"):
            instance["pipeline_id"] = str(request_params.get("pipeline_id"))
        if request_params.get("schedule"):
            instance["schedule"] = request_params.get("schedule")
        if row.get("updated_at") and (instance["updated_at"] is None or row.get("updated_at") > instance["updated_at"]):
            instance["updated_at"] = row.get("updated_at")

        instance["selected_years"] = sorted({*instance["selected_years"], *selected_years}, reverse=True)
        instance["selected_microdados_types"] = sorted(
            {*instance["selected_microdados_types"], *selected_microdados_types},
            key=lambda item: (PNP_MICRODADOS_TYPES.index(item) if item in PNP_MICRODADOS_TYPES else 999, item),
        )
        instance["selected_downloads"] = _normalize_pnp_selected_downloads([*instance["selected_downloads"], *selected_downloads])
        instance["selected_endpoints"] = sorted({*instance["selected_endpoints"], *selected_endpoints})
        existing_endpoint_keys = {str(item.get("endpoint_key") or "") for item in instance["endpoint_tables"]}
        for endpoint_table in endpoint_tables:
            endpoint_key = str(endpoint_table.get("endpoint_key") or "").strip()
            if endpoint_key and endpoint_key not in existing_endpoint_keys:
                instance["endpoint_tables"].append(endpoint_table)
                existing_endpoint_keys.add(endpoint_key)
        instance["endpoints"].append(
            {
                "id": row.get("id"),
                "endpoint_key": row.get("endpoint_key"),
                "page_url": row.get("page_url"),
                "is_active": row.get("is_active"),
                "selected_years": selected_years,
                "selected_microdados_types": selected_microdados_types,
                "selected_downloads": selected_downloads,
                "source_label": PNP_POWERBI_SOURCE_LABEL,
                "source_group": PNP_POWERBI_GROUP_LABEL,
                "source_path": "powerbi_microdados",
            }
        )

    for instance in grouped.values():
        instance["endpoint_tables"].sort(key=lambda item: str(item.get("endpoint_key") or ""))
        instance["endpoints"].sort(key=lambda item: item["endpoint_key"])
        instance["download_count"] = len(instance["selected_downloads"])
        instance["selection_count"] = instance["download_count"] or (
            len(instance["selected_years"]) * len(instance["selected_microdados_types"])
        )
        instance["source_count"] = instance["selection_count"]

    return sorted(grouped.values(), key=lambda item: item["instance_name"].lower())


def _load_pnp_instance_rows(instance_key: str, *, include_deleted: bool = False) -> list[dict[str, Any]]:
    try:
        return pnp_instance_repository.load_instance_rows(
            _db_connect,
            instance_key,
            include_deleted=include_deleted,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="PNP instance not found") from exc


def _load_all_pnp_rows(*, include_deleted: bool = False) -> list[dict[str, Any]]:
    return pnp_instance_repository.load_all_rows(_db_connect, include_deleted=include_deleted)


def _load_pnp_connection(connection_key: str) -> dict[str, Any]:
    try:
        row = pnp_instance_repository.load_connection(_db_connect, connection_key)
    except pnp_instance_repository.PnpConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PNP connection not found") from exc

    grouped = _group_pnp_connections([row], include_virtual=False)
    if grouped:
        return grouped[0]
    raise HTTPException(status_code=404, detail="PNP connection not found")


def _connection_health_snapshot() -> dict[str, str]:
    cached_catalog = _PNP_CATALOG_CACHE.get("value")
    if isinstance(cached_catalog, dict):
        page_url = str(cached_catalog.get("page_url") or DEFAULT_PNP_POWERBI_REPORT_URL)
        return {
            "validation_status": "validated",
            "validation_message": "Conector PNP validado a partir do catalogo em cache.",
            "page_url": page_url,
        }
    return {
        "validation_status": "pending",
        "validation_message": "A validacao online ainda nao foi executada nesta sessao da API.",
        "page_url": DEFAULT_PNP_POWERBI_REPORT_URL,
    }


def _enrich_connections_with_health(connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshot = _connection_health_snapshot()
    items: list[dict[str, Any]] = []
    for connection in connections:
        items.append(
            {
                **connection,
                "validation_status": snapshot["validation_status"],
                "validation_message": snapshot["validation_message"],
                "page_url": connection.get("page_url") or snapshot["page_url"],
            }
        )
    return items


def _load_pnp_instance(instance_key: str) -> dict[str, Any]:
    grouped = _group_pnp_instances(_load_pnp_instance_rows(instance_key))
    if not grouped:
        raise HTTPException(status_code=404, detail="PNP instance not found")
    return grouped[0]


def _delete_pnp_instance(instance_key: str) -> dict[str, Any]:
    try:
        return pnp_instance_repository.delete_instance(_db_connect, instance_key=instance_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="PNP instance not found") from exc


def _delete_pnp_connection(connection_key: str) -> dict[str, Any]:
    try:
        return pnp_instance_repository.delete_connection(_db_connect, connection_key=connection_key)
    except pnp_instance_repository.PnpConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PNP connection not found") from exc


def _safe_parse_json_text(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _describe_pnp_diagnostic(item: dict[str, Any]) -> dict[str, Any]:
    status = str(item.get("status") or "missing").strip().lower()
    raw_record_count = _coerce_int(item.get("raw_record_count")) or 0
    staging_record_count = _coerce_int(item.get("staging_record_count")) or 0
    curated_record_count = _coerce_int(item.get("curated_record_count")) or 0

    if curated_record_count > 0:
        return {
            "operational_status": "curated_ready",
            "severity": "ready",
            "message": "A pipeline ja publicou o endpoint na camada curated.",
        }

    if staging_record_count > 0:
        return {
            "operational_status": "staging_ready",
            "severity": "ready",
            "message": "O endpoint ja foi deduplicado e materializado em staging.",
        }

    if status in {"running", "queued"}:
        return {
            "operational_status": "running",
            "severity": "pending",
            "message": "O endpoint esta em processamento na execucao atual.",
        }

    if status in {"ok", "success", "cataloged"}:
        if raw_record_count > 0:
            return {
                "operational_status": "raw_loaded",
                "severity": "ready",
                "message": "Microdados públicos validados e persistidos em raw.",
            }
        return {
            "operational_status": "validated",
            "severity": "ready",
            "message": "Catálogo público resolvido e pronto para ingestão.",
        }

    if status == "error":
        return {
            "operational_status": "error",
            "severity": "danger",
            "message": "A leitura dos microdados públicos falhou.",
        }

    return {
        "operational_status": "missing",
        "severity": "pending",
        "message": "A fonte ainda nao produziu manifesto recente.",
    }


def _summarize_pnp_diagnostics(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total": len(diagnostics),
        "ready": 0,
        "attention": 0,
        "missing": 0,
        "raw_loaded": 0,
        "validated": 0,
        "last_updated_at": None,
    }

    latest_timestamp: datetime | None = None
    for item in diagnostics:
        operational_status = str(item.get("operational_status") or "missing")
        if operational_status == "raw_loaded":
            summary["raw_loaded"] += 1
            summary["ready"] += 1
        elif operational_status == "validated":
            summary["validated"] += 1
            summary["ready"] += 1
        elif operational_status == "missing":
            summary["missing"] += 1
        else:
            summary["attention"] += 1

        updated_at = _parse_iso_datetime(item.get("updated_at"))
        if updated_at and (latest_timestamp is None or updated_at > latest_timestamp):
            latest_timestamp = updated_at
            summary["last_updated_at"] = item.get("updated_at")

    return summary


def _load_pnp_instance_diagnostics(instance_key: str) -> list[dict[str, Any]]:
    with _db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH pipeline_endpoints AS (
              SELECT
                pe.instance_key,
                pe.endpoint_key,
                et.endpoint_name,
                et.tipo_microdados
              FROM raw.pnp_pipeline_endpoints pe
              JOIN raw.pnp_endpoint_tables et
                ON et.endpoint_key = pe.endpoint_key
              WHERE pe.instance_key = %s
                AND pe.is_active = TRUE
                AND et.is_active = TRUE
            ),
            endpoint_runs AS (
              SELECT
                pe.endpoint_key,
                pe.endpoint_name,
                pe.tipo_microdados,
                r.run_id,
                r.status AS run_status,
                r.started_at,
                r.finished_at,
                d.microdados_url AS source_url,
                d.status AS download_status,
                d.error_message AS download_error,
                d.row_count_raw,
                COALESCE(d.finished_at, d.started_at, r.finished_at, r.started_at) AS updated_at,
                CASE pe.endpoint_key
                  WHEN 'matriculas' THEN (SELECT COUNT(*) FROM raw.pnp_matriculas_src src WHERE src.run_id = r.run_id)
                  WHEN 'eficiencia_academica' THEN (SELECT COUNT(*) FROM raw.pnp_eficiencia_academica_src src WHERE src.run_id = r.run_id)
                  WHEN 'servidores' THEN (SELECT COUNT(*) FROM raw.pnp_servidores_src src WHERE src.run_id = r.run_id)
                  WHEN 'financeiro' THEN (SELECT COUNT(*) FROM raw.pnp_financeiro_src src WHERE src.run_id = r.run_id)
                  ELSE 0
                END AS raw_record_count,
                CASE pe.endpoint_key
                  WHEN 'matriculas' THEN (SELECT COUNT(*) FROM staging.pnp_matriculas src WHERE src.run_id = r.run_id)
                  WHEN 'eficiencia_academica' THEN (SELECT COUNT(*) FROM staging.pnp_eficiencia_academica src WHERE src.run_id = r.run_id)
                  WHEN 'servidores' THEN (SELECT COUNT(*) FROM staging.pnp_servidores src WHERE src.run_id = r.run_id)
                  WHEN 'financeiro' THEN (SELECT COUNT(*) FROM staging.pnp_financeiro src WHERE src.run_id = r.run_id)
                  ELSE 0
                END AS staging_record_count,
                CASE pe.endpoint_key
                  WHEN 'matriculas' THEN (SELECT COUNT(*) FROM curated.vw_pnp_matriculas_perfil src WHERE src.run_id = r.run_id)
                  WHEN 'eficiencia_academica' THEN (SELECT COUNT(*) FROM curated.vw_pnp_eficiencia_situacao src WHERE src.run_id = r.run_id)
                  WHEN 'servidores' THEN (SELECT COUNT(*) FROM curated.vw_pnp_servidores_quadro src WHERE src.run_id = r.run_id)
                  WHEN 'financeiro' THEN (SELECT COUNT(*) FROM curated.vw_pnp_financeiro_execucao src WHERE src.run_id = r.run_id)
                  ELSE 0
                END AS curated_record_count,
                (
                  SELECT COUNT(*)
                  FROM raw.pnp_catalog_entries c
                  WHERE c.run_id = r.run_id
                    AND c.tipo_microdados = pe.tipo_microdados
                ) AS catalog_entry_count,
                ROW_NUMBER() OVER (
                  PARTITION BY pe.endpoint_key
                  ORDER BY COALESCE(d.finished_at, d.started_at, r.finished_at, r.started_at) DESC, r.run_id DESC
                ) AS row_num
              FROM pipeline_endpoints pe
              JOIN raw.pnp_runs r
                ON r.instance_key = pe.instance_key
              LEFT JOIN LATERAL (
                SELECT
                  microdados_url,
                  status,
                  error_message,
                  row_count_raw,
                  started_at,
                  finished_at
                FROM raw.pnp_downloads d
                WHERE d.run_id = r.run_id
                  AND d.tipo_microdados = pe.tipo_microdados
                ORDER BY COALESCE(d.finished_at, d.started_at) DESC, d.download_id DESC
                LIMIT 1
              ) d ON TRUE
              WHERE d.microdados_url IS NOT NULL
                 OR EXISTS (
                   SELECT 1
                   FROM raw.pnp_catalog_entries c
                   WHERE c.run_id = r.run_id
                     AND c.tipo_microdados = pe.tipo_microdados
                 )
            )
            SELECT
              pe.endpoint_key,
              pe.endpoint_name,
              pe.tipo_microdados,
              er.run_id AS diagnostic_run_id,
              er.source_url,
              er.updated_at,
              er.run_status,
              er.download_status,
              er.download_error,
              er.row_count_raw,
              er.raw_record_count,
              er.staging_record_count,
              er.curated_record_count,
              er.catalog_entry_count
            FROM pipeline_endpoints pe
            LEFT JOIN endpoint_runs er
              ON er.endpoint_key = pe.endpoint_key
             AND er.row_num = 1
            ORDER BY pe.endpoint_key
            """,
            (instance_key,),
        )
        rows = [dict(row) for row in cur.fetchall()]

    items: list[dict[str, Any]] = []
    for row in rows:
        diagnostic = {
            "endpoint_key": row.get("endpoint_key"),
            "endpoint_name": row.get("endpoint_name"),
            "tipo_microdados": row.get("tipo_microdados"),
            "ingestion_mode": "powerbi_microdados",
            "source_label": PNP_POWERBI_SOURCE_LABEL,
            "source_group": PNP_POWERBI_GROUP_LABEL,
            "source_path": "powerbi_microdados",
            "run_id": row.get("diagnostic_run_id"),
            "source_url": row.get("source_url"),
            "updated_at": row.get("updated_at"),
            "status": row.get("download_status") or ("cataloged" if _coerce_int(row.get("catalog_entry_count")) else "missing"),
            "row_count": row.get("row_count_raw") or row.get("raw_record_count"),
            "selected_years": [],
            "selected_microdados_types": [row.get("tipo_microdados")] if row.get("tipo_microdados") else [],
            "downloads": [],
            "raw_run_id": row.get("diagnostic_run_id"),
            "raw_record_count": row.get("raw_record_count"),
            "staging_record_count": row.get("staging_record_count"),
            "curated_record_count": row.get("curated_record_count"),
            "raw_updated_at": row.get("updated_at"),
            "error": row.get("download_error") if row.get("run_status") != "success" else None,
        }
        diagnostic.update(_describe_pnp_diagnostic(diagnostic))
        items.append(diagnostic)

    return items


def _build_pnp_runtime_event_message(task_id: str, status: str, details: dict[str, Any], error_message: str | None) -> str:
    if error_message:
        return error_message
    if details.get("error"):
        return str(details["error"])
    task_meta = PNP_RUNTIME_TASK_META.get(task_id, {})
    if task_meta.get("message"):
        return str(task_meta["message"])
    return str(status or task_id or "unknown").replace("_", " ")


def _load_pnp_instance_run_events(instance_key: str, limit: int = 12) -> list[dict[str, Any]]:
    with _db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              steps.run_id,
              steps.airflow_task_id,
              steps.status,
              steps.started_at,
              steps.finished_at,
              steps.records_affected,
              steps.error_message,
              steps.details_json
            FROM raw.pnp_run_steps steps
            JOIN raw.pnp_runs runs
              ON runs.run_id = steps.run_id
            WHERE runs.instance_key = %s
              AND steps.airflow_task_id <> 'register_run'
            ORDER BY COALESCE(steps.finished_at, steps.started_at) DESC NULLS LAST, steps.step_id DESC
            LIMIT %s
            """,
            (instance_key, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]

    items: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").strip()
        task_id = str(row.get("airflow_task_id") or "")
        event_meta = PNP_RUNTIME_TASK_META.get(task_id, {})
        details = dict(row.get("details_json") or {})
        state = "neutral"
        if status == "success":
            state = "success"
        elif status in {"failed", "upstream_failed"}:
            state = "failed"
        elif status in {"running", "queued"}:
            state = "pending"
        items.append(
            {
                "run_id": row.get("run_id"),
                "status": status,
                "stage": event_meta.get("stage", task_id or "unknown"),
                "stage_label": event_meta.get("stage_label", str(task_id or status).replace("_", " ")),
                "state": state,
                "message": _build_pnp_runtime_event_message(task_id, status, details, row.get("error_message")),
                "timestamp": row.get("finished_at") or row.get("started_at"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
                "extracted_count": row.get("records_affected") if task_id == "extract_raw" else None,
                "loaded_count": row.get("records_affected"),
                "endpoint_count": _coerce_int(details.get("endpoint_count")),
                "asset_count": _coerce_int(details.get("asset_count")),
                "raw_count": _coerce_int(details.get("raw_count")) or _coerce_int(details.get("loaded_count")),
                "download_count": _coerce_int(details.get("download_count")) or _coerce_int(details.get("selected_download_count")),
                "error": row.get("error_message") or details.get("error"),
            }
        )

    return items


def _build_pnp_ingestion_summary(run_events: list[dict[str, Any]]) -> dict[str, Any]:
    if not run_events:
        return {
            "status": "not_started",
            "message": "A instância ainda não gerou eventos recentes de extração ou validação.",
            "last_event_at": None,
            "latest_success_at": None,
            "latest_success_stage": None,
            "stages": {},
        }

    latest_by_stage: dict[str, dict[str, Any]] = {}
    latest_success: dict[str, Any] | None = None
    latest_issue: dict[str, Any] | None = None
    latest_event = run_events[0]

    for item in run_events:
        stage = str(item.get("stage") or "unknown")
        latest_by_stage.setdefault(stage, item)
        if latest_success is None and item.get("state") == "success":
            latest_success = item
        if latest_issue is None and item.get("state") == "failed":
            latest_issue = item

    curated_event = latest_by_stage.get("build_curated_views")
    staging_event = latest_by_stage.get("materialize_staging")
    raw_event = latest_by_stage.get("extract_raw")

    if latest_event.get("state") == "pending":
        status = "running"
        message = "A instância tem uma execucao ativa no momento."
    elif curated_event and curated_event.get("state") == "success":
        status = "curated_ready"
        message = "A instância já publicou dados para consumo em curated."
    elif staging_event and staging_event.get("state") == "success":
        status = "staging_ready"
        message = "A instância já deduplicou e materializou dados em staging."
    elif raw_event and raw_event.get("state") == "success":
        status = "raw_loaded"
        message = "A instância já carregou microdados na camada raw."
    elif latest_issue:
        status = "failed"
        message = str(latest_issue.get("message") or "Há uma falha operacional recente na instância.")
    else:
        status = "pending"
        message = "A instância tem atividade recente, mas ainda sem materialização consolidada."

    return {
        "status": status,
        "message": message,
        "last_event_at": run_events[0].get("timestamp"),
        "latest_success_at": latest_success.get("timestamp") if latest_success else None,
        "latest_success_stage": latest_success.get("stage") if latest_success else None,
        "stages": latest_by_stage,
    }


def _load_pnp_instance_integrations(instance_key: str, limit: int = 10) -> list[dict[str, Any]]:
    with _db_connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH endpoint_counts AS (
              SELECT
                instance_key,
                COUNT(*) AS endpoint_count
              FROM raw.pnp_pipeline_endpoints
              WHERE instance_key = %s
                AND is_active = TRUE
              GROUP BY instance_key
            ),
            download_counts AS (
              SELECT
                run_id,
                COUNT(*) AS asset_count
              FROM raw.pnp_downloads
              GROUP BY run_id
            ),
            package_counts AS (
              SELECT
                run_id,
                COUNT(*) AS package_count
              FROM raw.pnp_run_packages
              GROUP BY run_id
            )
            SELECT
              runs.run_id,
              CASE
                WHEN COALESCE(runs.run_summary_json->>'operation', 'sync') = 'validate' THEN 'source_validation'
                ELSE 'pipeline_sync'
              END AS integration_type,
              runs.started_at,
              runs.finished_at,
              COALESCE(download_counts.asset_count, 0) AS asset_count,
              COALESCE(endpoint_counts.endpoint_count, 0) AS endpoint_count,
              runs.raw_record_count AS record_count,
              COALESCE(staging.deduplicated_record_count, 0) AS staging_record_count,
              COALESCE(package_counts.package_count, 0) AS package_count,
              runs.status
            FROM raw.pnp_runs runs
            LEFT JOIN endpoint_counts
              ON endpoint_counts.instance_key = runs.instance_key
            LEFT JOIN download_counts
              ON download_counts.run_id = runs.run_id
            LEFT JOIN package_counts
              ON package_counts.run_id = runs.run_id
            LEFT JOIN staging.pnp_ingestion_runs staging
              ON staging.run_id = runs.run_id
            WHERE runs.instance_key = %s
            ORDER BY COALESCE(runs.finished_at, runs.started_at) DESC NULLS LAST
            LIMIT %s
            """,
            (instance_key, instance_key, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _persist_pnp_instance_settings(
    instance_key: str,
    *,
    schedule: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    try:
        pnp_instance_repository.update_instance_settings(
            _db_connect,
            instance_key=instance_key,
            schedule=schedule,
            is_active=is_active,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="PNP instance not found") from exc
    return _load_pnp_instance(instance_key)


def _airflow_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.airflow_api_url:
        raise HTTPException(status_code=500, detail="AIRFLOW_API_URL not configured")

    target_url = f"{settings.airflow_api_url.rstrip('/')}{path}"
    try:
        with httpx.Client(
            timeout=max(settings.nilo_timeout_seconds, 30.0),
            follow_redirects=True,
            auth=(settings.airflow_admin_user, settings.airflow_admin_password),
        ) as client:
            response = client.request(method, target_url, json=payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Airflow unavailable: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    if not response.content:
        return {}
    return response.json()


def _build_airflow_run_id(dag_id: str, instance_key: str, operation: str | None = None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = operation.strip().lower() if isinstance(operation, str) and operation.strip() else "run"
    return f"{dag_id}__{suffix}__{timestamp}"


def _build_pnp_instance_dag_id(instance: dict[str, Any]) -> str:
    request_params = dict(instance.get("request_params") or {})
    pipeline_id = str(instance.get("pipeline_id") or request_params.get("pipeline_id") or "").strip() or None
    return pnp_dag_provisioner.build_pipeline_dag_id(
        str(instance["instance_key"]),
        pipeline_id,
    )


def _wait_for_airflow_dag(
    dag_id: str,
    *,
    timeout_seconds: float = 90.0,
    poll_interval_seconds: float = 1.0,
) -> None:
    if not settings.airflow_api_url:
        raise HTTPException(status_code=500, detail="AIRFLOW_API_URL not configured")

    target_url = f"{settings.airflow_api_url.rstrip('/')}/api/v1/dags/{dag_id}"
    deadline = monotonic() + max(timeout_seconds, poll_interval_seconds)
    last_error: str | None = None

    while monotonic() < deadline:
        try:
            with httpx.Client(
                timeout=max(settings.nilo_timeout_seconds, 30.0),
                follow_redirects=True,
                auth=(settings.airflow_admin_user, settings.airflow_admin_password),
            ) as client:
                response = client.get(target_url)
        except Exception as exc:
            last_error = f"Airflow unavailable: {exc}"
            sleep(poll_interval_seconds)
            continue

        if response.status_code == 200:
            return

        if response.status_code == 404:
            last_error = f"DAG {dag_id} ainda nao foi registrada no Airflow."
            sleep(poll_interval_seconds)
            continue

        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    raise HTTPException(
        status_code=502,
        detail=last_error or f"Airflow nao registrou a DAG {dag_id} dentro do prazo esperado.",
    )


def _trigger_pnp_airflow_dag(dag_id: str, instance_key: str, *, operation: str) -> dict[str, Any]:
    _load_pnp_instance(instance_key)
    dag_run = _airflow_request(
        "POST",
        f"/api/v1/dags/{dag_id}/dagRuns",
        {
            "dag_run_id": _build_airflow_run_id(dag_id, instance_key, operation),
            "conf": {
                "instance_key": instance_key,
                "operation": operation,
                "requested_by": f"api.{operation}",
            },
        },
    )
    return {
        "dag_id": dag_id,
        "instance_key": instance_key,
        "dag_run": dag_run,
    }


def _load_pnp_instance_dag_runs(instance_key: str, limit: int = 10) -> list[dict[str, Any]]:
    instance = _load_pnp_instance(instance_key)
    items: list[dict[str, Any]] = []
    request_limit = max(limit * 4, 20)
    dag_id = _build_pnp_instance_dag_id(instance)
    response = _airflow_request("GET", f"/api/v1/dags/{dag_id}/dagRuns?limit={request_limit}")
    for row in response.get("dag_runs") or []:
        conf = row.get("conf") or {}
        dag_run_id = str(row.get("dag_run_id") or "")
        if conf.get("instance_key") != instance_key and f"__{instance_key}__" not in dag_run_id:
            continue
        items.append(
            {
                "dag_id": dag_id,
                "dag_run_id": dag_run_id,
                "state": row.get("state"),
                "run_type": row.get("run_type"),
                "logical_date": row.get("logical_date"),
                "queued_at": row.get("queued_at"),
                "start_date": row.get("start_date"),
                "end_date": row.get("end_date"),
                "note": row.get("note"),
                "conf": conf,
            }
        )

    items.sort(
        key=lambda item: item.get("end_date") or item.get("start_date") or item.get("queued_at") or item.get("logical_date") or "",
        reverse=True,
    )
    return items[:limit]


@app.get("/api/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/api/admin/login")
def admin_login(payload: AdminLoginRequest) -> dict[str, Any]:
    return _request_keycloak_token(
        {
            "grant_type": "password",
            "username": payload.username.strip(),
            "password": payload.password,
        }
    )


@app.post("/api/admin/refresh")
def admin_refresh(payload: AdminRefreshRequest) -> dict[str, Any]:
    return _request_keycloak_token(
        {
            "grant_type": "refresh_token",
            "refresh_token": payload.refresh_token,
        }
    )


@app.get("/api/admin/whoami")
def whoami(payload: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"claims": payload}


@app.get("/api/admin/settings/llm")
def get_admin_llm_settings(payload: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    config = _effective_vanna_llm_settings_for_user(payload)
    return {
        "config": _serialize_vanna_llm_settings_public(config),
        "status": _vanna_provider_status(config),
    }


@app.get("/api/admin/settings/llm/status")
def get_admin_llm_settings_status(payload: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return _vanna_provider_status(_effective_vanna_llm_settings_for_user(payload))


@app.patch("/api/admin/settings/llm")
def update_admin_llm_settings(
    payload: AdminLlmSettingsUpdateRequest,
    admin_payload: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    config = _persist_vanna_llm_settings(payload, admin_payload)
    return {
        "config": _serialize_vanna_llm_settings_public(config),
        "status": _vanna_provider_status(config),
    }


@app.get("/api/admin/users")
def list_admin_users(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"items": _list_admin_users_with_metabase_state()}


@app.post("/api/admin/users")
def create_admin_user(
    payload: AdminUserCreateRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    keycloak_client = _keycloak_admin_client()
    metabase_client = _metabase_admin_client()
    username = payload.username.strip()
    email = payload.email.strip()
    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()

    created = keycloak_client.create_admin_user(
        username=username,
        email=email,
        password=payload.password,
        first_name=first_name,
        last_name=last_name,
        enabled=payload.enabled,
    )
    try:
        metabase_user = metabase_client.create_admin_user(
            email=email,
            password=payload.password,
            first_name=first_name,
            last_name=last_name,
        )
    except Exception as exc:
        rollback_error: str | None = None
        try:
            keycloak_client.delete_user(str(created["id"]))
        except Exception as rollback_exc:  # pragma: no cover - defensive rollback
            rollback_error = str(getattr(rollback_exc, "detail", rollback_exc))
        detail = str(getattr(exc, "detail", exc))
        if rollback_error:
            detail = f"{detail}. Keycloak rollback failed: {rollback_error}"
        raise HTTPException(status_code=502, detail=detail) from exc

    return {
        "user": {
            **created,
            "metabase_synced": True,
            "metabase_user_id": metabase_user.get("id"),
        }
    }


@app.post("/api/admin/users/{user_id}/metabase-sync")
def sync_admin_user_metabase(
    user_id: str,
    req: AdminUserMetabaseSyncRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    keycloak_client = _keycloak_admin_client()
    metabase_client = _metabase_admin_client()
    target = keycloak_client.get_admin_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin user not found in Keycloak")

    email = str(target.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=409, detail="Admin user has no email for Metabase sync")

    existing = metabase_client.find_user_by_email(email)
    if existing:
        return {
            "user": {
                **target,
                "metabase_synced": True,
                "metabase_user_id": existing.get("id"),
            },
            "created": False,
        }

    metabase_user = metabase_client.create_admin_user(
        email=email,
        password=req.password,
        first_name=str(target.get("first_name") or ""),
        last_name=str(target.get("last_name") or ""),
    )
    return {
        "user": {
            **target,
            "metabase_synced": True,
            "metabase_user_id": metabase_user.get("id"),
        },
        "created": True,
    }


@app.delete("/api/admin/users/{user_id}")
def delete_admin_user(
    user_id: str,
    payload: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    if str(payload.get("sub") or "") == user_id:
        raise HTTPException(status_code=409, detail="The current admin user cannot delete itself")
    keycloak_client = _keycloak_admin_client()
    metabase_client = _metabase_admin_client()
    target = keycloak_client.get_admin_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin user not found in Keycloak")

    email = str(target.get("email") or "").strip()
    metabase_user = metabase_client.find_user_by_email(email) if email else None
    if metabase_user and metabase_user.get("id") is not None:
        metabase_client.delete_user(metabase_user["id"])

    keycloak_client.delete_user(user_id)
    return {
        "deleted": True,
        "user_id": user_id,
        "email": email,
        "metabase_deleted": bool(metabase_user),
    }


@app.get("/api/admin/connector-definitions/pnp")
def get_pnp_connector_definition(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    catalog = _load_pnp_powerbi_catalog_or_502()
    return {
        "connector_id": "pnp",
        "internal_connector_id": PNP_INTERNAL_CONNECTOR_ID,
        "label": "Programa Nilo Pecanha",
        "ingestion_mode": "powerbi_microdados",
        "powerbi_report_url": catalog["page_url"],
        "selection_catalog": {
            "available_years": catalog["available_years"],
            "available_microdados_types": catalog["available_microdados_types"],
            "types_by_year": catalog["types_by_year"],
            "items": catalog["items"],
        },
        "sources": [],
    }


@app.get("/api/admin/connections/pnp")
def list_pnp_connections(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    rows = _load_all_pnp_rows()
    return {"items": _enrich_connections_with_health(_group_pnp_connections(rows))}


@app.get("/api/admin/connections/pnp/{connection_key}")
def get_pnp_connection(connection_key: str, _: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    connection = _enrich_connections_with_health([_load_pnp_connection(connection_key)])[0]
    pipelines = [item for item in _group_pnp_instances(_load_all_pnp_rows()) if item.get("connection_key") == connection_key]
    return {
        "connection": connection,
        "pipelines": pipelines,
    }


@app.post("/api/admin/connections/pnp")
def create_pnp_connection(
    payload: PnpConnectionCreateRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    catalog = _load_pnp_powerbi_catalog_or_502()
    connection_key = _build_pnp_connection_key(payload.connection_name)

    try:
        pnp_instance_repository.create_connection(
            _db_connect,
            connection_key=connection_key,
            connection_name=payload.connection_name.strip(),
            page_url=str(catalog.get("page_url") or DEFAULT_PNP_POWERBI_REPORT_URL),
            is_active=payload.is_active,
        )
    except psycopg2.Error as exc:
        if exc.pgcode == "23505":
            raise HTTPException(status_code=409, detail=f"PNP connection already exists for key: {connection_key}") from exc
        raise

    return _enrich_connections_with_health([_load_pnp_connection(connection_key)])[0]


@app.delete("/api/admin/connections/pnp/{connection_key}")
def delete_pnp_connection(
    connection_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    return _delete_pnp_connection(connection_key)


@app.get("/api/admin/pipelines/pnp")
def list_pnp_pipelines(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"items": _group_pnp_instances(_load_all_pnp_rows())}


@app.get("/api/admin/connectors/pnp/instances")
def list_pnp_instances(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return list_pnp_pipelines(_)


@app.get("/api/admin/connectors/pnp/instances/{instance_key}")
def get_pnp_instance(instance_key: str, _: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return _load_pnp_instance(instance_key)


@app.get("/api/admin/pipelines/pnp/{instance_key}")
def get_pnp_pipeline(instance_key: str, _: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return _load_pnp_instance(instance_key)


@app.get("/api/admin/connectors/pnp/instances/{instance_key}/admin-overview")
def get_pnp_instance_admin_overview(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    instance = _load_pnp_instance(instance_key)
    diagnostics = _load_pnp_instance_diagnostics(instance_key)
    run_events = _load_pnp_instance_run_events(instance_key)
    integrations = _load_pnp_instance_integrations(instance_key)
    return {
        "instance": instance,
        "diagnostics": diagnostics,
        "diagnostics_summary": _summarize_pnp_diagnostics(diagnostics),
        "run_events": run_events,
        "ingestion": _build_pnp_ingestion_summary(run_events),
        "integrations": integrations,
    }


@app.get("/api/admin/pipelines/pnp/{instance_key}/admin-overview")
def get_pnp_pipeline_admin_overview(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    return get_pnp_instance_admin_overview(instance_key, _)


@app.get("/api/admin/connectors/pnp/instances/{instance_key}/dag-runs")
def list_pnp_instance_dag_runs(instance_key: str, _: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"items": _load_pnp_instance_dag_runs(instance_key)}


@app.get("/api/admin/pipelines/pnp/{instance_key}/dag-runs")
def list_pnp_pipeline_dag_runs(instance_key: str, _: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"items": _load_pnp_instance_dag_runs(instance_key)}


@app.post("/api/admin/connectors/pnp/instances/{instance_key}/operations/validate-sources")
def trigger_pnp_instance_validate_sources(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    instance = _load_pnp_instance(instance_key)
    return _trigger_pnp_airflow_dag(
        _build_pnp_instance_dag_id(instance),
        instance_key,
        operation="validate",
    )


@app.post("/api/admin/pipelines/pnp/{instance_key}/operations/validate-sources")
def trigger_pnp_pipeline_validate_sources(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    instance = _load_pnp_instance(instance_key)
    return _trigger_pnp_airflow_dag(
        _build_pnp_instance_dag_id(instance),
        instance_key,
        operation="validate",
    )


@app.post("/api/admin/connectors/pnp/instances/{instance_key}/operations/full-sync")
def trigger_pnp_instance_full_sync(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    instance = _load_pnp_instance(instance_key)
    return _trigger_pnp_airflow_dag(
        _build_pnp_instance_dag_id(instance),
        instance_key,
        operation="sync",
    )


@app.post("/api/admin/pipelines/pnp/{instance_key}/operations/full-sync")
def trigger_pnp_pipeline_full_sync(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    instance = _load_pnp_instance(instance_key)
    return _trigger_pnp_airflow_dag(
        _build_pnp_instance_dag_id(instance),
        instance_key,
        operation="sync",
    )


@app.delete("/api/admin/pipelines/pnp/instances/{instance_key}")
def delete_pnp_pipeline_instance(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    return _delete_pnp_instance(instance_key)


@app.delete("/api/admin/connections/pnp/instances/{instance_key}")
def delete_pnp_connection_instance(
    instance_key: str,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, Any]:
    return _delete_pnp_instance(instance_key)


@app.post("/api/admin/pipelines/pnp")
def create_pnp_pipeline(
    payload: PnpPipelineCreateRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    catalog = _load_pnp_powerbi_catalog_or_502()
    _validate_pnp_selection_against_catalog(
        selected_years=payload.selected_years,
        selected_microdados_types=payload.selected_microdados_types,
        catalog=catalog,
    )
    selected_downloads = _resolve_pnp_selected_downloads(
        selected_years=payload.selected_years,
        selected_microdados_types=payload.selected_microdados_types,
        catalog=catalog,
    )

    connection = _load_pnp_connection(payload.connection_key)
    instance_key = _build_pnp_pipeline_key(payload.pipeline_name)
    normalized_schedule = _normalize_pipeline_schedule(payload.schedule)

    try:
        pnp_instance_repository.create_instance(
            _db_connect,
            instance_key=instance_key,
            instance_name=payload.pipeline_name.strip(),
            connection_key=str(connection["connection_key"]),
            selected_years=payload.selected_years,
            selected_microdados_types=payload.selected_microdados_types,
            selected_downloads=selected_downloads,
            schedule=normalized_schedule,
            is_active=payload.is_active,
        )
    except pnp_instance_repository.PnpConnectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PNP connection not found") from exc
    except psycopg2.Error as exc:
        if exc.pgcode == "23505":
            raise HTTPException(status_code=409, detail=f"PNP instance already exists for key: {instance_key}") from exc
        raise

    instance = _load_pnp_instance(instance_key)
    dag_id = _build_pnp_instance_dag_id(instance)
    try:
        _wait_for_airflow_dag(dag_id)
    except HTTPException:
        pnp_instance_repository.delete_instance(_db_connect, instance_key=instance_key)
        raise

    return instance


@app.post("/api/admin/connectors/pnp/instances")
def create_pnp_instance(
    payload: PnpInstanceCreateRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    rows = _load_all_pnp_rows()
    connections = _group_pnp_connections(rows)
    if connections:
        connection_key = connections[0]["connection_key"]
    else:
        connection = create_pnp_connection(
            PnpConnectionCreateRequest(connection_name="PNP Principal", is_active=payload.is_active),
            _,
        )
        connection_key = str(connection["connection_key"])

    return create_pnp_pipeline(
        PnpPipelineCreateRequest(
            pipeline_name=payload.instance_name,
            connection_key=connection_key,
            selected_years=payload.selected_years,
            selected_microdados_types=payload.selected_microdados_types,
            schedule=payload.schedule,
            is_active=payload.is_active,
        ),
        _,
    )


@app.patch("/api/admin/connectors/pnp/instances/{instance_key}")
def update_pnp_instance(
    instance_key: str,
    payload: PnpInstanceUpdateRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    _load_pnp_instance(instance_key)
    normalized_schedule = _normalize_pipeline_schedule(payload.schedule) if payload.schedule is not None else None
    return _persist_pnp_instance_settings(
        instance_key,
        schedule=normalized_schedule,
        is_active=payload.is_active,
    )


@app.post("/api/embed/metabase-token")
def create_embed_token(req: EmbedRequest) -> dict[str, object]:
    return _signed_metabase_dashboard_payload(req.dashboard_id, req.params)


@app.get("/api/embed/metabase-default")
def get_default_embed_token() -> dict[str, object]:
    dashboard_id = _read_metabase_default_dashboard_id()
    return _signed_metabase_dashboard_payload(dashboard_id, {})


@app.post("/api/admin/embed/metabase-default")
def set_default_embed_token(
    req: EmbedRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    _write_metabase_default_dashboard_id(req.dashboard_id)
    return _signed_metabase_dashboard_payload(req.dashboard_id, req.params)


@app.get("/api/admin/sql/catalog")
def get_admin_sql_catalog(_: dict[str, object] = Depends(_require_admin)) -> dict[str, object]:
    return {"items": _admin_sql_catalog()}


@app.post("/api/admin/sql/query")
def run_admin_sql_query(
    req: AdminSqlQueryRequest,
    _: dict[str, object] = Depends(_require_admin),
) -> dict[str, object]:
    statement = _validate_admin_sql(req.sql)

    try:
        with _db_connect() as conn, conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute(statement)
            fields = [{"name": item[0]} for item in (cur.description or [])]
            rows = list(cur.fetchmany(req.max_rows + 1)) if cur.description else []
            truncated = len(rows) > req.max_rows
            if truncated:
                rows = rows[: req.max_rows]
            cur.execute("ROLLBACK")
    except psycopg2.Error as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip()) from exc

    return {
        "fields": fields,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "max_rows": req.max_rows,
    }


@app.post("/api/vanna/ask")
async def ask(
    req: AskRequest,
    payload: dict[str, object] | None = Depends(verify_optional_bearer),
) -> dict[str, object]:
    config = _effective_vanna_llm_settings_for_user(payload) if payload else _effective_global_vanna_llm_settings()
    return await ask_vanna(settings.vanna_service_url, req.question, _vanna_llm_override_payload(config))
