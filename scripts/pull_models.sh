#!/usr/bin/env bash
# pull_models.sh — pull Ollama models (idempotent).
set -euo pipefail
. "$(dirname "$0")/_common.sh"

assert_docker_running

if ! container_running pfip-ollama; then
  log_err 'pfip-ollama container is not running. Run scripts/up.sh first.'
  exit 1
fi

# Defaults from .env fallback to plan defaults.
DEF="$(env_get LLM_DEFAULT_MODEL)"; DEF="${DEF:-mistral:7b-instruct}"
EMB="$(env_get LLM_EMBED_MODEL)"  ; EMB="${EMB:-nomic-embed-text}"

if [ "$#" -gt 0 ]; then
  MODELS=("$@")
else
  MODELS=("$DEF" "$EMB")
fi

log_step "Pulling Ollama models: ${MODELS[*]}"

# Installed set (skip header line).
INSTALLED="$(docker exec pfip-ollama ollama list 2>/dev/null | awk 'NR>1 {print $1}' || true)"

FAILED=0
for m in "${MODELS[@]}"; do
  if echo "$INSTALLED" | grep -qx "$m"; then
    log_ok "already present: $m"
    continue
  fi
  log_info "pulling $m ..."
  if docker exec pfip-ollama ollama pull "$m"; then
    log_ok "pulled: $m"
  else
    log_err "pull failed: $m"
    FAILED=$((FAILED+1))
  fi
done

[ "$FAILED" -eq 0 ] || exit 1
log_ok 'All models ready.'
