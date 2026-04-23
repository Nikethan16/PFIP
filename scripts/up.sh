#!/usr/bin/env bash
# up.sh — bring up the PFIP Docker stack.
# Usage: scripts/up.sh [service] [--build]
set -euo pipefail
. "$(dirname "$0")/_common.sh"

SERVICE=""
BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    -h|--help)
      sed -n '1,10p' "$0"; exit 0 ;;
    *) SERVICE="$arg" ;;
  esac
done

log_step 'PFIP — starting stack'
assert_env_file
assert_docker_running

args=(up -d)
[ "$BUILD" -eq 1 ] && args+=(--build)
[ -n "$SERVICE" ] && args+=("$SERVICE")

compose "${args[@]}"

BE_PORT="$(env_get BACKEND_PORT)"   ; BE_PORT="${BE_PORT:-8000}"
FE_PORT="$(env_get FRONTEND_PORT)"  ; FE_PORT="${FE_PORT:-3000}"
PR_PORT="$(env_get PREFECT_PORT)"   ; PR_PORT="${PR_PORT:-4200}"
ML_PORT="$(env_get MLFLOW_PORT)"    ; ML_PORT="${ML_PORT:-5000}"
QD_PORT="$(env_get QDRANT_HTTP_PORT)"; QD_PORT="${QD_PORT:-6333}"
UK_PORT="$(env_get UPTIME_KUMA_PORT)"; UK_PORT="${UK_PORT:-3001}"
OL_PORT="$(env_get OLLAMA_PORT)"    ; OL_PORT="${OL_PORT:-11434}"

echo ""
log_ok "Stack is up. Service URLs:"
printf "  %-14s %s\n" "Frontend"    "http://localhost:${FE_PORT}"
printf "  %-14s %s\n" "Backend API" "http://localhost:${BE_PORT}/docs"
printf "  %-14s %s\n" "Prefect"     "http://localhost:${PR_PORT}"
printf "  %-14s %s\n" "MLflow"      "http://localhost:${ML_PORT}"
printf "  %-14s %s\n" "Qdrant"      "http://localhost:${QD_PORT}/dashboard"
printf "  %-14s %s\n" "Uptime Kuma" "http://localhost:${UK_PORT}"
printf "  %-14s %s\n" "Ollama"      "http://localhost:${OL_PORT}"
echo ""
log_info 'Next: run `scripts/health.sh` to verify everything is healthy.'
