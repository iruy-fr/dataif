from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .config import Settings
    from sqlalchemy import Engine

from .runtime_config import RuntimeVannaConfig, load_runtime_vanna_config


@dataclass(frozen=True)
class CuratedRelation:
    schema_name: str
    relation_name: str
    relation_type: str
    columns: tuple[tuple[str, str], ...]

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.relation_name}"


class MaritacaChat:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def system_message(self, message: str) -> dict[str, str]:
        return {"role": "system", "content": message}

    def user_message(self, message: str) -> dict[str, str]:
        return {"role": "user", "content": message}

    def assistant_message(self, message: str) -> dict[str, str]:
        return {"role": "assistant", "content": message}

    def submit_prompt(self, prompt: Any, **_: Any) -> str:
        api_key = str(self.config.get("maritaca_api_key") or "").strip()
        if not api_key:
            raise RuntimeError("VANNA_MARITACA_API_KEY is required for VANNA_LLM_PROVIDER=maritaca")

        api_url = str(
            self.config.get("maritaca_api_url") or "https://chat.maritaca.ai/api/chat/completions"
        ).strip()
        model = str(self.config.get("model") or "sabia-4").strip()
        timeout = int(self.config.get("maritaca_timeout_seconds") or 60)
        payload = json.dumps({"model": model, "messages": self._messages(prompt)}).encode("utf-8")
        request = Request(
            api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Maritaca API returned HTTP {exc.code}: {detail}") from exc
        except (OSError, TimeoutError, URLError) as exc:
            raise RuntimeError(f"Maritaca API request failed: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Maritaca API returned an invalid response") from exc

    @staticmethod
    def _messages(prompt: Any) -> list[dict[str, str]]:
        if isinstance(prompt, list):
            messages: list[dict[str, str]] = []
            for item in prompt:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    messages.append({"role": str(item["role"]), "content": str(item["content"])})
                else:
                    messages.append({"role": "user", "content": str(item)})
            return messages or [{"role": "user", "content": ""}]
        return [{"role": "user", "content": str(prompt)}]


class DataifVannaEngine:
    def __init__(self, settings: Settings, engine: Engine, allowed_schema: str) -> None:
        self.settings = settings
        self.engine = engine
        self.allowed_schema = allowed_schema.strip().lower()
        self._lock = Lock()
        self._trained = False
        self.vn: Any | None = None
        self._vanna_class: type | None = None
        self._runtime_config: RuntimeVannaConfig | None = None
        self._config_signature: tuple[object, ...] | None = None
        Path(settings.vanna_vectorstore_path).mkdir(parents=True, exist_ok=True)
        self._ensure_runtime_config()

    def _client(self) -> Any:
        self._ensure_runtime_config()
        if self.vn is not None:
            return self.vn
        if self._vanna_class is None or self._runtime_config is None:
            raise RuntimeError("Vanna runtime configuration is unavailable")
        self.vn = self._vanna_class(config=self._provider_config(self._runtime_config))
        self.vn.run_sql = self._run_sql_dataframe
        self.vn.run_sql_is_set = True
        return self.vn

    def generate_sql(self, question: str, runtime_override: dict[str, Any] | None = None) -> str:
        runtime = self._runtime_from_override(runtime_override)
        if not self._is_runtime_available(runtime):
            raise RuntimeError(self._unavailable_message(runtime))
        if runtime.auto_train:
            self.train_once()
        client = self._client() if runtime.signature() == self.runtime_config().signature() else self._client_for_runtime(runtime)
        return client.generate_sql(question=question, allow_llm_to_see_data=False)

    def is_llm_available(self) -> bool:
        return bool(self.provider_status()["available"])

    def provider_status(self) -> dict[str, object]:
        runtime = self.runtime_config()
        return self._provider_status(runtime)

    def _provider_status(self, runtime: RuntimeVannaConfig) -> dict[str, object]:
        provider = runtime.provider
        if provider == "maritaca":
            if runtime.maritaca_api_key.strip():
                return {"available": True, "detail": "Maritaca API key configured"}
            return {"available": False, "detail": "Maritaca API key is not configured"}

        try:
            with urlopen(f"{runtime.ollama_base_url.rstrip('/')}/api/tags", timeout=2) as response:
                available = 200 <= response.status < 500
                return {
                    "available": available,
                    "detail": f"Ollama responded at {runtime.ollama_base_url}" if available else "Ollama returned an error",
                }
        except (OSError, TimeoutError, URLError) as exc:
            return {"available": False, "detail": f"Ollama is not reachable at {runtime.ollama_base_url}: {exc}"}

    def _is_runtime_available(self, runtime: RuntimeVannaConfig) -> bool:
        return bool(self._provider_status(runtime)["available"])

    def train_once(self, force: bool = False) -> None:
        with self._lock:
            self._ensure_runtime_config()
            if self._trained and not force:
                return
            vn = self._client()
            for relation in self._load_allowed_relations():
                vn.train(ddl=self._build_ddl(relation))
            for item in self._load_catalog_documentation():
                vn.train(documentation=item)
            for query in self._approved_examples():
                vn.train(sql=query)
            self._trained = True

    def _run_sql_dataframe(self, sql: str) -> Any:
        import pandas as pd
        from sqlalchemy import text

        with self.engine.begin() as conn:
            return pd.read_sql_query(sql=text(sql), con=conn)

    def _load_allowed_relations(self) -> list[CuratedRelation]:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT
                        c.table_schema,
                        c.table_name,
                        c.column_name,
                        c.data_type,
                        COALESCE(
                            t.table_type,
                            CASE WHEN mv.matviewname IS NOT NULL THEN 'MATERIALIZED VIEW' ELSE 'RELATION' END
                        ) AS relation_type
                    FROM information_schema.columns c
                    LEFT JOIN information_schema.tables t
                      ON t.table_schema = c.table_schema
                     AND t.table_name = c.table_name
                    LEFT JOIN pg_catalog.pg_matviews mv
                      ON mv.schemaname = c.table_schema
                     AND mv.matviewname = c.table_name
                    WHERE c.table_schema = :allowed_schema
                    ORDER BY table_schema, table_name, ordinal_position
                    """
                ),
                {"allowed_schema": self.allowed_schema},
            ).mappings()
            grouped: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
            for row in rows:
                key = (row["table_schema"], row["table_name"], row["relation_type"])
                grouped.setdefault(key, []).append((row["column_name"], row["data_type"]))

        return [
            CuratedRelation(
                schema_name=schema,
                relation_name=name,
                relation_type=relation_type,
                columns=tuple(columns),
            )
            for (schema, name, relation_type), columns in grouped.items()
        ]

    def _load_catalog_documentation(self) -> list[str]:
        from sqlalchemy import text

        catalog_name = f"{self.allowed_schema}.vw_pnp_vanna_catalogo"
        schema_sql = self._quote_identifier(self.allowed_schema)
        with self.engine.begin() as conn:
            exists = conn.execute(
                text("SELECT to_regclass(:catalog_name)"),
                {"catalog_name": catalog_name},
            ).scalar()
            if not exists:
                return []

            rows = conn.execute(
                text(
                    f"""
                    SELECT relation_group, relation_name, relation_description
                    FROM {schema_sql}.vw_pnp_vanna_catalogo
                    ORDER BY relation_group, relation_name
                    """
                )
            ).mappings()
            return [
                (
                    f"Relacao {self.allowed_schema}.{row['relation_name']} pertence ao dominio "
                    f"{row['relation_group']}: {row['relation_description']}"
                )
                for row in rows
            ]

    def _build_vanna_class(self, provider: str | None = None) -> type:
        from vanna.chromadb import ChromaDB_VectorStore

        provider = provider or self.runtime_config().provider
        if provider == "ollama":
            from vanna.ollama import Ollama

            class OllamaVanna(ChromaDB_VectorStore, Ollama):
                def __init__(self, config=None):
                    ChromaDB_VectorStore.__init__(self, config=config)
                    Ollama.__init__(self, config=config)

            return OllamaVanna

        if provider == "maritaca":
            class MaritacaVanna(MaritacaChat, ChromaDB_VectorStore):
                def __init__(self, config=None):
                    ChromaDB_VectorStore.__init__(self, config=config)
                    MaritacaChat.__init__(self, config=config)

            return MaritacaVanna

        raise RuntimeError(f"Unsupported VANNA_LLM_PROVIDER: {self.settings.vanna_llm_provider}")

    def _provider_config(self, runtime: RuntimeVannaConfig | None = None) -> dict[str, Any]:
        runtime = runtime or self.runtime_config()
        config: dict[str, Any] = {
            "model": runtime.model_name(),
            "path": runtime.vectorstore_path,
        }
        provider = runtime.provider
        if provider == "ollama":
            config["ollama_host"] = runtime.ollama_base_url
        elif provider == "maritaca":
            config["maritaca_api_url"] = runtime.maritaca_api_url
            config["maritaca_api_key"] = runtime.maritaca_api_key
            config["maritaca_timeout_seconds"] = runtime.maritaca_timeout_seconds
        return config

    def _client_for_runtime(self, runtime: RuntimeVannaConfig) -> Any:
        client_class = self._build_vanna_class(runtime.provider)
        client = client_class(config=self._provider_config(runtime))
        client.run_sql = self._run_sql_dataframe
        client.run_sql_is_set = True
        return client

    def _runtime_from_override(self, override: dict[str, Any] | None) -> RuntimeVannaConfig:
        runtime = self.runtime_config()
        if not override:
            return runtime

        provider = str(override.get("provider") or runtime.provider).strip().lower() or runtime.provider
        ollama = override.get("ollama") if isinstance(override.get("ollama"), dict) else {}
        maritaca = override.get("maritaca") if isinstance(override.get("maritaca"), dict) else {}
        return replace(
            runtime,
            provider=provider,
            ollama_base_url=str(ollama.get("base_url") or runtime.ollama_base_url).strip() or runtime.ollama_base_url,
            ollama_model=str(ollama.get("model") or runtime.ollama_model).strip() or runtime.ollama_model,
            maritaca_api_url=str(maritaca.get("api_url") or runtime.maritaca_api_url).strip() or runtime.maritaca_api_url,
            maritaca_api_key=str(maritaca.get("api_key") or runtime.maritaca_api_key),
            maritaca_model=str(maritaca.get("model") or runtime.maritaca_model).strip() or runtime.maritaca_model,
            maritaca_timeout_seconds=_coerce_positive_int(
                maritaca.get("timeout_seconds"),
                runtime.maritaca_timeout_seconds,
            ),
        )

    def _unavailable_message(self, runtime: RuntimeVannaConfig | None = None) -> str:
        runtime = runtime or self.runtime_config()
        provider = runtime.provider
        if provider == "maritaca":
            return "Maritaca API key is not configured"
        return f"Ollama is not reachable at {runtime.ollama_base_url}"

    def runtime_config(self) -> RuntimeVannaConfig:
        self._ensure_runtime_config()
        if self._runtime_config is None:
            raise RuntimeError("Vanna runtime configuration is unavailable")
        return self._runtime_config

    def _ensure_runtime_config(self) -> None:
        runtime = load_runtime_vanna_config(self.settings, self.engine)
        signature = runtime.signature()
        if self._config_signature == signature:
            return

        Path(runtime.vectorstore_path).mkdir(parents=True, exist_ok=True)
        self._runtime_config = runtime
        self._config_signature = signature
        self._vanna_class = self._build_vanna_class(runtime.provider)
        self.vn = None
        self._trained = False

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            raise ValueError(f"Invalid SQL identifier: {identifier}")
        return f'"{identifier}"'

    @staticmethod
    def _build_ddl(relation: CuratedRelation) -> str:
        columns = ",\n  ".join(f"{name} {data_type}" for name, data_type in relation.columns)
        return f"-- RELATION TYPE: {relation.relation_type}\nCREATE TABLE {relation.full_name} (\n  {columns}\n);"

    def _approved_examples(self) -> list[str]:
        if self.allowed_schema != "curated":
            return []
        return [
            (
                "SELECT dominio, indicador, ano, SUM(valor) AS total "
                "FROM curated.vw_pnp_vanna_resumo "
                "GROUP BY dominio, indicador, ano "
                "ORDER BY ano DESC, dominio, indicador LIMIT 50"
            ),
            (
                "SELECT relation_group, relation_name, relation_description "
                "FROM curated.vw_pnp_vanna_catalogo "
                "ORDER BY relation_group, relation_name LIMIT 50"
            ),
            (
                "SELECT instituicao, ano, SUM(valor) AS total_matriculas "
                "FROM curated.vw_pnp_vanna_resumo "
                "WHERE dominio = 'matriculas' "
                "GROUP BY instituicao, ano "
                "ORDER BY ano DESC, total_matriculas DESC LIMIT 50"
            ),
            (
                "SELECT ano, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "GROUP BY ano ORDER BY ano DESC LIMIT 50"
            ),
        ]
