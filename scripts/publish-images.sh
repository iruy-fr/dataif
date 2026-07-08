#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${DATAIF_IMAGE_REGISTRY:-docker.io/dataif}"
TAG="${DATAIF_IMAGE_TAG:-0.1.3}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_FLAGS=(--pull)

if [ -n "${DATAIF_BUILD_FLAGS:-}" ]; then
  read -r -a EXTRA_BUILD_FLAGS <<<"${DATAIF_BUILD_FLAGS}"
  BUILD_FLAGS+=("${EXTRA_BUILD_FLAGS[@]}")
fi

build_and_push() {
  local image_name="$1"
  local context_dir="$2"
  local dockerfile_path="$3"

  printf 'Building %s/%s:%s\n' "${REGISTRY}" "${image_name}" "${TAG}"
  docker build "${BUILD_FLAGS[@]}" -t "${REGISTRY}/${image_name}:${TAG}" -f "${dockerfile_path}" "${context_dir}"
  printf 'Pushing %s/%s:%s\n' "${REGISTRY}" "${image_name}" "${TAG}"
  docker push "${REGISTRY}/${image_name}:${TAG}"
}

build_and_push "dataif-airflow" "${ROOT_DIR}" "${ROOT_DIR}/infra/airflow/Dockerfile.release"
build_and_push "dataif-api" "${ROOT_DIR}/services/api" "${ROOT_DIR}/services/api/Dockerfile"
build_and_push "dataif-web" "${ROOT_DIR}/services/web" "${ROOT_DIR}/services/web/Dockerfile"
build_and_push "dataif-vanna" "${ROOT_DIR}/services/vanna" "${ROOT_DIR}/services/vanna/Dockerfile"
build_and_push "dataif-ollama-bootstrap" "${ROOT_DIR}/infra/ollama" "${ROOT_DIR}/infra/ollama/Dockerfile"
