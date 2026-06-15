# PFIP Cloud Pipeline Run Report

**Date:** 2026-06-15 (UTC)
**Environment:** GitHub Actions runners (Ubuntu, Python 3.12) → Neon Postgres.
**Why Actions, not local:** outbound to Neon:5432 is blocked from the dev sandbox
(TCP connect times out), so migrations and ingest are driven entirely through the
workflows, which run inside GitHub's network and reach Neon. Direct Neon row-count
queries from the sandbox are therefore not possible; the counts below are taken from
the pipeline's own structured summaries in the job logs.

`FEATURE_ML_SIGNALS` was deliberately **left off** for this run.

---

## 1. Migrations — `alembic upgrade head` on Neon

**Status: ✅ success.** Both the Backfill and Daily-ingest workflows run
`alembic upgrade head` as a step; it completed in ~5s against the fresh Neon DB,
creating the full schema (migrations `0001`–`0009`).

## 2. Backfill history (workflow_dispatch, days=1200, skip_compute=false)

- Run: `27582259789` — **✅ success**, ~29 min (`elapsed_s` 1735.8).
- Structured `backfill summary` from the job log:

| Stage / source        | Rows / result          | Notes |
| --------------------- | ---------------------- | ----- |
| OHLCV — BTC/USD       | 1921                   | crypto via ccxt (keyless) |
| OHLCV — ETH/USD       | 1200                   | crypto |
| OHLCV — SOL/USD       | 1405                   | crypto |
| OHLCV — India (jugaad)| 3303                   | NSE EOD, keyless |
| OHLCV — US (Tiingo)   | 0                      | **no `TIINGO_API_KEY`** → source no-ops |
| FX (`fx_rates`)       | 0                      | **`fx_frankfurter` timed out >180s** |
| features              | 0 (symbols=0)          | see finding below |
| regime                | 0 (symbols=0)          | see finding below |
| signals               | skipped                | `FEATURE_ML_SIGNALS=false` (intended) |

**OHLCV total seeded on Neon: ~7,829 bars** across 4 symbols (3 crypto + NIFTY names).

## 3. Daily ingest (workflow_dispatch, blank stages = all)

- Run: `27583694633` — _see "Daily ingest result" section appended below._

---

## Findings & recommendations

1. **Features/regime computed 0 rows despite ~7.8k OHLCV bars landing.** Both compute
   stages iterate the **`watchlist` table, which is empty** on the fresh Neon DB — the
   backfill seeds OHLCV for a hardcoded universe but never populates `watchlist`, so
   the feature/regime runners have no symbols to iterate. **Fix:** seed `watchlist`
   (the tracked NIFTY-50 + US + crypto universe) as part of backfill, or have the
   compute stages fall back to "distinct symbols present in `ohlcv`" when the watchlist
   is empty.
2. **FX did not seed (`fx_frankfurter` timeout >180s).** USD/INR is needed for
   mark-to-market of US holdings and Schedule-FA. **Fix:** add a faster/secondary FX
   source (e.g. FRED `DEXINUS` with `FRED_API_KEY`, or exchangerate.host) and/or raise
   the per-source timeout; the marking layer already abstains safely without it.
3. **US equities not seeded** (no `TIINGO_API_KEY`). Expected — every data source
   no-ops without its key. Add the key to repo secrets to seed US OHLCV.
4. **Signals correctly skipped** — `FEATURE_ML_SIGNALS` stays off until calibration.

## How to verify counts directly (from a network that can reach Neon)

```sql
SELECT 'ohlcv' t, count(*) FROM ohlcv
UNION ALL SELECT 'features', count(*) FROM features
UNION ALL SELECT 'regime', count(*) FROM regime
UNION ALL SELECT 'news', count(*) FROM news
UNION ALL SELECT 'fx_rates', count(*) FROM fx_rates;
```
