from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    metabase_site_url: str = Field(default="http://localhost:3000", alias="METABASE_SITE_URL")
    metabase_api_url: str = Field(default="http://metabase:3000", alias="METABASE_API_URL")
    metabase_embed_secret: str = Field(default="replace_with_secure_secret", alias="METABASE_EMBED_SECRET")
    metabase_allowed_dashboard_ids: str = Field(default="1,2,3", alias="METABASE_ALLOWED_DASHBOARD_IDS")
    metabase_default_dashboard_id: str = Field(default="", alias="METABASE_DEFAULT_DASHBOARD_ID")
    metabase_admin_email: str = Field(default="admin@dataif.local", alias="METABASE_ADMIN_EMAIL")
    metabase_admin_password: str = Field(default="admin", alias="METABASE_ADMIN_PASSWORD")
    metabase_admin_first_name: str = Field(default="DataIF", alias="METABASE_ADMIN_FIRST_NAME")
    metabase_admin_last_name: str = Field(default="Metabase", alias="METABASE_ADMIN_LAST_NAME")
    metabase_site_name: str = Field(default="dataif", alias="METABASE_SITE_NAME")
    metabase_allow_tracking: bool = Field(default=False, alias="METABASE_ALLOW_TRACKING")

    vanna_service_url: str = Field(default="http://localhost:9000", alias="VANNA_SERVICE_URL")
    vanna_llm_provider: str = Field(default="ollama", alias="VANNA_LLM_PROVIDER")
    vanna_ollama_base_url: str = Field(default="http://ollama:11434", alias="VANNA_OLLAMA_BASE_URL")
    vanna_ollama_model: str = Field(default="sabia-7b", alias="VANNA_OLLAMA_MODEL")
    vanna_maritaca_api_url: str = Field(
        default="https://chat.maritaca.ai/api/chat/completions",
        alias="VANNA_MARITACA_API_URL",
    )
    vanna_maritaca_api_key: str = Field(default="", alias="VANNA_MARITACA_API_KEY")
    vanna_maritaca_model: str = Field(default="sabia-4", alias="VANNA_MARITACA_MODEL")
    vanna_maritaca_timeout_seconds: int = Field(default=60, alias="VANNA_MARITACA_TIMEOUT_SECONDS")

    keycloak_url: str = Field(default="http://localhost:8081", alias="KEYCLOAK_URL")
    keycloak_realm: str = Field(default="dataif", alias="KEYCLOAK_REALM")
    keycloak_audience: str = Field(default="dataif-api", alias="KEYCLOAK_AUDIENCE")
    keycloak_client_id: str = Field(default="dataif-web", alias="KEYCLOAK_CLIENT_ID")
    keycloak_client_secret: str = Field(default="", alias="KEYCLOAK_CLIENT_SECRET")
    keycloak_admin_realm: str = Field(default="master", alias="KEYCLOAK_ADMIN_REALM")
    keycloak_admin_client_id: str = Field(default="admin-cli", alias="KEYCLOAK_ADMIN_CLIENT_ID")
    keycloak_admin_username: str = Field(default="admin", alias="KEYCLOAK_ADMIN")
    keycloak_admin_password: str = Field(default="admin", alias="KEYCLOAK_ADMIN_PASSWORD")
    dataif_admin_username: str = Field(default="admin", alias="DATAIF_ADMIN_USERNAME")
    dataif_admin_email: str = Field(default="admin@dataif.local", alias="DATAIF_ADMIN_EMAIL")
    dataif_admin_password: str = Field(default="admin", alias="DATAIF_ADMIN_PASSWORD")
    dataif_admin_first_name: str = Field(default="DataIF", alias="DATAIF_ADMIN_FIRST_NAME")
    dataif_admin_last_name: str = Field(default="Admin", alias="DATAIF_ADMIN_LAST_NAME")

    warehouse_dsn: str = Field(default="", alias="WAREHOUSE_DSN")
    dataif_db_name: str = Field(default="dataif", alias="DATAIF_DB_NAME")
    dataif_metabase_user: str = Field(default="metabase_user", alias="DATAIF_METABASE_USER")
    dataif_metabase_password: str = Field(default="metabase_password", alias="DATAIF_METABASE_PASSWORD")
    airflow_api_url: str = Field(default="http://airflow-webserver:8080/airflow", alias="AIRFLOW_API_URL")
    airflow_admin_user: str = Field(default="admin", alias="AIRFLOW_ADMIN_USER")
    airflow_admin_password: str = Field(default="admin", alias="AIRFLOW_ADMIN_PASSWORD")
    airflow_dag_registration_timeout_seconds: int = Field(default=240, alias="AIRFLOW_DAG_REGISTRATION_TIMEOUT_SECONDS")

    cors_allow_origins: str = Field(default="http://localhost:5173", alias="CORS_ALLOW_ORIGINS")
    nilo_timeout_seconds: int = Field(default=60, alias="NILO_TIMEOUT_SECONDS")
    pnp_catalog_cache_ttl_seconds: int = Field(default=900, alias="PNP_CATALOG_CACHE_TTL_SECONDS")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
