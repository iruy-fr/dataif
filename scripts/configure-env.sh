#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${script_dir}/.env.example" ]; then
  template_file="${script_dir}/.env.example"
  default_env_file="${script_dir}/.env"
  compose_file="${script_dir}/docker-compose.yml"
elif [ -f "${script_dir}/../infra/.env.example" ]; then
  template_file="${script_dir}/../infra/.env.example"
  default_env_file="${script_dir}/../infra/.env"
  compose_file="${script_dir}/../infra/docker-compose.yml"
else
  printf 'Nao encontrei .env.example.\n' >&2
  exit 1
fi

env_file="${DATAIF_ENV_FILE:-${default_env_file}}"

input_fd=0
if [ -e /dev/tty ] && (: </dev/tty) 2>/dev/null; then
  exec 3</dev/tty
  input_fd=3
fi

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '\n'
  else
    local secret
    set +o pipefail
    secret="$(LC_ALL=C tr -dc 'A-Za-z0-9_=-' </dev/urandom | head -c 48)"
    set -o pipefail
    printf '%s' "${secret}"
  fi
}

read_value() {
  local label="$1"
  local default_value="$2"
  local value

  if ! read -r -u "${input_fd}" -p "${label} [${default_value}]: " value; then
    value=""
  fi
  printf '%s' "${value:-${default_value}}"
}

read_secret() {
  local label="$1"
  local default_value="$2"
  local value

  if ! read -r -s -u "${input_fd}" -p "${label} [Enter gera segredo]: " value; then
    value=""
  fi
  printf '\n' >&2
  printf '%s' "${value:-${default_value}}"
}

set_env() {
  local key="$1"
  local value="$2"
  local tmp_file

  tmp_file="$(mktemp)"
  awk -v key="${key}" -v value="${value}" '
    BEGIN { done = 0 }
    $0 ~ "^" key "=" {
      print key "=" value
      done = 1
      next
    }
    { print }
    END {
      if (!done) {
        print key "=" value
      }
    }
  ' "${env_file}" > "${tmp_file}"
  mv "${tmp_file}" "${env_file}"
}

printf 'Configurando DataIF .env\n'
printf 'Template: %s\n' "${template_file}"
printf 'Destino: %s\n\n' "${env_file}"

if [ -f "${env_file}" ] && [ "${DATAIF_FORCE_ENV:-false}" = "true" ]; then
  cp "${template_file}" "${env_file}"
elif [ -f "${env_file}" ]; then
  overwrite="$(read_value "Sobrescrever .env existente? (s/N)" "N")"
  case "${overwrite}" in
    s|S|sim|SIM) cp "${template_file}" "${env_file}" ;;
    *) printf 'Mantendo arquivo existente.\n' ;;
  esac
else
  cp "${template_file}" "${env_file}"
fi

public_base_url="$(read_value "URL publica da aplicacao" "http://localhost:5173")"
web_port="$(read_value "Porta Web" "5173")"
api_port="$(read_value "Porta API" "8000")"
postgres_port="$(read_value "Porta Postgres host" "5433")"
metabase_port="$(read_value "Porta Metabase host" "3000")"
airflow_port="$(read_value "Porta Airflow host" "8088")"
keycloak_port="$(read_value "Porta Keycloak host" "8081")"
vanna_port="$(read_value "Porta Vanna host" "9000")"
image_registry="$(read_value "Registry imagens" "docker.io/dataif")"
image_tag="$(read_value "Tag imagens" "latest")"
admin_email="$(read_value "Email admin" "admin@dataif.local")"
llm_provider="$(read_value "Provider Vanna (ollama/maritaca)" "ollama")"
maritaca_key=""

if [ "${llm_provider}" = "maritaca" ]; then
  maritaca_key="$(read_secret "Chave Maritaca" "")"
fi

set_env COMPOSE_PROJECT_NAME "$(read_value "Nome projeto Compose" "dataif")"
set_env DATAIF_IMAGE_REGISTRY "${image_registry}"
set_env DATAIF_IMAGE_TAG "${image_tag}"
set_env WEB_PORT "${web_port}"
set_env API_PORT "${api_port}"
set_env POSTGRES_EXPOSE_PORT "${postgres_port}"
set_env METABASE_PORT "${metabase_port}"
set_env AIRFLOW_PORT "${airflow_port}"
set_env KEYCLOAK_PORT "${keycloak_port}"
set_env VANNA_PORT "${vanna_port}"
set_env METABASE_SITE_URL "${public_base_url%/}/metabase"
set_env METABASE_ADMIN_EMAIL "${admin_email}"
set_env AIRFLOW_ADMIN_EMAIL "${admin_email}"
set_env VANNA_LLM_PROVIDER "${llm_provider}"
set_env VANNA_MARITACA_API_KEY "${maritaca_key}"

set_env POSTGRES_SUPERUSER_PASSWORD "$(read_secret "Senha Postgres superuser" "$(random_secret)")"
set_env DATAIF_ETL_PASSWORD "$(read_secret "Senha usuario ETL" "$(random_secret)")"
set_env DATAIF_METABASE_PASSWORD "$(read_secret "Senha usuario Metabase" "$(random_secret)")"
set_env DATAIF_VANNA_PASSWORD "$(read_secret "Senha usuario Vanna" "$(random_secret)")"
set_env AIRFLOW_DB_PASSWORD "$(read_secret "Senha banco Airflow" "$(random_secret)")"
set_env METABASE_APP_DB_PASSWORD "$(read_secret "Senha banco Metabase" "$(random_secret)")"
set_env AIRFLOW_ADMIN_PASSWORD "$(read_secret "Senha admin Airflow" "$(random_secret)")"
set_env METABASE_ADMIN_PASSWORD "$(read_secret "Senha admin Metabase" "$(random_secret)")"
set_env KEYCLOAK_ADMIN_PASSWORD "$(read_secret "Senha admin Keycloak" "$(random_secret)")"
set_env METABASE_EMBED_SECRET "$(read_secret "Segredo embed Metabase" "$(random_secret)")"

chmod 600 "${env_file}"

printf '\n.env configurado: %s\n' "${env_file}"
printf 'Valide com: docker compose --env-file %s -f %s config >/dev/null\n' "${env_file}" "${compose_file}"
