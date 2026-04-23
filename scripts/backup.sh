#!/usr/bin/env bash
# backup.sh — nightly backup: TimescaleDB + Qdrant + MLflow mirror + optional rclone.
# Retention: 30 daily + 12 monthly + 5 yearly for the dated DB dumps and qdrant/mlflow dirs.
#
# Environment overrides:
#   RCLONE_REMOTE   if set, push backups dir to this remote (e.g., "b2:pfip-backups")
#   SKIP_RCLONE=1   skip the rclone step even if RCLONE_REMOTE set.
set -euo pipefail
. "$(dirname "$0")/_common.sh"

assert_docker_running

STAMP="$(date +%Y%m%d-%H%M)"
DATE_TAG="$(date +%Y%m%d)"

DB_DIR="$BACKUPS_DIR/db"
QD_DIR="$BACKUPS_DIR/qdrant"
ML_DIR="$BACKUPS_DIR/mlflow"
LOG_FILE="$BACKUPS_DIR/backup.log"

mkdir -p "$BACKUPS_DIR" "$DB_DIR" "$QD_DIR" "$ML_DIR"

log_line() {
  local level="$1"; shift
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$*" >> "$LOG_FILE"
}

log_line INFO "backup start stamp=$STAMP"
log_step "PFIP backup — $STAMP"

# ----------------------------------------------------------------
# 1) TimescaleDB pg_dump
# ----------------------------------------------------------------
PG_USER="$(env_get POSTGRES_USER)"; PG_USER="${PG_USER:-pfip}"
PG_DB="$(env_get POSTGRES_DB)"    ; PG_DB="${PG_DB:-pfip}"
DB_OUT="$DB_DIR/pfip-${STAMP}.sql.gz"

if ! container_running pfip-timescaledb; then
  log_err 'pfip-timescaledb is not running; cannot pg_dump.'
  log_line ERROR 'pg_dump skipped (container not running)'
  exit 1
fi

log_info "pg_dump -> $DB_OUT"
if docker exec -i pfip-timescaledb sh -c "pg_dump -U '$PG_USER' -d '$PG_DB' -Fc | gzip -c" > "$DB_OUT"; then
  size=$(stat -c%s "$DB_OUT" 2>/dev/null || stat -f%z "$DB_OUT" 2>/dev/null || echo 0)
  if [ "$size" -lt 100 ]; then
    log_err "pg_dump output suspiciously small ($size bytes)"
    log_line ERROR "pg_dump small ($size bytes) -> $DB_OUT"
    exit 2
  fi
  log_ok "pg_dump ok ($size bytes)"
  log_line OK "pg_dump wrote $DB_OUT ($size bytes)"
else
  log_err 'pg_dump failed'
  log_line ERROR 'pg_dump failed'
  exit 2
fi

# ----------------------------------------------------------------
# 2) Qdrant snapshots
# ----------------------------------------------------------------
QD_PORT="$(env_get QDRANT_HTTP_PORT)"; QD_PORT="${QD_PORT:-6333}"
QD_DAY="$QD_DIR/$DATE_TAG"
mkdir -p "$QD_DAY"

