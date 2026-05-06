#!/bin/sh
set -eu

enabled="${OLLAMA_MODEL_BOOTSTRAP_ENABLED:-true}"
if [ "$enabled" = "false" ] || [ "$enabled" = "0" ] || [ "$enabled" = "no" ]; then
  echo "Ollama model bootstrap disabled."
  exit 0
fi

ollama_base_url="${OLLAMA_BASE_URL:-http://ollama:11434}"
model_name="${OLLAMA_MODEL_NAME:-${VANNA_OLLAMA_MODEL:-sabia-7b}}"
gguf_url="${OLLAMA_MODEL_GGUF_URL:-}"
gguf_file="${OLLAMA_MODEL_GGUF_FILE:-sabia-7b.Q4_K_M.gguf}"
model_dir="/models/${model_name}"
model_path="${model_dir}/${gguf_file}"
modelfile_template="${OLLAMA_MODELFILE_TEMPLATE:-/bootstrap/sabia-7b.Modelfile}"

if [ -z "$model_name" ]; then
  echo "OLLAMA_MODEL_NAME or VANNA_OLLAMA_MODEL must be set." >&2
  exit 2
fi

wait_for_ollama() {
  tries="${OLLAMA_BOOTSTRAP_WAIT_RETRIES:-60}"
  delay="${OLLAMA_BOOTSTRAP_WAIT_SECONDS:-2}"
  i=1
  while [ "$i" -le "$tries" ]; do
    if curl -fsS "${ollama_base_url%/}/api/tags" >/tmp/ollama-tags.json; then
      return 0
    fi
    echo "Waiting for Ollama at ${ollama_base_url} (${i}/${tries})..."
    sleep "$delay"
    i=$((i + 1))
  done
  echo "Ollama did not become reachable at ${ollama_base_url}." >&2
  exit 1
}

model_exists() {
  curl -fsS "${ollama_base_url%/}/api/tags" >/tmp/ollama-tags.json
  grep -Eq "\"(name|model)\"[[:space:]]*:[[:space:]]*\"${model_name}(:latest)?\"" /tmp/ollama-tags.json
}

download_gguf() {
  if [ -f "$model_path" ]; then
    echo "GGUF already present at ${model_path}."
    return 0
  fi
  if [ -z "$gguf_url" ]; then
    echo "OLLAMA_MODEL_GGUF_URL is required because ${model_path} is missing." >&2
    exit 2
  fi

  mkdir -p "$model_dir"
  tmp_path="${model_path}.part"
  echo "Downloading ${model_name} GGUF to ${model_path}..."
  if [ -n "${HF_TOKEN:-}" ]; then
    curl -fL --retry 5 --retry-delay 10 -H "Authorization: Bearer ${HF_TOKEN}" -o "$tmp_path" "$gguf_url"
  else
    curl -fL --retry 5 --retry-delay 10 -o "$tmp_path" "$gguf_url"
  fi

  mv "$tmp_path" "$model_path"
}

json_escape_file() {
  sed "s#__MODEL_GGUF_PATH__#${model_path}#g" "$modelfile_template" \
    | sed 's/\\/\\\\/g; s/"/\\"/g' \
    | awk '{printf "%s\\n", $0}'
}

create_model() {
  escaped_modelfile="$(json_escape_file)"
  payload="/tmp/ollama-create-model.json"
  printf '{"name":"%s","modelfile":"%s","stream":false}\n' "$model_name" "$escaped_modelfile" >"$payload"

  echo "Creating Ollama model ${model_name} from ${model_path}..."
  curl -fsS \
    -H "Content-Type: application/json" \
    --data-binary "@${payload}" \
    "${ollama_base_url%/}/api/create"
  echo
}

wait_for_ollama
if model_exists; then
  echo "Ollama model ${model_name} already exists."
  exit 0
fi

download_gguf
create_model

if model_exists; then
  echo "Ollama model ${model_name} is ready."
  exit 0
fi

echo "Ollama model ${model_name} was not visible after creation." >&2
exit 1
