#!/usr/bin/env bash
# Release smoke checks for the Docker image (package help, OCR langs, HTTP endpoints).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${DEEPSEEK_CURSOR_GATEWAY_SMOKE_IMAGE:-deepseek-cursor-gateway:smoke}"
PORT="${DEEPSEEK_CURSOR_GATEWAY_SMOKE_PORT:-19090}"

if ! command -v docker >/dev/null 2>&1; then
    echo "SKIP: docker not available"
    exit 0
fi

cd "$REPO_ROOT"

echo "==> docker build -t ${IMAGE}"
docker build -t "${IMAGE}" .

echo "==> package --help"
docker run --rm --entrypoint deepseek-cursor-gateway "${IMAGE}" --help >/dev/null

echo "==> tesseract --list-langs"
langs="$(docker run --rm --entrypoint tesseract "${IMAGE}" --list-langs)"
echo "${langs}"
echo "${langs}" | grep -q '^eng$'
echo "${langs}" | grep -q '^chi_sim$'

cid="$(docker run -d --rm -p "127.0.0.1:${PORT}:9000" "${IMAGE}")"
cleanup() {
    docker rm -f "${cid}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

deadline=$((SECONDS + 60))
until curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
        echo "FAIL: gateway did not become ready on port ${PORT}"
        docker logs "${cid}" || true
        exit 1
    fi
    sleep 1
done

echo "==> GET /healthz"
curl -fsS "http://127.0.0.1:${PORT}/healthz" | grep -q '"ok":true'

echo "==> GET /readyz"
curl -fsS "http://127.0.0.1:${PORT}/readyz" | grep -q '"ready":true'

echo "==> GET /v1/models"
curl -fsS "http://127.0.0.1:${PORT}/v1/models" | grep -q '"object":"list"'

echo "==> GET /metrics"
curl -fsS "http://127.0.0.1:${PORT}/metrics" | grep -q 'gateway_requests_total'

echo "Docker smoke checks passed."
