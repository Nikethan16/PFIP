# PFIP — Personal Financial Intelligence Platform

A solo-built, local-first financial intelligence platform that ingests market data, computes
features, generates calibrated signals, runs a shadow portfolio, answers questions against a
personal knowledge base, and keeps Indian tax compliance honest — all from a single
workstation with optional cloud tunnel. Advisory-only; no auto-execution.

See the full product plan (Sections 1 & 12) for mission, stages, and roadmap.

---

## Links

- Product plan: `../PFIP_v0.5/financial_intelligence_platform_plan.md`
- Progress tracker: `../PFIP_v0.5/tracker.md`
- Placeholders & open decisions: `./PLACEHOLDERS.md`
- Contracts (backend + frontend must implement identically): `./docs/CONTRACTS.md`
- Changelog (what changed, newest first): `./docs/CHANGELOG.md`
- Runbooks: `./docs/runbooks/`
- Onboarding (for future-Suresh): `./docs/ONBOARDING.md`

---

## Prerequisites

Install these once on the workstation before anything else.

| Tool            | Version | Download                                                           |
| --------------- | ------- | ------------------------------------------------------------------ |
| Docker Desktop  | latest  | https://www.docker.com/products/docker-desktop/                    |
| Node.js         | 20 LTS  | https://nodejs.org/                                                |
| pnpm            | latest  | `npm install -g pnpm`                                              |
| Python          | 3.12    | https://www.python.org/downloads/                                  |
| uv              | latest  | `pip install uv`                                                   |
| Git             | latest  | https://git-scm.com/download/win                                   |

Optional but recommended:

- Windows Terminal (Microsoft Store)
- VS Code — https://code.visualstudio.com/

Enable BitLocker on the drive first — see `docs/SECURITY.md`.

---

## Quick start (PowerShell, Windows primary)

```powershell
# 1. Clone (or unzip) into your workspace
cd C:\Users\gaura\OneDrive\Desktop
# git clone <repo-url> PFIP_app
cd PFIP_app

# 2. Copy env template and fill critical secrets
Copy-Item .env.example .env
notepad .env   # fill NEXTAUTH_SECRET, POSTGRES_PASSWORD, PFIP_USER_PASSWORD_HASH, FRED_API_KEY, FINNHUB_API_KEY
#   NEXTAUTH_SECRET and POSTGRES_PASSWORD are now MANDATORY — compose uses ${VAR:?...}
#   and aborts at startup if either is unset (no insecure dev defaults anymore).

# 3. Generate a NextAuth secret
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Max 256 } | ForEach-Object { [byte]$_ }))

# 4. (Frontend deps) After pulling new code, install frontend packages — required after the
#    Next.js bump + new middleware/Zod schemas landed in the 2026-06-04 audit.
cd frontend; pnpm install; cd ..

# 5. Bring the stack up
docker compose -f infra/docker-compose.yml --env-file .env up -d

# 6. Pull local LLM models (one-time, ~4 GB)
docker exec -it pfip-ollama ollama pull mistral:7b-instruct
docker exec -it pfip-ollama ollama pull nomic-embed-text

# 7. Verify
docker compose -f infra/docker-compose.yml ps
```

All host ports bind to `127.0.0.1` (loopback) — the compose file maps them as
`127.0.0.1:PORT:PORT`, so nothing is reachable from the LAN. Open in the browser
(localhost only):

- Frontend dashboard: http://localhost:3000
- Backend OpenAPI UI: http://localhost:8000/docs
- Prefect: http://localhost:4200
- MLflow: http://localhost:5000
- Qdrant: http://localhost:6333/dashboard
- Uptime Kuma: http://localhost:3001

If port 3000 / 8000 / 5432 / 6379 is already taken on your machine, see
`docs/runbooks/docker_compose_port_conflict.md`.

---

## Architecture (ascii)

```
                       +-------------------+
                       |   Frontend (3000) |
                       |   Next.js 14      |
                       +---------+---------+
                                 |
                                 v
+------------------+   +-------------------+   +------------------+
| Prefect (4200)   |-->|  Backend (8000)   |-->| Ollama (11434)   |
| flows + schedule |   |  FastAPI + agent  |   | mistral / nomic  |
+------------------+   +---+----+----+-----+   +------------------+
                           |    |    |
        +------------------+    |    +---------------------+
        v                       v                          v
+-----------------+   +-------------------+       +-------------------+
| TimescaleDB5432 |   |  Redis (6379)     |       |  Qdrant (6333)    |
| OHLCV + ledger  |   |  cache + queues   |       |  KB vectors       |
+-----------------+   +-------------------+       +-------------------+

+------------------+   +-------------------+
| MLflow (5000)    |   | Uptime Kuma 3001  |
| model registry   |   | health monitor    |
+------------------+   +-------------------+

All services live on the `pfip-net` bridge network. Only the host-mapped
ports above are exposed, and they bind to localhost. No service is
reachable from outside the workstation by default.
```

