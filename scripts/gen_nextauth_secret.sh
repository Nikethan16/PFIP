#!/usr/bin/env bash
# gen_nextauth_secret.sh — generate a 32-byte base64 secret.
# Usage: scripts/gen_nextauth_secret.sh [bytes]
set -euo pipefail

BYTES="${1:-32}"
QUIET="${QUIET:-0}"

if command -v openssl >/dev/null 2>&1; then
  SECRET="$(openssl rand -base64 "$BYTES" | tr -d '\n')"
elif [ -r /dev/urandom ]; then
  SECRET="$(head -c "$BYTES" /dev/urandom | base64 | tr -d '\n')"
else
  echo "ERROR: neither openssl nor /dev/urandom available" >&2
  exit 2
fi

if [ "$QUIET" = "1" ]; then
  printf '%s\n' "$SECRET"
else
  printf '\nNEXTAUTH_SECRET=%s\n\n' "$SECRET"
  echo 'Paste the line above into your .env file.' >&2
fi
