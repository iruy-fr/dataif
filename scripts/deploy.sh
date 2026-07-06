#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="${ROOT_DIR}/infra"
ENV_FILE="${INFRA_DIR}/.env"
STG_TEMPLATE="${INFRA_DIR}/.env.stg.example"
PROD_TEMPLATE="${INFRA_DIR}/.env.example"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.yml"

usage() {
  cat <<'USAGE'
Uso: ./scripts/deploy.sh stg|prod [--llm]

stg   Sobe ambiente local de teste com variaveis presetadas.
prod  Sobe ambiente local de producao com configuração interativa.

Opcoes:
  --llm  Inclui Ollama e bootstrap do modelo local.

Variaveis:
  DATAIF_FORCE_ENV=true  Recria infra/.env a partir do template do modo.
  DATAIF_DEPLOY_CONFIG_ONLY=true  Configura e valida sem subir containers.
USAGE
}

mode="${1:-}"
shift || true

if [ "${mode}" != "stg" ] && [ "${mode}" != "prod" ]; then
  usage >&2
  exit 1
fi

compose_args=(--env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")

for arg in "$@"; do
  case "${arg}" in
    --llm) compose_args+=(--profile llm) ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Opcao invalida: %s\n' "${arg}" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ "${mode}" = "stg" ]; then
  if [ ! -f "${ENV_FILE}" ] || [ "${DATAIF_FORCE_ENV:-false}" = "true" ]; then
    cp "${STG_TEMPLATE}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    printf 'Arquivo stg criado: %s\n' "${ENV_FILE}"
  else
    printf 'Arquivo existente mantido: %s\n' "${ENV_FILE}"
  fi
else
  if [ ! -f "${ENV_FILE}" ] || [ "${DATAIF_FORCE_ENV:-false}" = "true" ]; then
    DATAIF_ENV_FILE="${ENV_FILE}" "${ROOT_DIR}/scripts/configure-env.sh"
  else
    printf 'Arquivo existente mantido: %s\n' "${ENV_FILE}"
    printf 'Para reconfigurar: DATAIF_FORCE_ENV=true ./scripts/deploy.sh prod\n'
  fi
fi

docker compose "${compose_args[@]}" config >/dev/null

if [ "${DATAIF_DEPLOY_CONFIG_ONLY:-false}" = "true" ]; then
  printf 'Configuracao validada: %s\n' "${ENV_FILE}"
  exit 0
fi

printf 'Inicializando admin DataIF no Keycloak...\n'
docker compose "${compose_args[@]}" up -d --build keycloak
docker compose "${compose_args[@]}" up --build keycloak-bootstrap

docker compose "${compose_args[@]}" up -d --build

printf 'DataIF %s ativo.\n' "${mode}"
public_url="$(awk -F= '$1 == "DATAIF_PUBLIC_BASE_URL" {print $2}' "${ENV_FILE}")"
if [ -z "${public_url}" ]; then
  public_url="http://localhost:$(awk -F= '$1 == "WEB_PORT" {print $2}' "${ENV_FILE}")"
fi
printf 'Web: %s\n' "${public_url}"
