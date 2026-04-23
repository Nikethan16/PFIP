# PFIP — `scripts/` index

Operational helpers for running, maintaining, and backing up the PFIP stack.
Every script is intended to be run from the repo root (paths resolve relative
to the script's own location, not your cwd).

## Platform matrix

| Script                       | PowerShell | Bash/WSL | Purpose                                                       | When to use                                             |
|------------------------------|:----------:|:--------:|---------------------------------------------------------------|----------------------------------------------------------|
| `up`                         | `.ps1`     | `.sh`    | Pre-flight checks + `docker compose up -d` + URL summary       | Daily first thing. Boots the full stack.                 |
| `down`                       | `.ps1`     | `.sh`    | Graceful shutdown. `-Volumes` / `--volumes` for destructive    | End of session; `-Volumes` to wipe data.                 |
| `health`                     | `.ps1`     | `.sh`    | Hits every service health endpoint; PASS/FAIL report           | Post-`up` verification, and before starting work.        |
| `pull_models`                | `.ps1`     | `.sh`    | Idempotent Ollama model pull (mistral, nomic-embed-text)       | First boot; after changing `LLM_*_MODEL` in `.env`.      |
| `migrate`                    | `.ps1`     | `.sh`    | `alembic upgrade head` (or `--autogen` for new revisions)      | After pulling code that changes DB models.               |
| `ingest_btc`                 | `.ps1`     | `.sh`    | Trigger BTC Prefect flow; falls back to direct module run      | Manual ingest run / smoke test.                          |
| `backup`                     | `.ps1`     | `.sh`    | pg_dump + Qdrant snapshots + MLflow mirror + retention         | Nightly (scheduled via Windows Task Scheduler).          |
| `restore_drill`              | `.ps1`     | `.sh`    | Quarterly drill: isolated test stack + restore + row counts    | Quarterly (scheduled). Also run manually after disaster. |
| `gen_nextauth_secret`        | `.ps1`     | `.sh`    | 32-byte base64 random secret                                   | One-off during Stage 0 onboarding.                       |
| `make_password_hash.py`      |     —      | Python   | bcrypt hash of a password for `PFIP_USER_PASSWORD_HASH`        | One-off during Stage 0 onboarding.                       |
| `check_env`                  | `.ps1`     | `.sh`    | Validates `.env` has required keys for the current stage       | Before every `up` when advancing stages.                 |
| `port_check`                 | `.ps1`     |  (n/a)   | Windows — detects PFIP default ports already bound by others   | Troubleshooting `up` failures on Windows.                |
| `run.js`                     |  (n/a)     |  (n/a)   | Dispatcher invoked by `pnpm run <script>` in root `package.json` | Internal — not called directly.                        |
| `_common.ps1` / `_common.sh` |  (n/a)     |  (n/a)   | Shared helpers; dot-sourced by every sibling script            | Internal — never run standalone.                         |

## Conventions

- PowerShell scripts target **PowerShell 5.1 and 7+**. No external modules required.
- Bash scripts start with `#!/usr/bin/env bash` and `set -euo pipefail`.
- Destructive operations prompt `y/N` by default; pass `-Force` (PS) or `FORCE=1` (bash) to skip.
- Every script prints clear `[PASS]` / `[FAIL]` / `[WARN]` lines and exits non-zero on failure.
- No secrets are ever logged. Only the key NAME is logged when reporting missing env vars.
- All scripts are **idempotent** where possible: re-running is safe and will skip work already done.

## Canonical Windows workflow (minimum)

```powershell
# First time
.\scripts\gen_nextauth_secret.ps1      # copy output into .env
py scripts\make_password_hash.py       # copy output into .env
.\scripts\check_env.ps1 -Stage 0
.\scripts\port_check.ps1
.\scripts\up.ps1
.\scripts\pull_models.ps1
.\scripts\health.ps1

# Day-to-day
.\scripts\up.ps1
.\scripts\health.ps1
.\scripts\logs-backend.ps1    # (use docker compose logs)
.\scripts\down.ps1

# Backup (scheduled — see schedules/)
.\scripts\backup.ps1
```

## Canonical bash/WSL workflow

```bash
scripts/gen_nextauth_secret.sh
python3 scripts/make_password_hash.py
scripts/check_env.sh 0
scripts/up.sh
scripts/pull_models.sh
scripts/health.sh
```

## Related

- Scheduled tasks (cron / Prefect / Windows Task Scheduler): see `../schedules/`.
- One-shot / npm entrypoints: see root `package.json` (e.g., `pnpm run up`).
- GNU Make entrypoints: see root `Makefile` (e.g., `make up`).
