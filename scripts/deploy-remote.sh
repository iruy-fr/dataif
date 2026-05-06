#!/usr/bin/env bash
set -euo pipefail

RAW_BASE_URL="${DATAIF_RAW_BASE_URL:-https://raw.githubusercontent.com/iruy-fr/dataif/main}"
TARGET_DIR="${DATAIF_DEPLOY_DIR:-$PWD/.dataif-deploy}"

mkdir -p "${TARGET_DIR}"

compose_file="${TARGET_DIR}/docker-compose.yml"
env_example_file="${TARGET_DIR}/.env.example"
env_file="${TARGET_DIR}/.env"

curl -fsSL "${RAW_BASE_URL}/infra/docker-compose.remote.yml" -o "${compose_file}"
curl -fsSL "${RAW_BASE_URL}/infra/.env.example" -o "${env_example_file}"

if [ ! -f "${env_file}" ]; then
  cp "${env_example_file}" "${env_file}"
fi

docker compose --env-file "${env_file}" -f "${compose_file}" pull
docker compose --env-file "${env_file}" -f "${compose_file}" up -d

printf 'DataIF deployado em %s\n' "${TARGET_DIR}"
printf 'Edite %s para ajustar credenciais e portas em reexecucoes futuras.\n' "${env_file}"

