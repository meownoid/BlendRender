#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
host_arch="$(uname -m)"
if [[ "$host_arch" == "arm64" ]]; then
  host_arch="aarch64"
fi

colima_arch="${BLENDQUEUE_E2E_ARCH:-$host_arch}"
image_platform="${BLENDQUEUE_E2E_PLATFORM:-linux/amd64}"
profile="${BLENDQUEUE_E2E_PROFILE:-blendqueue-e2e-${colima_arch}}"
image="${BLENDQUEUE_E2E_IMAGE:-blendqueue:e2e}"
container="${BLENDQUEUE_E2E_CONTAINER:-blendqueue-e2e}"
port="${BLENDQUEUE_E2E_PORT:-18000}"
password="${BLENDQUEUE_E2E_PASSWORD:-blendqueue-e2e-password}"
blend_file="${BLENDQUEUE_E2E_BLEND:-$project_root/tests/fixtures/test.blend}"
timeout="${BLENDQUEUE_E2E_TIMEOUT:-600}"
started_colima=0

if [[ "$colima_arch" != "aarch64" && "$colima_arch" != "x86_64" ]]; then
  echo "BLENDQUEUE_E2E_ARCH must be aarch64 or x86_64" >&2
  exit 2
fi
if [[ "$image_platform" != "linux/amd64" ]]; then
  echo "Blender 5.2.1 has no official Linux ARM64 archive; use linux/amd64" >&2
  exit 2
fi
if [[ ! -f "$blend_file" ]]; then
  echo "Blend fixture not found: $blend_file" >&2
  exit 2
fi

cleanup() {
  docker --context "colima-$profile" rm -f "$container" >/dev/null 2>&1 || true
  if [[ "$started_colima" == "1" && "${BLENDQUEUE_E2E_KEEP_COLIMA:-0}" != "1" ]]; then
    colima stop --profile "$profile" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! colima status --profile "$profile" >/dev/null 2>&1; then
  colima start --profile "$profile" --arch "$colima_arch" --runtime docker \
    --activate=false --vm-type vz --cpus "${BLENDQUEUE_E2E_CPUS:-4}" \
    --memory "${BLENDQUEUE_E2E_MEMORY:-8}" --disk "${BLENDQUEUE_E2E_DISK:-30}"
  started_colima=1
fi

actual_arch="$(colima status --profile "$profile" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["arch"])')"
if [[ "$actual_arch" != "$colima_arch" ]]; then
  echo "Colima profile $profile uses $actual_arch, expected $colima_arch" >&2
  exit 2
fi

docker_context="colima-$profile"
(
  cd "$project_root/frontend"
  npm ci
  npm run build
)
if docker buildx version >/dev/null 2>&1; then
  DOCKER_BUILDKIT=1 docker --context "$docker_context" build \
    --platform "$image_platform" -f "$project_root/Dockerfile.e2e" \
    -t "$image" "$project_root"
else
  DOCKER_BUILDKIT=0 docker --context "$docker_context" build \
    --platform "$image_platform" -f "$project_root/Dockerfile.e2e" \
    -t "$image" "$project_root"
fi
docker --context "$docker_context" rm -f "$container" >/dev/null 2>&1 || true
docker --context "$docker_context" run --detach --name "$container" \
  --platform "$image_platform" -p "127.0.0.1:${port}:8000" \
  -e APP_PASSWORD="$password" -e COOKIE_SECURE=false "$image" >/dev/null

for _ in $(seq 1 120); do
  if curl --fail --silent "http://127.0.0.1:${port}/readyz" >/dev/null; then
    break
  fi
  if [[ "$(docker --context "$docker_context" inspect -f '{{.State.Running}}' "$container")" != "true" ]]; then
    docker --context "$docker_context" logs "$container" >&2
    exit 1
  fi
  sleep 1
done
curl --fail --silent "http://127.0.0.1:${port}/readyz" >/dev/null

python3 "$project_root/scripts/e2e_backend.py" \
  --base-url "http://127.0.0.1:${port}" --password "$password" \
  --blend "$blend_file" --timeout "$timeout"
