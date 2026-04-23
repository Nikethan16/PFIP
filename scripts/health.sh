#!/usr/bin/env bash
# health.sh — check every PFIP service and report PASS/FAIL.
# Exits non-zero if any fail.
set -euo pipefail
. "$(dirname "$0")/_common.sh"

TIMEOUT="${TIMEOUT:-5}"

BE="$(env_get BACKEND_PORT)"      ; BE="${BE:-8000}"
FE="$(env_get FRONTEND_PORT)"     ; FE="${FE:-3000}"
PR="$(env_get PREFECT_PORT)"      ; PR="${PR:-4200}"
ML="$(env_get MLFLOW_PORT)"       ; ML="${ML:-5000}"
QD="$(env_get QDRANT_HTTP_PORT)"  ; QD="${QD:-6333}"
UK="$(env_get UPTIME_KUMA_PORT)"  ; UK="${UK:-3001}"
OL="$(env_get OLLAMA_PORT)"       ; OL="${OL:-11434}"
PG_USER="$(env_get POSTGRES_USER)"; PG_USER="${PG_USER:-pfip}"
PG_DB="$(env_get POSTGRES_DB)"    ; PG_DB="${PG_DB:-pfip}"

FAILS=0
REPORT=""

record() {
  local name="$1" ok="$2" detail="$3"
  local status
  if [ "$ok" = "1" ]; then status="PASS"; else status="FAIL"; FAILS=$((FAILS+1)); fi
  if [ "$status" = "PASS" ]; then
    REPORT+="$(printf "  ${C_GRN}[PASS]${C_RST} %-12s %s\n" "$name" "$detail")"
  else
    REPORT+="$(printf "  ${C_RED}[FAIL]${C_RST} %-12s %s\n" "$name" "$detail")"
  fi
  REPORT+=$'\n'
}

# TimescaleDB
if docker exec pfip-timescaledb pg_isready -U "$PG_USER" -d "$PG_DB" > /dev/null 2>&1; then
  record 'TimescaleDB' 1 "pg_isready -U $PG_USER -d $PG_DB"
else
  record 'TimescaleDB' 0 "pg_isready -U $PG_USER -d $PG_DB"
fi

# Redis
if docker exec pfip-redis redis-cli PING 2>/dev/null | grep -q PONG; then
  record 'Redis' 1 "redis-cli PING"
else
  record 'Redis' 0 "redis-cli PING"
fi

# HTTP-checked services
for pair in \
  "Qdrant|http://localhost:${QD}/healthz" \
  "Ollama|http://localhost:${OL}/api/tags" \
  "Prefect|http://localhost:${PR}/api/health" \
  "MLflow|http://localhost:${ML}/" \
  "Uptime-Kuma|http://localhost:${UK}/" ; do
  name="${pair%%|*}"; url="${pair#*|}"
  if http_ok "$url" "$TIMEOUT"; then record "$name" 1 "$url"; else record "$name" 0 "$url"; fi
done

# Backend: deep first, fall back to /health
if http_ok "http://localhost:${BE}/api/v1/health/deep" "$TIMEOUT" \
  || http_ok "http://localhost:${BE}/health" "$TIMEOUT"; then
  record 'Backend' 1 "http://localhost:${BE}/api/v1/health/deep"
else
  record 'Backend' 0 "http://localhost:${BE}/api/v1/health/deep"
fi

# Frontend: /api/health first, fall back to /
if http_ok "http://localhost:${FE}/api/health" "$TIMEOUT" \
  || http_ok "http://localhost:${FE}/" "$TIMEOUT"; then
  record 'Frontend' 1 "http://localhost:${FE}/api/health"
else
  record 'Frontend' 0 "http://localhost:${FE}/api/health"
fi

echo ""
printf "%s" "$REPORT"
echo ""

if [ "$FAILS" -gt 0 ]; then
  log_err "$FAILS service(s) unhealthy."
  exit 1
fi
log_ok 'All services healthy.'
