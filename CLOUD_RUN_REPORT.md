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

- Run: `27583694633` — **✅ success**, ~5 min (pipeline `elapsed_s` 201.8).
- `stages_run`: ingest, features, regime, signals, retention.

| Stage / source        | Rows / result          | Notes |
| --------------------- | ---------------------- | ----- |
| OHLCV — crypto (ccxt) | 63                     | recent bars |
| OHLCV — India (jugaad)| 80                     | recent NSE EOD |
| OHLCV — US (Tiingo)   | 0                      | no key |
| **FX (`fx_rates`)**   | **3**                  | USD/EUR/GBP→INR — **worked here** (1-day window is fast; the backfill timeout was the 1200-day depth) |
| news (all sources)    | 0                      | every source 0 — see findings |
| fundamentals (screener)| 36                    | screener.in, keyless |
| fundamentals (finnhub)| 0                      | no key |
| features              | 0 (symbols=0)          | empty watchlist |
| regime                | 0 (symbols=0)          | empty watchlist |
| signals               | skipped                | `FEATURE_ML_SIGNALS=false` (intended) |
| retention             | 0 pruned               | nothing old yet |

## 4. Per-stage totals on Neon after both runs (from pipeline summaries)

| Table        | Approx rows | Source of count |
| ------------ | ----------- | --------------- |
| `ohlcv`      | ~7,972      | backfill ~7,829 + daily 143 |
| `fx_rates`   | 3           | daily ingest |
| `features`   | 0           | empty watchlist starves compute |
| `regime`     | 0           | empty watchlist starves compute |
| `news`       | 0           | no sources returned rows (see findings) |
| (`fundamentals` | 36       | screener.in — not in the requested set, noted for completeness) |

> Counts are from the workflows' own structured summaries (Neon isn't reachable from
> the sandbox for a direct `SELECT count(*)`). Both runs were green end-to-end.

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
4. **News seeded 0 rows from every source**, even keyless RSS/Google-News/GDELT. The
   news fetchers key off the (empty) watchlist/universe, so there are no symbols to
   pull news for. Same root cause as #1 — seed the watchlist.
5. **Prefect 2.20.25 + anyio 4.x incompatibility (real bug).** The news *embedder*
   flow crashed with `TypeError: Can't instantiate abstract class GatherTaskGroup
   without an implementation for abstract method 'create_task'` (Prefect's
   `GatherTaskGroup` vs the abstract method anyio 4 now requires). It was caught
   gracefully (`embedder unavailable`, `embedded: 0`) and didn't fail the run, but
   with real news data the embedding step would silently produce 0 embeddings.
   **Fix:** pin a compatible anyio for Prefect 2.20 (e.g. `anyio<4`) or move the
   embedder off Prefect's `gather`. Tracked in `PLACEHOLDERS.md` / `OVERNIGHT_LOG.md`.
6. **FX timeout was depth-related, not broken.** The daily (1-day) FX pull succeeded
   (3 rows); only the 1200-day backfill FX pull timed out. Consider chunking the
   backfill FX window or raising its per-source timeout.
7. **Signals correctly skipped** — `FEATURE_ML_SIGNALS` stays off until calibration.

## How to verify counts directly (from a network that can reach Neon)

```sql
SELECT 'ohlcv' t, count(*) FROM ohlcv
UNION ALL SELECT 'features', count(*) FROM features
UNION ALL SELECT 'regime', count(*) FROM regime
UNION ALL SELECT 'news', count(*) FROM news
UNION ALL SELECT 'fx_rates', count(*) FROM fx_rates;
```
