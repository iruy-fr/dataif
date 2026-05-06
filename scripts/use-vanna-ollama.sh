#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"
ENV_FILE="${INFRA_DIR}/.env"

run_bootstrap=true

usage() {
  cat <<'EOF'
Uso: ./scripts/use-vanna-ollama.sh [--no-bootstrap]

Alterna o Vanna para Ollama, preservando a chave Maritaca no infra/.env.

Opcoes:
  --no-bootstrap  Nao executa ollama-model-bootstrap. Use quando o modelo ja existir.
  -h, --help      Mostra esta ajuda.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-bootstrap)
      run_bootstrap=false
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Opcao desconhecida: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [ ! -f "${ENV_FILE}" ]; then
  echo "Arquivo ${ENV_FILE} nao encontrado. Crie-o a partir de infra/.env.example antes de continuar." >&2
  exit 1
fi

get_env_value() {
  local key="$1"

  awk -v key="${key}" '
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
      value = $0
      sub("^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=[[:space:]]*", "", value)
      sub(/[[:space:]]*$/, "", value)
      if ((value ~ /^".*"$/) || (value ~ /^'\''.*'\''$/)) {
        value = substr(value, 2, length(value) - 2)
      }
      found = 1
    }
    END {
      if (found) {
        print value
      }
    }
  ' "${ENV_FILE}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp

  tmp="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
  awk -v key="${key}" -v value="${value}" '
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "[[:space:]]*=" {
      if (!written) {
        print key "=" value
        written = 1
      }
      next
    }
    { print }
    END {
      if (!written) {
        print key "=" value
      }
    }
  ' "${ENV_FILE}" > "${tmp}"

  chmod --reference="${ENV_FILE}" "${tmp}" 2>/dev/null || true
  mv "${tmp}" "${ENV_FILE}"
}

ollama_model_name="$(get_env_value OLLAMA_MODEL_NAME)"
if [ -z "${ollama_model_name}" ]; then
  ollama_model_name="sabia-7b"
fi

vanna_port="$(get_env_value VANNA_PORT)"
if [ -z "${vanna_port}" ]; then
  vanna_port="9000"
fi

echo "Atualizando ${ENV_FILE}: VANNA_LLM_PROVIDER=ollama"
set_env_value "VANNA_LLM_PROVIDER" "ollama"
set_env_value "VANNA_OLLAMA_BASE_URL" "http://ollama:11434"
set_env_value "VANNA_OLLAMA_MODEL" "${ollama_model_name}"

cd "${INFRA_DIR}"

echo "Subindo Ollama..."
docker compose --profile llm up -d ollama

if [ "${run_bootstrap}" = true ]; then
  echo "Carregando modelo Ollama (${ollama_model_name})..."
  docker compose --profile llm run --rm ollama-model-bootstrap
else
  echo "Bootstrap do modelo pulado (--no-bootstrap)."
fi

echo "Reiniciando Vanna..."
docker compose up -d --build vanna

health_url="http://localhost:${vanna_port}/health"
echo "Verificando healthcheck: curl ${health_url}"

for attempt in $(seq 1 30); do
  if curl -fsS "${health_url}"; then
    echo
    exit 0
  fi

  if [ "${attempt}" -eq 30 ]; then
    echo
    echo "Vanna nao respondeu em ${health_url}. Tente novamente com:" >&2
    echo "curl ${health_url}" >&2
    exit 1
  fi

  sleep 2
done