See `docs/ARCHITECTURE.md` for the module-by-module breakdown (M1–M9).

---

## Directory layout

```
PFIP_app/
├── README.md                  <- you are here
├── PLACEHOLDERS.md            <- open decisions & TODO(user) index
├── .env.example               <- copy to .env, fill secrets
├── .gitignore
├── .github/workflows/         <- CI (lint, test, compose-config)
├── backend/                   <- FastAPI app + Prefect flows (Python 3.12)
├── frontend/                  <- Next.js 14 app (TypeScript, pnpm)
├── infra/
│   └── docker-compose.yml     <- single source of truth for local stack
├── schedules/                 <- Prefect deployment specs (cron mapping)
├── scripts/                   <- backup, restore, ingest helpers
└── docs/
    ├── CONTRACTS.md           <- canonical backend/frontend interface
    ├── ARCHITECTURE.md
    ├── ONBOARDING.md          <- resume-after-pause playbook
    ├── SECURITY.md
    ├── BACKUP.md
    ├── SCHEDULED_TASKS.md
    ├── TAX_REFERENCE.md
    ├── GLOSSARY.md
    ├── checklists/            <- pre-trade, post-mortem, stage gates
    └── runbooks/              <- on-call fixes
```

---

## Common commands

All commands assume PowerShell from the repo root (`PFIP_app/`).

| Purpose                    | Command                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------- |
| Bring stack up             | `docker compose -f infra/docker-compose.yml --env-file .env up -d`                       |
| Tear stack down            | `docker compose -f infra/docker-compose.yml down`                                        |
| Nuke volumes (destructive) | `docker compose -f infra/docker-compose.yml down -v`                                     |
| Tail all logs              | `docker compose -f infra/docker-compose.yml logs -f`                                     |
| Tail one service           | `docker compose -f infra/docker-compose.yml logs -f backend`                             |
| List service status        | `docker compose -f infra/docker-compose.yml ps`                                          |
| Shell into backend         | `docker exec -it pfip-backend bash`                                                      |
| Run backend tests          | `docker exec -it pfip-backend uv run pytest`                                             |
| Install frontend deps      | `cd frontend; pnpm install` (run after pulling — Next bump + new middleware/schemas)     |
| Run frontend tests         | `docker exec -it pfip-frontend pnpm test`                                                |
| Alembic migrate            | `docker exec -it pfip-backend uv run alembic upgrade head`                               |
| Ingest BTC (one-shot)      | `docker exec -it pfip-backend uv run python -m pfip.ingest.crypto.btc_daily`             |
| Deep health check          | `curl http://localhost:8000/api/v1/health/deep`                                          |
| Pull LLM models            | `docker exec -it pfip-ollama ollama pull mistral:7b-instruct`                            |
| Backup now                 | `docker exec -it pfip-backend uv run python scripts/backup.py`                           |
| Restore (dry-run first)    | `docker exec -it pfip-backend uv run python scripts/restore.py --dry-run` (add `--confirm` to apply) |
| Backfill FX (USD→INR MTM)  | `docker exec -it pfip-backend uv run python -c "import asyncio; from pfip.ingest.macro.fx_rates import ingest_fx_rates; asyncio.run(ingest_fx_rates(mode='backfill', lookback_days=730))"` |

---

## When you're stuck

1. Check the service you suspect with `docker logs pfip-<service>`.
2. Open `docs/runbooks/` and look for a matching symptom file.
3. If nothing matches, open `docs/runbooks/` and copy the template into a new file while you debug — future-you will thank you.
4. `docs/ONBOARDING.md` has the resume-from-pause playbook.
5. `docs/BACKUP.md` covers any restore scenario.

---

## Placeholders

See `./PLACEHOLDERS.md` for every open decision, missing secret, and inline `TODO(user)` tag.
Do not remove that file until Stage 0 is signed off per `docs/checklists/stage_gate_0.md`.
