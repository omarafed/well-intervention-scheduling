#!/usr/bin/env bash
# Runs on the dedicated server, with deployment values supplied by GitHub Actions.
set -euo pipefail
umask 077

for key in GHCR_TOKEN GHCR_USER IMAGE_PREFIX DEPLOY_TAG TARGET_HOST RELEASE_FILES; do
  if [ -z "${!key:-}" ]; then
    echo "Missing required deployment setting: $key" >&2
    exit 1
  fi
done
APP_PORT=${APP_PORT:-3010}
API_PORT=${API_PORT:-8090}
BIND_ADDRESS=${BIND_ADDRESS:-0.0.0.0}
DEPLOY_DIR=${DEPLOY_DIR:-/opt/bayu-platform/staging}
for port in "$APP_PORT" "$API_PORT"; do
  if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    echo 'APP_PORT and API_PORT must be valid TCP ports' >&2
    exit 1
  fi
done
if [ "$APP_PORT" = "$API_PORT" ]; then
  echo 'APP_PORT and API_PORT must differ' >&2
  exit 1
fi
PUBLIC_APP_URL=${PUBLIC_APP_URL:-http://${TARGET_HOST}:${APP_PORT}}
PUBLIC_API_BASE=${PUBLIC_API_BASE:-http://${TARGET_HOST}:${API_PORT}/api}
# Keep generated Compose dotenv files literal: reject multiline/interpolated values.
for key in IMAGE_PREFIX DEPLOY_TAG BIND_ADDRESS PUBLIC_APP_URL PUBLIC_API_BASE; do
  value=${!key}
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* || "$value" == *\$* || "$value" == *\'* || "$value" == *\"* || "$value" == *' '* || "$value" == *'#'* ]]; then
    echo "Unsupported characters in $key" >&2
    exit 1
  fi
done
if [[ ! "$DEPLOY_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
  echo 'DEPLOY_TAG is not a valid Docker image tag' >&2
  exit 1
fi
if [[ ! "$PUBLIC_APP_URL" =~ ^https?://[^/]+$ ]] || [[ ! "$PUBLIC_API_BASE" =~ ^https?://.+/api$ ]]; then
  echo 'PUBLIC_APP_URL must be an origin without a trailing slash; PUBLIC_API_BASE must end in /api' >&2
  exit 1
fi

# This is an existing EDAFY host: require its Docker installation, never alter it.
docker compose version >/dev/null
command -v openssl >/dev/null
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"
# Serialize server-side deployments too, including any manual invocations.
exec 9>.deploy.lock
flock -w 1200 9
install -m 600 "$RELEASE_FILES/revamped/compose.staging.yaml" compose.staging.yaml

# Preserve credentials across deployments so existing data remains accessible.
if [ ! -f .env.prod ]; then
  {
    printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'SERVICE_TOKEN=%s\n' "$(openssl rand -hex 32)"
    printf 'MINIO_ROOT_USER=bayu-platform\n'
    printf 'MINIO_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 24)"
  } > .env.prod
fi
chmod 600 .env.prod

release_env=$(mktemp "$DEPLOY_DIR/.env.release.XXXXXX")
docker_config=$(mktemp -d)
export DOCKER_CONFIG="$docker_config"
cleanup() {
  rm -f "$release_env"
  rm -rf "$docker_config"
}
trap cleanup EXIT
{
  printf 'IMAGE_PREFIX=%s\n' "$IMAGE_PREFIX"
  printf 'TAG=%s\n' "$DEPLOY_TAG"
  printf 'APP_PORT=%s\n' "$APP_PORT"
  printf 'API_PORT=%s\n' "$API_PORT"
  printf 'BIND_ADDRESS=%s\n' "$BIND_ADDRESS"
  printf 'CORS_ORIGINS=%s\n' "$PUBLIC_APP_URL"
  printf 'NUXT_PUBLIC_API_BASE=%s\n' "$PUBLIC_API_BASE"
} > "$release_env"
# Explicit project name keeps networks and volumes separate from EDAFY and local Compose.
compose=(docker compose --project-name bayu-platform-staging --env-file .env.prod --env-file "$release_env" -f compose.staging.yaml)
"${compose[@]}" config --quiet
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
"${compose[@]}" pull
if ! "${compose[@]}" up -d --wait --wait-timeout 240; then
  "${compose[@]}" ps
  "${compose[@]}" logs --tail=80 api worker optimizer frontend
  echo 'Deployment did not become healthy. Fix the reported error and rerun the workflow.' >&2
  exit 1
fi
# Check HTTP success explicitly rather than accepting any responding status code.
curl --fail --silent --show-error --retry 6 --retry-delay 5 --retry-connrefused "http://127.0.0.1:${API_PORT}/health" >/dev/null
curl --fail --silent --show-error --retry 6 --retry-delay 5 --retry-connrefused "http://127.0.0.1:${APP_PORT}/" >/dev/null
mv -f "$release_env" .env.release
printf 'Deployed %s\nFrontend: %s\nAPI: %s\n' "$DEPLOY_TAG" "$PUBLIC_APP_URL" "$PUBLIC_API_BASE"