log_info "Qdrant snapshots -> $QD_DAY"
if command -v curl >/dev/null 2>&1; then
  cols_json="$(curl -s --max-time 10 "http://localhost:${QD_PORT}/collections" || true)"
  # Extract collection names without jq (best-effort).
  colls="$(echo "$cols_json" | grep -oE '"name"[^,}]*' | head -n50 | sed -E 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true)"

  if [ -z "$colls" ]; then
    log_warn 'No Qdrant collections yet — skipping snapshot step.'
    log_line WARN 'qdrant no collections'
  else
    for c in $colls; do
      snap_resp="$(curl -s -X POST --max-time 120 "http://localhost:${QD_PORT}/collections/${c}/snapshots" || true)"
      snap_name="$(echo "$snap_resp" | grep -oE '"name"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 | sed -E 's/.*"([^"]+)".*/\1/' || true)"
      if [ -z "$snap_name" ]; then
        log_warn "qdrant snapshot create failed for $c"
        log_line WARN "qdrant snapshot create failed: $c"
        continue
      fi
      dst="$QD_DAY/${c}-${snap_name}"
      if curl -s --max-time 600 -o "$dst" "http://localhost:${QD_PORT}/collections/${c}/snapshots/${snap_name}"; then
        log_ok "qdrant snap: $c => $dst"
        log_line OK "qdrant snapshot $c -> $dst"
      else
        log_warn "qdrant snapshot download failed for $c"
        log_line WARN "qdrant snapshot download failed: $c"
      fi
    done
  fi
else
  log_warn 'curl not installed; skipping qdrant snapshots.'
  log_line WARN 'curl missing'
fi

# ----------------------------------------------------------------
# 3) MLflow volume mirror via alpine rsync
# ----------------------------------------------------------------
ML_DAY="$ML_DIR/$DATE_TAG"
mkdir -p "$ML_DAY"

log_info "MLflow mirror -> $ML_DAY"
ML_DAY_ABS="$(cd "$ML_DAY" && pwd)"
# On Windows Git Bash, /c/Users/... must be translated for docker. MSYS_NO_PATHCONV=1 stops auto-convert.
if docker run --rm \
    -v "pfip_mlflow_data:/src:ro" \
    -v "${ML_DAY_ABS}:/dst" \
    alpine:3.19 \
    sh -c 'apk add --no-cache rsync >/dev/null && rsync -a --delete /src/ /dst/'; then
  log_ok 'MLflow mirror ok'
  log_line OK "mlflow mirror -> $ML_DAY"
else
  log_warn 'MLflow mirror failed'
  log_line WARN 'mlflow mirror failed'
fi

# ----------------------------------------------------------------
# 4) Optional rclone push
# ----------------------------------------------------------------
if [ "${SKIP_RCLONE:-0}" != "1" ] && [ -n "${RCLONE_REMOTE:-}" ]; then
  log_info "rclone push -> $RCLONE_REMOTE"
  if rclone copy "$BACKUPS_DIR" "$RCLONE_REMOTE" --transfers 4 --checkers 4 --stats 30s --log-level NOTICE; then
    log_ok 'rclone push ok'
    log_line OK "rclone push -> $RCLONE_REMOTE"
  else
    log_warn 'rclone push failed'
    log_line WARN 'rclone push failed'
  fi
elif [ -z "${RCLONE_REMOTE:-}" ]; then
  log_info 'RCLONE_REMOTE not set — skipping off-site push.'
fi

# ----------------------------------------------------------------
# 5) Retention: 30 daily + 12 monthly + 5 yearly
# ----------------------------------------------------------------
# Helpers: given a newline-separated list of "YYYYMMDD<tab>path", print the set to KEEP.
compute_keep() {
  local daily=30 monthly=12 yearly=5
  local input
  input="$(cat)"
  [ -z "$input" ] && return 0

  local sorted
  sorted="$(printf '%s\n' "$input" | sort -r)"

  # Daily: top N.
  printf '%s\n' "$sorted" | head -n "$daily" | cut -f2

  # Monthly: one per YYYYMM, up to N.
  printf '%s\n' "$sorted" | awk -F'\t' -v n="$monthly" '
    { ym = substr($1,1,6); if (!(ym in seen)) { seen[ym]=1; print $2; c++; if (c>=n) exit } }
  '
  # Yearly: one per YYYY, up to N.
  printf '%s\n' "$sorted" | awk -F'\t' -v n="$yearly" '
    { y = substr($1,1,4); if (!(y in seen)) { seen[y]=1; print $2; c++; if (c>=n) exit } }
  '
}

apply_retention_files() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  local candidates keep
  candidates="$(find "$dir" -maxdepth 1 -type f -name 'pfip-*.sql.gz' | while read -r f; do
    base="$(basename "$f")"
    if [[ "$base" =~ pfip-([0-9]{8})-([0-9]{4})\.sql\.gz ]]; then
      printf '%s\t%s\n' "${BASH_REMATCH[1]}" "$f"
    fi
  done)"
  [ -z "$candidates" ] && return 0
  keep="$(printf '%s\n' "$candidates" | compute_keep | sort -u)"
  printf '%s\n' "$candidates" | cut -f2 | sort -u | while read -r path; do
    if ! printf '%s\n' "$keep" | grep -Fxq "$path"; then
      log_info "retention: delete $path"
      log_line INFO "retention deleted $path"
      rm -f -- "$path"
    fi
  done
}

apply_retention_dirs() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  local candidates keep
  candidates="$(find "$dir" -mindepth 1 -maxdepth 1 -type d | while read -r d; do
    base="$(basename "$d")"
    if [[ "$base" =~ ^[0-9]{8}$ ]]; then
      printf '%s\t%s\n' "$base" "$d"
    fi
  done)"
  [ -z "$candidates" ] && return 0
  keep="$(printf '%s\n' "$candidates" | compute_keep | sort -u)"
  printf '%s\n' "$candidates" | cut -f2 | sort -u | while read -r path; do
    if ! printf '%s\n' "$keep" | grep -Fxq "$path"; then
      log_info "retention: delete dir $path"
      log_line INFO "retention deleted dir $path"
      rm -rf -- "$path"
    fi
  done
}

log_step 'Retention pass'
apply_retention_files "$DB_DIR"
apply_retention_dirs  "$QD_DIR"
apply_retention_dirs  "$ML_DIR"

log_line OK "backup end stamp=$STAMP"
log_ok "Backup complete — $STAMP"
