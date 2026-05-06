from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


VANNA_LLM_SETTING_KEY = "vanna.llm_config"


@dataclass(frozen=True)
class RuntimeVannaConfig:
    provider: str
    ollama_base_url: str
    ollama_model: str
    maritaca_api_url: str
    maritaca_api_key: str
    maritaca_model: str
    maritaca_timeout_seconds: int
    allowed_schema: str
    vectorstore_path: str
    auto_train: bool
    max_rows: int

    def signature(self) -> tuple[object, ...]:
        return (
            self.provider,
            self.ollama_base_url,
            self.ollama_model,
            self.maritaca_api_url,
            self.maritaca_api_key,
            self.maritaca_model,
            self.maritaca_timeout_seconds,
            self.allowed_schema,
            self.vectorstore_path,
            self.auto_train,
            self.max_rows,
        )

    def model_name(self) -> str:
        if self.provider == "maritaca":
            return self.maritaca_model
        return self.ollama_model


def load_runtime_vanna_config(base_settings: Any, engine: Engine) -> RuntimeVannaConfig:
    defaults = {
        "provider": str(base_settings.vanna_llm_provider).strip().lower() or "ollama",
        "ollama_base_url": str(base_settings.vanna_ollama_base_url).strip() or "http://ollama:11434",
        "ollama_model": str(base_settings.vanna_ollama_model).strip() or "sabia-7b",
        "maritaca_api_url": str(base_settings.vanna_maritaca_api_url).strip(),
        "maritaca_api_key": str(base_settings.vanna_maritaca_api_key),
        "maritaca_model": str(base_settings.vanna_maritaca_model).strip() or "sabia-4",
        "maritaca_timeout_seconds": int(base_settings.vanna_maritaca_timeout_seconds),
        "allowed_schema": str(base_settings.effective_allowed_schema()).strip().lower() or "curated",
        "vectorstore_path": str(base_settings.vanna_vectorstore_path).strip() or "/data/vanna/chroma",
        "auto_train": bool(base_settings.vanna_auto_train),
        "max_rows": int(base_settings.vanna_max_rows),
    }

    persisted = _read_persisted_llm_settings(engine)
    if isinstance(persisted, dict):
        provider = str(persisted.get("provider") or defaults["provider"]).strip().lower() or "ollama"
        ollama = persisted.get("ollama") if isinstance(persisted.get("ollama"), dict) else {}
        maritaca = persisted.get("maritaca") if isinstance(persisted.get("maritaca"), dict) else {}
        defaults.update(
            {
                "provider": provider,
                "ollama_base_url": str(ollama.get("base_url") or defaults["ollama_base_url"]).strip()
                or defaults["ollama_base_url"],
                "ollama_model": str(ollama.get("model") or defaults["ollama_model"]).strip() or defaults["ollama_model"],
                "maritaca_api_url": str(maritaca.get("api_url") or defaults["maritaca_api_url"]).strip()
                or defaults["maritaca_api_url"],
                "maritaca_api_key": str(maritaca.get("api_key") or defaults["maritaca_api_key"]),
                "maritaca_model": str(maritaca.get("model") or defaults["maritaca_model"]).strip()
                or defaults["maritaca_model"],
                "maritaca_timeout_seconds": _coerce_positive_int(
                    maritaca.get("timeout_seconds"), defaults["maritaca_timeout_seconds"]
                ),
            }
        )

    return RuntimeVannaConfig(**defaults)


def _read_persisted_llm_settings(engine: Engine) -> dict[str, Any] | None:
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT setting_value FROM config.app_settings WHERE setting_key = :setting_key"),
                {"setting_key": VANNA_LLM_SETTING_KEY},
            ).mappings().first()
    except SQLAlchemyError:
        return None

    if not row:
        return None
    value = row.get("setting_value")
    return value if isinstance(value, dict) else None


def _coerce_positive_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return int(value) or default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            parsed = int(normalized)
            return parsed if parsed > 0 else default
    return default
