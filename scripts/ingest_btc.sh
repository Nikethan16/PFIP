#!/usr/bin/env bash
# ingest_btc.sh — on-demand trigger for the BTC daily Prefect flow.
# Falls back to direct module invocation if the deployment isn't registered yet.
set -euo pipefail
. "$(dirname "$0")/_common.sh"

DEPLOYMENT="${DEPLOYMENT:-ingest-btc-daily/prod}"
DIRECT="${DIRECT:-0}"

for arg in "$@"; do
  case "$arg" in
    --direct) DIRECT=1 ;;
    --deployment=*) DEPLOYMENT="${arg#*=}" ;;
    -h|--help) sed -n '1,15p' "$0"; exit 0 ;;
  esac
done

assert_docker_running
if ! container_running pfip-backend; then
  log_err 'pfip-backend container is not running. Run scripts/up.sh first.'
  exit 1
fi

if [ "$DIRECT" != "1" ]; then
  log_step "Triggering Prefect deployment: $DEPLOYMENT"
  if docker exec -i pfip-backend prefect deployment run "$DEPLOYMENT"; then
    log_ok "Flow run submitted for $DEPLOYMENT"
    exit 0
  fi
  log_warn 'Prefect deployment trigger failed; falling back to direct module run.'
fi

log_step 'Running pfip.ingest.crypto.btc_daily directly'
docker exec -i pfip-backend python -m pfip.ingest.crypto.btc_daily
log_ok 'BTC ingest complete.'
