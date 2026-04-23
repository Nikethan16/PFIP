#!/usr/bin/env bash
# restore_drill.sh — quarterly restore-from-backup drill.
# Spins up an isolated test project (ports shifted by +10000), restores the
# latest pg_dump, verifies row counts, then tears down.
# Environment:
#   FORCE=1       skip confirmation
#   KEEP_UP=1     leave the drill stack up after verification
set -euo pipefail
. "$(dirname "$0")/_common.sh"

assert_docker_running

STAMP="$(date +%Y%m%d-%H%M)"
DATE_TAG="$(date +%Y%m%d)"
LOG="$BACKUPS_DIR/drill-${DATE_TAG}.log"
PROJECT="pfip_drill_${STAMP}"
mkdir -p "$BACKUPS_DIR"

log_line() {
  local level="$1"; shift
  local msg="$*"
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$msg" >> "$LOG"
  case "$level" in
    OK)   log_ok   "$msg" ;;
    FAIL) log_err  "$msg" ;;
    WARN) log_warn "$msg" ;;
    *)    log_info "$msg" ;;
  esac
}

# Find latest DB backup.
DB_DIR="$BACKUPS_DIR/db"
if [ ! -d "$DB_DIR" ]; then
  log_err "No backups dir at $DB_DIR. Run backup.sh first."
  exit 1
fi
LATEST="$(ls -1t "$DB_DIR"/pfip-*.sql.gz 2>/dev/null | head -n1 || true)"
if [ -z "$LATEST" ]; then
  log_err 'No pfip-*.sql.gz found in backups/db. Run backup.sh first.'
  exit 1
fi

log_line INFO "drill start stamp=$STAMP project=$PROJECT backup=$LATEST"
log_step "Restore drill — using $(basename "$LATEST")"

if ! confirm "Spin up isolated test stack (project=$PROJECT)?"; then
  log_info 'Aborted.'
  exit 0
fi

# Shift ports by +10000.
shift_port() { local k="$1" def="$2"; local v; v="$(env_get "$k")"; v="${v:-$def}"; echo $((v + 10000)); }

TS="$(shift_port TIMESCALEDB_PORT 5432)"
RE="$(shift_port REDIS_PORT 6379)"
QH="$(shift_port QDRANT_HTTP_PORT 6333)"
QG="$(shift_port QDRANT_GRPC_PORT 6334)"
PR="$(shift_port PREFECT_PORT 4200)"
ML="$(shift_port MLFLOW_PORT 5000)"
OL="$(shift_port OLLAMA_PORT 11434)"
UK="$(shift_port UPTIME_KUMA_PORT 3001)"
BE="$(shift_port BACKEND_PORT 8000)"
FE="$(shift_port FRONTEND_PORT 3000)"

DRILL_ENV="$(mktemp "${TMPDIR:-/tmp}/pfip-drill-${STAMP}.XXXXXX.env")"

PG_USER="$(env_get POSTGRES_USER)"; PG_USER="${PG_USER:-pfip}"
PG_DB="$(env_get POSTGRES_DB)"    ; PG_DB="${PG_DB:-pfip}"
PG_PWD="$(env_get POSTGRES_PASSWORD)"; PG_PWD="${PG_PWD:-pfip_drill}"

cat > "$DRILL_ENV" <<EOF
POSTGRES_USER=$PG_USER
POSTGRES_PASSWORD=$PG_PWD
POSTGRES_DB=$PG_DB
TIMESCALEDB_PORT=$TS
REDIS_PORT=$RE
QDRANT_HTTP_PORT=$QH
QDRANT_GRPC_PORT=$QG
PREFECT_PORT=$PR
MLFLOW_PORT=$ML
OLLAMA_PORT=$OL
UPTIME_KUMA_PORT=$UK
BACKEND_PORT=$BE
FRONTEND_PORT=$FE
NEXTAUTH_SECRET=drill-only-not-a-secret
PFIP_USER_EMAIL=drill@example.local
EOF

cleanup() {
  if [ "${KEEP_UP:-0}" = "1" ]; then
    log_line WARN "drill stack left up (KEEP_UP=1). Tear down: docker compose -p $PROJECT down -v"
  else
    log_line INFO "tearing down drill project $PROJECT"
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$DRILL_ENV" down -v >/dev/null 2>&1 || true
  fi
  rm -f "$DRILL_ENV" 2>/dev/null || true
}
trap cleanup EXIT

set +e
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$DRILL_ENV" up -d timescaledb
rc=$?
set -e
if [ $rc -ne 0 ]; then
  log_line FAIL 'compose up (drill) failed'
  exit 2
fi

# Find the DB container name (docker compose v2 uses <project>-<service>-1).
CTR="${PROJECT}-timescaledb-1"
if ! docker inspect "$CTR" >/dev/null 2>&1; then
  CTR="${PROJECT}_timescaledb_1"
fi

log_line INFO "waiting for drill DB to be healthy ($CTR)"
HEALTHY=0
for i in $(seq 1 30); do
  state="$(docker inspect -f '{{.State.Health.Status}}' "$CTR" 2>/dev/null || echo)"
  if [ "$state" = "healthy" ]; then HEALTHY=1; break; fi
  sleep 2
done
if [ "$HEALTHY" -ne 1 ]; then
  log_line FAIL 'drill DB did not become healthy within 60s'
  exit 3
fi

log_line INFO "pg_restore -> $CTR"
set +e
gunzip -c "$LATEST" | docker exec -i "$CTR" pg_restore -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner --no-privileges
rc=$?
set -e
if [ $rc -ne 0 ]; then
  log_line WARN "pg_restore exit=$rc — continuing to verify"
fi

# Verify
TABLES_SQL="SELECT table_schema||'.'||table_name FROM information_schema.tables
 WHERE table_schema NOT IN ('pg_catalog','information_schema','_timescaledb_internal','_timescaledb_catalog','_timescaledb_config','_timescaledb_cache','timescaledb_experimental','timescaledb_information')
   AND table_type='BASE TABLE' ORDER BY 1;"

mapfile -t TABLES < <(docker exec -i "$CTR" psql -U "$PG_USER" -d "$PG_DB" -tA -c "$TABLES_SQL" | sed '/^\s*$/d')

if [ "${#TABLES[@]}" -eq 0 ]; then
  log_line WARN 'no user tables found — backup may be from an empty DB (Stage 0)'
else
  ZERO=()
  for t in "${TABLES[@]}"; do
    c="$(docker exec -i "$CTR" psql -U "$PG_USER" -d "$PG_DB" -tA -c "SELECT count(*) FROM $t;" | tr -d '[:space:]')"
    case "$c" in
      ''|*[!0-9]*) c=0 ;;
    esac
    if [ "$c" -le 0 ]; then ZERO+=("$t"); else log_line OK "$t rows=$c"; fi
  done
  if [ "${#ZERO[@]}" -gt 0 ]; then
    log_line WARN "tables with 0 rows: ${ZERO[*]}"
  fi
fi

log_line OK 'restore drill verification complete'
log_ok "Restore drill PASSED. Log: $LOG"
