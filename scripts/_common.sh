#!/usr/bin/env bash
# _common.sh — shared helpers for PFIP bash scripts.
# Source from every script:  . "$(dirname "$0")/_common.sh"

# NOTE: this file is sourced — do NOT set -e here (would break the caller).
# The calling script is responsible for `set -euo pipefail`.

# -------------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------------
_common_self_dir() {
  # shellcheck disable=SC2164
  local src="${BASH_SOURCE[0]}"
  cd -- "$(dirname -- "$src")" &> /dev/null && pwd
}

SCRIPTS_DIR="$(_common_self_dir)"
ROOT_DIR="$(cd -- "$SCRIPTS_DIR/.." &> /dev/null && pwd)"
INFRA_DIR="$ROOT_DIR/infra"
ENV_FILE="$ROOT_DIR/.env"
ENV_EXAMPLE="$ROOT_DIR/.env.example"
COMPOSE_FILE="$INFRA_DIR/docker-compose.yml"
BACKUPS_DIR="$ROOT_DIR/backups"

# -------------------------------------------------------------------------
# Colors (only when stdout is a TTY)
# -------------------------------------------------------------------------
if [ -t 1 ]; then
  C_RED='\033[31m'; C_GRN='\033[32m'; C_YEL='\033[33m'
  C_CYN='\033[36m'; C_MAG='\033[35m'; C_RST='\033[0m'
else
  C_RED=''; C_GRN=''; C_YEL=''; C_CYN=''; C_MAG=''; C_RST=''
fi

log_info() { printf "${C_CYN}[INFO]${C_RST} %s\n" "$*"; }
log_ok()   { printf "${C_GRN}[ OK ]${C_RST} %s\n" "$*"; }
log_warn() { printf "${C_YEL}[WARN]${C_RST} %s\n" "$*" >&2; }
log_err()  { printf "${C_RED}[FAIL]${C_RST} %s\n" "$*" >&2; }
log_step() { printf "${C_MAG}==>${C_RST} %s\n" "$*"; }

# -------------------------------------------------------------------------
# Docker helpers
# -------------------------------------------------------------------------
docker_running() {
  docker info --format '{{.ServerVersion}}' > /dev/null 2>&1
}

assert_docker_running() {
  if ! docker_running; then
    log_err "Docker daemon is not running. Start Docker Desktop / dockerd and retry."
    exit 1
  fi
}

compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

container_running() {
  local name="$1"
  local state
  state="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)"
  [ "$state" = "true" ]
}

# -------------------------------------------------------------------------
# .env helpers
# -------------------------------------------------------------------------
assert_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    log_warn ".env not found at $ENV_FILE"
    if [ -f "$ENV_EXAMPLE" ]; then
      log_warn "Copying .env.example -> .env. EDIT SECRETS BEFORE DEPLOYING."
      cp "$ENV_EXAMPLE" "$ENV_FILE"
    else
      log_err ".env.example also missing. Cannot continue."
      exit 1
    fi
  fi
}

# Read a single value from .env. Usage: val="$(env_get POSTGRES_USER)"
env_get() {
  local key="$1"
  local f="${2:-$ENV_FILE}"
  [ -f "$f" ] || return 1
  # POSIX-safe parse: strip comments/blanks, match KEY=, strip surrounding quotes.
  local line
  line="$(grep -E "^${key}=" "$f" | head -n1 | cut -d'=' -f2- || true)"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# -------------------------------------------------------------------------
# HTTP helpers (uses curl; pre-req on Windows: Git Bash or WSL comes with curl)
# -------------------------------------------------------------------------
http_ok() {
  local url="$1"
  local timeout="${2:-5}"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$timeout" "$url" 2>/dev/null || echo 000)"
  [ "$code" -ge 200 ] && [ "$code" -lt 400 ]
}

# -------------------------------------------------------------------------
# Confirm-Destructive — Y/N prompt unless FORCE=1
# -------------------------------------------------------------------------
confirm() {
  local msg="$1"
  if [ "${FORCE:-0}" = "1" ]; then return 0; fi
  printf "%s [y/N] " "$msg"
  local reply
  read -r reply
  [ "$reply" = "y" ] || [ "$reply" = "Y" ]
}
