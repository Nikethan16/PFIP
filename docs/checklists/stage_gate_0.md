# Stage Gate 0 — Scaffold / Bring-Up Sign-Off

Plan **Section 12** defines Stage 0 as "repo scaffolded, local stack comes up, health
checks green, first ingest works end-to-end". Every item below must be ticked before
declaring Stage 0 done and starting Stage 1 (market-specific adapters).

---

## 1. Host prerequisites

- [ ] Docker Desktop installed, runs, engine shows "running" green.
- [ ] Node 20 LTS: `node --version` prints `v20.*`.
- [ ] pnpm: `pnpm --version` prints a version.
- [ ] Python 3.12: `py -3.12 --version` prints `Python 3.12.*`.
- [ ] uv: `uv --version` prints a version.
- [ ] Git: `git --version` prints a version.
- [ ] BitLocker is **On** for the drive containing the repo (`manage-bde -status`).

## 2. Environment

- [ ] `.env` exists at repo root (copied from `.env.example`).
- [ ] `NEXTAUTH_SECRET` populated (non-default, base64 32 bytes).
- [ ] `PFIP_USER_PASSWORD_HASH` populated via `scripts/make_password_hash.py`.
- [ ] `PFIP_USER_EMAIL` matches the real operator email.
- [ ] At least one critical data-source key set (`FRED_API_KEY` or `FINNHUB_API_KEY`).
- [ ] `.gitignore` confirms `.env` is ignored (`git check-ignore .env` prints `.env`).

## 3. Stack comes up cleanly on a fresh machine

- [ ] `docker compose -f infra/docker-compose.yml --env-file .env up -d` exits 0.
- [ ] `docker compose ps` shows all 9 services in `running` state:
  - [ ] `pfip-timescaledb` (healthy)
  - [ ] `pfip-redis` (healthy)
  - [ ] `pfip-qdrant`
  - [ ] `pfip-prefect`
  - [ ] `pfip-mlflow`
  - [ ] `pfip-ollama`
  - [ ] `pfip-uptime-kuma`
  - [ ] `pfip-backend`
  - [ ] `pfip-frontend`
- [ ] No CrashLoopBackOff or restart > 1 for any container after 5 minutes.

## 4. Health checks

- [ ] `curl http://localhost:8000/api/v1/health` returns `{"status":"ok", ...}`.
- [ ] `curl http://localhost:8000/api/v1/health/deep` returns all green — TimescaleDB,
      Redis, Qdrant, Ollama all reporting reachable.
- [ ] Uptime Kuma (http://localhost:3001) initial-setup wizard completed; monitors added
      for every service above.

## 5. Frontend usable

- [ ] http://localhost:3000 renders the login screen without console errors.
- [ ] Login with the configured email + password succeeds and redirects to dashboard.
- [ ] Dashboard loads cleanly at 375x812 viewport (iPhone SE / modern phone size).
- [ ] Mobile nav (bottom tabs or hamburger) is usable one-thumb.

## 6. Database & migrations

- [ ] `docker exec -it pfip-backend uv run alembic upgrade head` exits 0.
- [ ] `\dt` in psql shows the core tables: `ohlcv`, `fundamentals`, `holdings`,
      `portfolio_tx`, `news_items`, `signals`, `journal_entries`, `users`.
- [ ] `ohlcv` is a hypertable:
      `SELECT * FROM timescaledb_information.hypertables WHERE hypertable_name='ohlcv';`
      returns 1 row.

## 7. First ingest end-to-end

- [ ] BTC daily flow runs:
      `docker exec -it pfip-backend uv run python -m pfip.ingest.crypto.btc_daily`.
- [ ] Row count in `ohlcv` WHERE symbol='BTC-USD' is > 0 and monotonically increasing
      across days.
- [ ] `GET /api/v1/assets/BTC-USD/candles?timeframe=1d` returns a non-empty array.
- [ ] Frontend home chart for BTC renders the candles.

## 8. LLM wired

- [ ] `docker exec -it pfip-ollama ollama list` shows `mistral:7b-instruct` and
      `nomic-embed-text`.
- [ ] `curl http://localhost:11434/api/tags` returns the same set.
- [ ] Agent stub endpoint (`POST /api/v1/agent/chat` with a trivial prompt) streams back
      at least one token event.

## 9. Backups

- [ ] `scripts/backup.py` (or `.ps1`) runs end-to-end without error.
- [ ] Output directory for the date has non-zero-byte artifacts for `timescaledb.dump`,
      `qdrant/` snapshot, `mlflow/`.
- [ ] Cloud remote sync succeeds (`rclone ls pfip-cloud:` lists today's folder).
- [ ] Restore drill (section 5 of `docs/BACKUP.md`) executed once and row counts match.

## 10. Security

- [ ] Windows Defender firewall profile is Private, not Public.
- [ ] No router port-forward to this machine.
- [ ] `git ls-files | Select-String '\.env$|\.session$'` returns nothing.
- [ ] `docs/SECURITY.md` section 8 rotation date scheduled in calendar.

## 11. Observability

- [ ] Uptime Kuma monitors all 9 services + nightly backup job.
- [ ] Sentry DSN (if provided) receives a deliberate test error from the backend.
- [ ] LangSmith (if key provided) shows a trace from the agent smoke test.

## 12. Docs & placeholders

- [ ] `PLACEHOLDERS.md` section 1 — all four pre-Stage-0 decisions have an explicit answer
      (resolved or "deferred: <reason>").
- [ ] `docs/ONBOARDING.md` section 1 updated to "Stage 0 — brought up <date>".
- [ ] `docs/ONBOARDING.md` section 7 contacts block has at least the CA and one broker
      filled in, or explicit `TODO(user)` with an owner date.

---

**Sign-off:**

```
Stage 0 signed off by: ______________________   Date: ____________
Next milestone:        Stage 1 — <chosen starting market>
```
