#!/usr/bin/env bash
# PFIP logical backup for managed Neon Postgres.
#
# Dumps DATABASE_URL via pg_dump (custom format, compressed) to a local dir on
# the host, verifies the archive is readable, and rotates old dumps. This is the
# Neon-era replacement for the obsolete docker-based backup.py/restore.py.
#
# Run by the `pfip-backup.timer` systemd timer (see docs/DEPLOY_ORACLE.md).
# Manual run:   bash backend/scripts/backup_neon.sh
# Restore drill: see docs/DEPLOY_ORACLE.md "Backup / restore".
#
# Env overrides:
#   PFIP_ENV_FILE     path to the .env holding DATABASE_URL (default VM backend/.env)
#   PFIP_BACKUP_DIR   where dumps are written (default ~/pfip-backups)
#   PFIP_BACKUP_KEEP  how many dumps to retain (default 14)
#   PG_DUMP/PG_RESTORE  explicit binary paths (default the v18 client)
set -euo pipefail

ENV_FILE="${PFIP_ENV_FILE:-/home/ubuntu/pfip/backend/.env}"
BACKUP_DIR="${PFIP_BACKUP_DIR:-/home/ubuntu/pfip-backups}"
KEEP="${PFIP_BACKUP_KEEP:-14}"
PG_DUMP="${PG_DUMP:-/usr/lib/postgresql/18/bin/pg_dump}"
PG_RESTORE="${PG_RESTORE:-/usr/lib/postgresql/18/bin/pg_restore}"
command -v "$PG_DUMP" >/dev/null 2>&1 || PG_DUMP=pg_dump
command -v "$PG_RESTORE" >/dev/null 2>&1 || PG_RESTORE=pg_restore

# Pull DATABASE_URL from the .env and convert SQLAlchemy -> libpq form.
RAW=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)
RAW="${RAW%\"}"; RAW="${RAW#\"}"          # strip surrounding quotes if present
DB_URL="${RAW/+psycopg/}"                  # postgresql+psycopg:// -> postgresql://
DB_URL="${DB_URL/+asyncpg/}"
if [ -z "$DB_URL" ]; then
  echo "[backup] ERROR: DATABASE_URL not found in $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TS=$(date -u +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/pfip-$TS.dump"

echo "[backup] $(date -u +%FT%TZ) dumping Neon -> $OUT"
"$PG_DUMP" "$DB_URL" --format=custom --compress=9 --no-owner --no-privileges -f "$OUT"
SIZE=$(du -h "$OUT" | cut -f1)

# Verify: a valid custom-format archive lists its objects without error.
NOBJ=$("$PG_RESTORE" --list "$OUT" | grep -cE '^[0-9]+;' || true)
if [ "${NOBJ:-0}" -lt 1 ]; then
  echo "[backup] ERROR: archive $OUT lists no objects — treating as failed" >&2
  rm -f "$OUT"
  exit 1
fi
echo "[backup] OK: $OUT ($SIZE, $NOBJ objects)"

# Offsite copy: PUT the dump to Object Storage via a Pre-Authenticated Request
# (PAR). The PAR URL is a secret and lives in the env (PFIP_BACKUP_PAR_URL),
# never in the repo. A failed upload warns but does not fail the local backup.
# Read the PAR URL from the env, falling back to the .env file (the systemd
# service doesn't export .env, so we grep it — same pattern as DATABASE_URL).
PAR_URL="${PFIP_BACKUP_PAR_URL:-$(grep -E '^PFIP_BACKUP_PAR_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)}"
PAR_URL="${PAR_URL%\"}"; PAR_URL="${PAR_URL#\"}"
if [ -n "$PAR_URL" ]; then
  obj=$(basename "$OUT")
  code=$(curl -s -o /dev/null -w "%{http_code}" -T "$OUT" "${PAR_URL}${obj}" || echo "000")
  if [ "$code" = "200" ]; then
    echo "[backup] offsite OK: uploaded $obj (HTTP $code)"
  else
    echo "[backup] WARNING: offsite upload of $obj failed (HTTP $code)" >&2
  fi
else
  echo "[backup] offsite: PFIP_BACKUP_PAR_URL unset — skipping upload"
fi

# Rotate: keep the newest $KEEP dumps.
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/pfip-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) || true)
if [ "${#OLD[@]}" -gt 0 ]; then
  printf '%s\n' "${OLD[@]}" | xargs -r rm -f
  echo "[backup] rotated: removed ${#OLD[@]} old dump(s), keeping newest $KEEP"
fi
echo "[backup] current backups:"
ls -1t "$BACKUP_DIR"/pfip-*.dump | head -5
