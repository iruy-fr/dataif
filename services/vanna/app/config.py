from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    vanna_host: str = Field(default="0.0.0.0", alias="VANNA_HOST")
    vanna_port: int = Field(default=9000, alias="VANNA_PORT")
    vanna_dsn: str = Field(..., alias="VANNA_DSN")
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
    vanna_vectorstore_path: str = Field(default="/data/vanna/chroma", alias="VANNA_VECTORSTORE_PATH")
    vanna_auto_train: bool = Field(default=True, alias="VANNA_AUTO_TRAIN")
    vanna_allowed_schema: str = Field(default="curated", alias="VANNA_ALLOWED_SCHEMA")
    allowed_curated_views: str = Field(
        default="",
        alias="ALLOWED_CURATED_VIEWS",
    )
    vanna_max_rows: int = Field(default=200, alias="VANNA_MAX_ROWS")

    def effective_allowed_schema(self) -> str:
        configured_schema = self.vanna_allowed_schema.strip().lower()
        if os.getenv("VANNA_ALLOWED_SCHEMA") or configured_schema:
            return configured_schema or "curated"

        legacy_schemas = {
            item.strip().split(".", 1)[0].lower()
            for item in self.allowed_curated_views.split(",")
            if "." in item.strip()
        }
        if len(legacy_schemas) == 1:
            return next(iter(legacy_schemas))
        return "curated"

    def model_name(self) -> str:
        provider = self.vanna_llm_provider.strip().lower()
        if provider == "maritaca":
            return self.vanna_maritaca_model
        return self.vanna_ollama_model

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
