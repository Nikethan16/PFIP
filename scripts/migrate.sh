#!/usr/bin/env bash
# migrate.sh — run Alembic migrations in the backend container.
# Usage:
#   scripts/migrate.sh                       # upgrade head
#   scripts/migrate.sh <revision>            # upgrade to revision
#   scripts/migrate.sh --autogen "message"   # create new autogen revision
set -euo pipefail
. "$(dirname "$0")/_common.sh"

assert_docker_running
if ! container_running pfip-backend; then
  log_err 'pfip-backend container is not running. Run scripts/up.sh first.'
  exit 1
fi

if [ "${1:-}" = "--autogen" ]; then
  shift
  msg="${1:-}"
  if [ -z "$msg" ]; then
    log_err '--autogen requires a message'
    exit 2
  fi
  log_step "alembic revision --autogenerate -m \"$msg\""
  docker exec -i pfip-backend alembic revision --autogenerate -m "$msg"
else
  rev="${1:-head}"
  log_step "alembic upgrade $rev"
  docker exec -i pfip-backend alembic upgrade "$rev"
fi

log_ok 'Migration complete.'
