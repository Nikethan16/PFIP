# Production / Ops Status

_Living doc. Last updated 2026-06-23. Records the production-readiness posture and the operating
decisions taken._

## Decisions (2026-06-23)

| Decision | Choice | Implication |
| --- | --- | --- |
| **Execution stance** | **Advisory-only** | Platform never places orders. No broker keys, no order routing. Matches the safety constraints baked into the codebase. **Do not add execution without an explicit future decision.** |
| **VPS (Hetzner)** | **Decide later** | Qdrant (KB/RAG), Ollama (local LLM), Redis, and a 24/7 hosted web app stay **parked**. Stack remains Neon + GitHub Actions (serverless). |
| **Stage-1 market focus** | **India equities + crypto, co-equal** | Feature/regime work targets both universes. Both now have ML-eligible history (see data audit). |
| **Knowledge base** | Research/curate now, ingest later | See [KB_SOURCES.md](KB_SOURCES.md). Ingestion blocked on Qdrant (→ VPS). |

## Auth / env

- `NEXTAUTH_SECRET`: **set** (non-default) in `.env`.
- `APP_ENV`: the cloud ingest workflows already run with `APP_ENV=prod` + `PFIP_PIPELINE_MODE=true`
  (headless, enforces real DB creds, skips web-auth). There is **no standing web deployment** yet
  (VPS deferred), so there's no long-running service on which to set `APP_ENV=prod` for the API.
  When a deployment target exists, set `APP_ENV=prod` and confirm the auth secrets are enforced.
- `FEATURE_ML_SIGNALS`: corrected to **`false`** (was `true` locally) — honours the data-readiness
  gate. Keep OFF until the gate criteria in [ML_SIGNAL_RESEARCH.md](ML_SIGNAL_RESEARCH.md) are met.

## Backup / disaster recovery — **gap flagged**

- **`scripts/backup.py` and `scripts/restore.py` are obsolete for the managed-Neon architecture.**
  They shell out to `docker exec pfip-timescaledb` / the Qdrant container, which no longer exist —
  the DB moved to Neon and Qdrant is unprovisioned.
- **Current DB durability:** Neon provides **automatic continuous backups + point-in-time restore**
  on its platform (restore via the Neon console / branch from a past timestamp). This covers the
  database today without a custom pipeline.
- **Recommended hardening (when a deployment/storage target exists):**
  1. Add a `pg_dump`-based logical export against `DATABASE_URL` (Neon) on a schedule, pushed to
     object storage — requires Postgres client tools (not currently installed locally) and a bucket.
  2. **Restore drill via a Neon branch:** branch prod (instant copy-on-write), restore/validate
     against the branch — never against prod. This is the Neon-native, zero-risk drill.
- **Follow-up:** rewrite `backup.py`/`restore.py` for Neon (or retire them in favour of Neon PITR +
  a `pg_dump` cron). Tracked separately.

## Connectivity note (dev machine)

Local runs against Neon hit **intermittent DNS failures** (`getaddrinfo`, WinError 11001) from this
LAN's router resolver. Workaround in use for local data ops: resolve the Neon host once and pin the
IP via libpq `hostaddr` while keeping `host` for SNI/TLS. The cloud (GitHub Actions) path is
unaffected. See [VALIDATION_REPORT_2026-06-23.md](VALIDATION_REPORT_2026-06-23.md) §5.

## Live deployment (2026-06-26)

PFIP is hosted on the Oracle ARM VM as the 3rd app (systemd + venv, not Docker), alongside
Agent_System and OPPs_Finder. Public URL (Tailscale Funnel, HTTPS): **https://apps.tail1d9a60.ts.net:8443**
(login-gated). DB on Neon, Redis shared (logical DB 1). Services: `pfip-api` (:8000), `pfip-web` (:3000),
`pfip-pipeline.timer` (daily 02:30 UTC). **CI/CD:** push to `main` → CI → on success the VM's self-hosted
runner auto-redeploys via `.github/workflows/deploy-oracle.yml`. See `docs/DEPLOY_ORACLE.md`.
