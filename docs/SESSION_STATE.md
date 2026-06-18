# PFIP — Session State / Handoff

> **Read this first if you're a new chat picking up PFIP.** It captures the live
> state as of the last working session so you can continue without re-deriving
> context. Pairs with `PROJECT_TRACKER.md` (big board) and `PROJECT_PLAN.md`
> (phases 0–10). When this doc and the tracker disagree, **this doc is newer.**

**Last updated:** 2026-06-16
**Active feature branch:** `claude/amazing-noether-va818n`
**Branching rule:** code → feature branch → CI → merge to `main`; docs → direct to `main`.

---

## 1. What was done this session

### Phase 0 — data hardening (DONE, merged to main `a541da0` / `fd91786`)
- **FX timeout fix**: `fx_rates.py` now fetches base currencies concurrently via
  `asyncio.gather`; backfill timeout bumped 180s → 600s. (Was timing out >180s in CI.)
- **MLflow cloud persistence**: artifact dirs default to `/tmp/mlflow/artifacts`;
  workflows set `MLFLOW_TRACKING_URI=file:/tmp/mlruns`; added `setuptools>=69.0`
  (Python 3.12 dropped `pkg_resources`, which MLflow needs).
- **BNB/XRP/India-MF backfill**: added BNB/USD + XRP/USD symbol rewrites (ccxt),
  added India MF (AMFI NAV) block to `backfill_history.py`.
- **Backfill run #3 completed successfully** after these fixes.

### Phase 1 — scoring harness (DONE, merged to main `50ae534` / `fd91786`)
- `pfip/vol/garch.py` — GARCH(1,1) vol baseline + EWMA fallback + `evaluate_vol_forecast`.
- `pfip/regime/markov_switching.py` — Hamilton regime model + rule-based fallback.
- `pfip/core/schemas.py` — pandera validators (`validate_ohlcv` hard-fail,
  `validate_features` soft-warn, `validate_regime` hard-fail).
- `pfip/backtest/scorer.py` — 5-gate KEEP/REJECT acceptance gate.
- Tests: `test_garch_baseline.py`, `test_markov_switching.py`, `test_schemas.py`.
- NOTE: the walk-forward engine already existed in `pfip/backtest/vectorbt_engine.py`
  (embargo, CPCV, Monte Carlo, lookahead test) — Phase 1 only added the missing baselines + gate.

### Infra consolidation — ONE setup (commit `613d56e`)
The big simplification: **one database (Neon), one way to run.**
- `infra/docker-compose.yml`: removed `timescaledb`, `prefect`, `prefect-worker`.
  Backend now reads `DATABASE_URL` straight from `.env` (the Neon URL — same one CI uses).
  Remaining services: redis, qdrant, mlflow, ollama, uptime-kuma, backend, frontend.
- `.env.example`: dropped `POSTGRES_*` / `TIMESCALEDB_PORT` / `PREFECT_PORT`;
  replaced with a single `DATABASE_URL` Neon template.

---

## 2. How to run (the one setup)

```bash
git pull origin main
cp .env.example .env        # then paste your Neon DATABASE_URL + secrets
docker compose -f infra/docker-compose.yml --env-file .env up -d
```
- **Data ingest** runs in the cloud: GitHub Actions cron (`daily-ingest.yml`) → Neon.
  Manual backfill: run the `backfill.yml` workflow (workflow_dispatch).
- **Run the pipeline locally on demand** (optional):
  `docker exec pfip-backend python -m scripts.run_daily_pipeline`
- API keys (Tiingo etc.) live in **GitHub repo → Settings → Secrets → Actions**, not in code.

---

## 3. Live data state (from backfill run #3)

The `PROJECT_TRACKER.md` "live system status" table (section 1) predates the
Phase 0 fixes — treat it as STALE. After run #3, FX / BNB / XRP / India-MF
should now be flowing. **Verify against Neon** before trusting either doc:
query row counts per symbol rather than reading the table.

---

## 4. What's pending (next work)

| Item | Phase | Notes |
|---|---|---|
| Confirm run #3 coverage in Neon | — | Verify FX/BNB/XRP/MF actually landed; refresh tracker section 1 |
| Regime upgrade: `ruptures` change-point alongside HMM + MS | 2 | Freeze a 3-state def (bull/bear/sideways) |
| Historical extras backfill | P1 gap #5 | Fundamentals/macro only stamped on latest bar; supervised ML needs them on historical bars |
| Precommitment Sharpe-floor gate | P2 gap #6 | Currently a no-op |

---

## 5. Git state at handoff

- `main` has: Phase 0 + Phase 1 (merged via `fd91786`).
- The infra consolidation (`613d56e`) is being merged to `main` this session.
- Working tree clean; nothing uncommitted.
