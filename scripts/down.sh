#!/usr/bin/env bash
# down.sh — graceful shutdown of the PFIP stack.
# Usage: scripts/down.sh [--volumes] [--force]
set -euo pipefail
. "$(dirname "$0")/_common.sh"

VOLUMES=0
for arg in "$@"; do
  case "$arg" in
    --volumes|-v) VOLUMES=1 ;;
    --force|-f)   FORCE=1 ;;
    -h|--help)    sed -n '1,10p' "$0"; exit 0 ;;
  esac
done
export FORCE="${FORCE:-0}"

log_step 'PFIP — shutting down stack'

if ! docker_running; then
  log_warn 'Docker is not running; nothing to do.'
  exit 0
fi

if [ "$VOLUMES" -eq 1 ]; then
  if ! confirm 'Remove all PFIP data volumes? This DELETES databases + models.'; then
    log_info 'Aborted.'
    exit 0
  fi
  compose down -v
else
  compose down
fi

log_ok 'Stack is down.'
