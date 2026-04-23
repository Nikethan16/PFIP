#!/usr/bin/env bash
# check_env.sh — validate .env for a given PFIP stage.
# Usage: scripts/check_env.sh [stage]  (default 0)
set -euo pipefail
. "$(dirname "$0")/_common.sh"

STAGE="${1:-0}"
if ! [[ "$STAGE" =~ ^[0-7]$ ]]; then
  log_err "Stage must be 0..7 (got $STAGE)"
  exit 2
fi

# Required-per-stage (cumulative).
stage_keys() {
  case "$1" in
    0) echo "POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB NEXTAUTH_SECRET PFIP_USER_EMAIL" ;;
    1) echo "LLM_DEFAULT_MODEL LLM_EMBED_MODEL HOME_CURRENCY" ;;
    2) echo "FRED_API_KEY FINNHUB_API_KEY" ;;
    3) echo "NEWSAPI_API_KEY" ;;
    4) echo "" ;;
    5) echo "PFIP_USER_PASSWORD_HASH TAX_YEAR_START TAX_YEAR_END" ;;
    6) echo "TELEGRAM_BOT_TOKEN TELEGRAM_BOT_CHAT_ID" ;;
    7) echo "" ;;
  esac
}

PLACEHOLDERS=( 'change_me_to_random_32_bytes_base64' 'pfip_dev_change_me' 'REPLACE_ME' )

assert_env_file

NEED=()
for s in $(seq 0 "$STAGE"); do
  for k in $(stage_keys "$s"); do NEED+=("$k"); done
done

MISSING=(); EMPTY=(); PLACEHOLDER=()
for k in "${NEED[@]}"; do
  if ! grep -qE "^${k}=" "$ENV_FILE"; then MISSING+=("$k"); continue; fi
  v="$(env_get "$k")"
  if [ -z "$v" ]; then EMPTY+=("$k"); continue; fi
  for p in "${PLACEHOLDERS[@]}"; do
    case "$v" in *"$p"*) PLACEHOLDER+=("$k"); break ;; esac
  done
done

log_step "Environment check for Stage $STAGE"
log_info "Required keys: ${#NEED[@]}"

if [ "${#MISSING[@]}" -eq 0 ] && [ "${#EMPTY[@]}" -eq 0 ] && [ "${#PLACEHOLDER[@]}" -eq 0 ]; then
  log_ok 'All required keys present and non-placeholder.'
  exit 0
fi

for k in "${MISSING[@]}";     do log_err  "MISSING:     $k"; done
for k in "${EMPTY[@]}";       do log_err  "EMPTY:       $k"; done
for k in "${PLACEHOLDER[@]}"; do log_warn "PLACEHOLDER: $k  (still has default/example value)"; done

FAIL=$(( ${#MISSING[@]} + ${#EMPTY[@]} ))
if [ "$STAGE" -ge 1 ]; then FAIL=$(( FAIL + ${#PLACEHOLDER[@]} )); fi
[ "$FAIL" -eq 0 ] || exit 1
