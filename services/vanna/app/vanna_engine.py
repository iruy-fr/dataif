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

from .runtime_config import RuntimeVannaConfig, _coerce_positive_int, load_runtime_vanna_config

# Marcador usado quando a LLM julga o contexto insuficiente para gerar SQL. O prompt padrao da
# lib vanna instrui a LLM a "explicar por que nao pode gerar" nesse caso (texto livre, sem SQL),
# o que quebra o SQLGuard com um erro generico ("Only SELECT statements are allowed"). Prefixar
# a resposta com este marcador deixa esse caso detectavel de forma confiavel em main.py, para
# devolver ao usuario uma mensagem clara pedindo mais contexto, em vez de um erro tecnico.
CONTEXT_INSUFFICIENT_MARKER = "CONTEXTO_INSUFICIENTE:"

_INITIAL_PROMPT = (
    "Voce e um especialista em PostgreSQL. Ajude a gerar uma consulta SQL para responder a "
    "pergunta. Sua resposta deve se basear apenas no contexto fornecido (DDL, documentacao e "
    "exemplos abaixo) e seguir as diretrizes de resposta."
)

_RESPONSE_GUIDELINES = (
    "===Diretrizes de resposta \n"
    "1. Se o contexto fornecido for suficiente, gere apenas uma consulta SQL valida para a "
    "pergunta, sem nenhuma explicacao. Prefira sempre tentar responder com os dados "
    "disponiveis, mesmo que a pergunta seja ampla ou generica -- para perguntas sobre quais "
    "dados/tabelas existem, use curated.vw_pnp_vanna_catalogo; para indicadores gerais, use "
    "curated.vw_pnp_vanna_resumo. \n"
    "2. Se o contexto for quase suficiente mas faltar o valor exato de uma coluna categorica, "
    "use a documentacao de valores codificados fornecida acima; NAO gere uma consulta "
    "intermediaria (intermediate_sql) -- este ambiente nao permite executa-la. \n"
    f"3. Use a opcao a seguir apenas como ultimo recurso, quando a pergunta genuinamente nao "
    f"tiver relacao com nenhuma tabela, view ou exemplo do contexto fornecido (ex.: pergunta "
    f"sobre assunto fora do dominio, como clima ou noticias): responda apenas com uma unica "
    f"linha no formato {CONTEXT_INSUFFICIENT_MARKER} <motivo em poucas palavras, em "
    "portugues>. Nao inclua mais nada nessa resposta. \n"
    "4. Utilize a tabela/view mais adequada disponivel no contexto. \n"
    "5. Se a pergunta ja foi feita e respondida antes, repita a resposta exatamente como foi "
    "dada. \n"
    "6. Garanta que a SQL de saida seja compativel com PostgreSQL, executavel e livre de erros "
    "de sintaxe. \n"
)


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
            for item in self._domain_value_documentation():
                vn.train(documentation=item)
            for question, sql in self._approved_examples():
                # question sempre explicito: sem isso, vanna.train(sql=...) chama a LLM para
                # gerar a pergunta (generate_question), o que exige API key so para treinar e
                # produz perguntas menos fieis ao fraseado real do usuario do que os exemplos
                # curados abaixo.
                vn.train(question=question, sql=sql)
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
                    LEFT JOIN pg_catalog.pg_namespace pn
                      ON pn.nspname = c.table_schema
                    LEFT JOIN pg_catalog.pg_class pc
                      ON pc.relname = c.table_name
                     AND pc.relnamespace = pn.oid
                    WHERE c.table_schema = :allowed_schema
                      AND COALESCE(pc.relispartition, FALSE) = FALSE
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
            # vanna.base.base.VannaBase.generate_sql le "initial_prompt" da propria config para
            # montar o prompt de geracao de SQL (get_sql_prompt). A lib sempre concatena suas
            # proprias guidelines em ingles logo apos isto, entao este texto funciona como reforco
            # (idioma, orientacao sobre intermediate_sql), nao como garantia -- a deteccao real de
            # "sem SQL na resposta" acontece em main.py, independente do formato da explicacao.
            "initial_prompt": _INITIAL_PROMPT + "\n\n" + _RESPONSE_GUIDELINES,
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

    def _domain_value_documentation(self) -> list[str]:
        if self.allowed_schema != "curated":
            return []
        return [
            (
                "Para perguntas sobre matriculas, prefira sempre curated.mv_pnp_dashboard_matriculas "
                "(tabela particionada por ano e indexada) em vez de curated.vw_pnp_matriculas_perfil "
                "ou curated.vw_pnp_matriculas_oferta (views nao materializadas, recalculadas por "
                "completo a cada consulta). Use as views pesadas apenas quando a pergunta exigir "
                "eixo_tecnologico ou subeixo_tecnologico, colunas que nao existem na fonte rapida."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, sempre que possivel filtre por 'ano' "
                "(coluna de particionamento) para a consulta ser rapida; se a pergunta mencionar "
                "uma instituicao, filtre tambem por 'instituicao' (geralmente a sigla, ex.: 'IFRS')."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna sexo usa codigos curtos: "
                "'F' (feminino), 'M' (masculino), 'S/I' (sem informacao). Nunca usar "
                "'Feminino'/'Masculino' como literal."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna cor_raca aceita os valores: "
                "'Amarela', 'Branca', 'Indigena', 'Parda', 'Preta', 'Nao declarada', 'S/I'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna faixa_etaria aceita os valores: "
                "'Menor de 14 anos', '15 a 19 anos', '20 a 24 anos', '25 a 29 anos', '30 a 34 anos', "
                "'35 a 39 anos', '40 a 44 anos', '45 a 49 anos', '50 a 54 anos', '55 a 59 anos', "
                "'Maior de 60 anos', 'S/I'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna renda_familiar aceita os valores: "
                "'0<RFP<=0,5', '0,5<RFP<=1', '1<RFP<=1,5', '1,5<RFP<=2,5', '2,5<RFP<=3,5', "
                "'RFP>3,5', 'Nao declarada', 'S/I' (RFP = renda familiar per capita em salarios minimos)."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna modalidade_ensino aceita os "
                "valores: 'Educacao Presencial', 'Educacao a Distancia'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna turno aceita os valores: "
                "'Matutino', 'Vespertino', 'Noturno', 'Integral', 'Nao se aplica', 'Sem Informacao'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna situacao_matricula aceita os "
                "valores: 'Em curso', 'Concluida', 'Integralizada', 'Abandono', 'Cancelada', "
                "'Desligada', 'Reprovado', 'Transf. externa', 'Transf. interna'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna tipo_curso aceita os valores: "
                "'Tecnico', 'Tecnologia', 'Bacharelado', 'Licenciatura', 'ABI', "
                "'Qualificacao Profissional (FIC)', 'Especializacao Tecnica', "
                "'Especializacao (Lato Sensu)', 'Mestrado', 'Mestrado Profissional', 'Doutorado', "
                "'Doutorado Profissional', 'Ensino Fundamental I', 'Ensino Fundamental II', "
                "'Ensino Medio', 'Educacao Infantil'."
            ),
            (
                "Em curated.mv_pnp_dashboard_matriculas, a coluna tipo_oferta aceita os valores: "
                "'Integrado', 'Concomitante', 'Subsequente', 'Todos', 'Nao se aplica', "
                "'PROEJA -', 'PROEJA - Integrado', 'PROEJA - Concomitante', 'PROEJA - Subsequente'."
            ),
        ]

    def _approved_examples(self) -> list[tuple[str, str]]:
        if self.allowed_schema != "curated":
            return []
        return [
            (
                "Qual o total por dominio e indicador?",
                "SELECT dominio, indicador, ano, SUM(valor) AS total "
                "FROM curated.vw_pnp_vanna_resumo "
                "GROUP BY dominio, indicador, ano "
                "ORDER BY ano DESC, dominio, indicador LIMIT 50",
            ),
            (
                "Quais relacoes existem no catalogo de dados?",
                "SELECT relation_group, relation_name, relation_description "
                "FROM curated.vw_pnp_vanna_catalogo "
                "ORDER BY relation_group, relation_name LIMIT 50",
            ),
            # organizacao / territorio
            (
                "Qual a quantidade de matriculas do IFRS em 2025?",
                "SELECT ano, instituicao, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 AND instituicao = 'IFRS' "
                "GROUP BY ano, instituicao LIMIT 50",
            ),
            # serie historica sem filtro de ano
            (
                "Qual a evolucao do total de matriculas por ano?",
                "SELECT ano, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "GROUP BY ano ORDER BY ano DESC LIMIT 50",
            ),
            # sexo
            (
                "Qual a quantidade de matriculas de pessoas do sexo feminino em 2025?",
                "SELECT sexo, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 AND sexo = 'F' "
                "GROUP BY sexo LIMIT 50",
            ),
            # cor/raca
            (
                "Quantas matriculas de pessoas pretas houve em 2025?",
                "SELECT cor_raca, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 AND cor_raca = 'Preta' "
                "GROUP BY cor_raca LIMIT 50",
            ),
            # faixa etaria
            (
                "Como as matriculas de 2025 se distribuem por faixa etaria?",
                "SELECT faixa_etaria, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY faixa_etaria ORDER BY total_matriculas DESC LIMIT 50",
            ),
            # renda familiar
            (
                "Como as matriculas de 2025 se distribuem por faixa de renda familiar?",
                "SELECT renda_familiar, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY renda_familiar ORDER BY total_matriculas DESC LIMIT 50",
            ),
            # tipo de curso / modalidade / turno
            (
                "Quantas matriculas existem por tipo de curso em 2025?",
                "SELECT tipo_curso, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY tipo_curso ORDER BY total_matriculas DESC LIMIT 50",
            ),
            (
                "Quantas matriculas na modalidade a distancia houve em 2025?",
                "SELECT modalidade_ensino, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY modalidade_ensino LIMIT 50",
            ),
            (
                "Quantas matriculas no turno noturno houve em 2025?",
                "SELECT turno, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY turno LIMIT 50",
            ),
            # ranking de cursos
            (
                "Quais os cursos com mais matriculas no IFRS em 2025?",
                "SELECT nome_curso, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 AND instituicao = 'IFRS' "
                "GROUP BY nome_curso ORDER BY total_matriculas DESC LIMIT 20",
            ),
            # situacao da matricula
            (
                "Quantas matriculas concluidas houve em 2025?",
                "SELECT situacao_matricula, SUM(matriculas) AS total_matriculas "
                "FROM curated.mv_pnp_dashboard_matriculas "
                "WHERE ano = 2025 "
                "GROUP BY situacao_matricula ORDER BY total_matriculas DESC LIMIT 50",
            ),
            # caso legitimo de uso da view pesada (colunas que nao existem na fonte rapida)
            (
                "Quais os eixos tecnologicos com mais matriculas em 2025?",
                "SELECT eixo_tecnologico, SUM(matriculas) AS total_matriculas "
                "FROM curated.vw_pnp_matriculas_oferta "
                "WHERE ano = 2025 "
                "GROUP BY eixo_tecnologico ORDER BY total_matriculas DESC LIMIT 50",
            ),
        ]
