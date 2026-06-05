# PFIP ingest layer — change log

Generated 2026-05-29 as part of the "data ingest expansion" pass.

## Summary

- **Pre-existing scaffold:** 46 adapter modules already in place, most fully
  implemented (BTC/ETH/SOL hourly, US/India EOD, FX, macro, news RSS, social,
  self-custody, fundamentals). Total ~4,800 LOC of adapter code before this pass.
- **Added in this pass:** 15 new adapter modules + 7 new Prefect flows + 1
  new schedules catalogue + 1 new Alembic migration + 1 ingest test file.
- **Status legend:** WORKING (validated end-to-end at least once) /
  SCAFFOLDED (code complete, awaiting first run or external creds) /
  BLOCKED (waiting on user input or third-party access).

## New / extended files this pass

### Migrations

| File | What |
|------|------|
| `alembic/versions/0006_ingest_additions.py` | Adds `source_health`, `mf_nav`, `fx_rates`, `macro_series` tables. Down-revision `0005`. |

### Shared helpers

| File | What |
|------|------|
| `pfip/ingest/_common/source_health.py` | `record_run()` + `track()` async context manager — every flow records into `source_health`. |
| `pfip/ingest/_common/__init__.py` | Re-exports `record_run`, `track`. |

### Crypto adapters

| File | Status | Notes |
|------|--------|-------|
| `crypto/ccxt_multi_ohlcv.py` | SCAFFOLDED | Thin alias re-exporting `ccxt_multi`. Spec-mandated name. |
| `crypto/coingecko.py` | SCAFFOLDED | New. Uses `COINGECKO_API_KEY` (set). Pulls top-N market caps + `/global` dominance. |
| `crypto/coinmetrics_community.py` | SCAFFOLDED | New. Free community API, no key. ~10 daily metrics for BTC+ETH. |
| `crypto/mempool_space.py` | SCAFFOLDED | New. Network-level BTC fees / hashrate / mempool / tip height. |
| `crypto/glassnode_free.py` | SCAFFOLDED | Alias of `glassnode` (no-op when key missing — `GLASSNODE_API_KEY` is empty). |

### Commodities

| File | Status | Notes |
|------|--------|-------|
| `commodities/lbma_fix.py` | SCAFFOLDED | Alias of `lbma_gold`. |
| `commodities/nasdaq_data_link.py` | SCAFFOLDED | New. Free datasets (LBMA/GOLD, LBMA/SILVER, MOSL/IN10Y, CHRIS/CME_GC1). Requires `NASDAQ_DATA_LINK_API_KEY`. |

### Macro

| File | Status | Notes |
|------|--------|-------|
| `macro/mospi.py` | SCAFFOLDED | New. MOSPI press-release RSS; best-effort scrape. Will often fail (MOSPI is flaky) — DBnomics mirror covers the same data. |

### News

| File | Status | Notes |
|------|--------|-------|
| `news/sec_8k_rss.py` | SCAFFOLDED | New. SEC's atom feed for all 8-K filings; uses descriptive UA. |
| `news/rss_aggregator.py` | SCAFFOLDED | New. Convenience over `rss_fetcher` adding per-watchlist Yahoo per-ticker RSS. |
| `news/_pipeline.py` | SCAFFOLDED | New. Post-ingest pipeline: dedupe (normalized URL), entity-link (watchlist regex), classify (FinBERT/CryptoBERT via sentiment service), embed (Qdrant via `kb/news_embed`). |

### Indian equities

| File | Status | Notes |
|------|--------|-------|
| `indian_equities/nse_corporate_announcements.py` | SCAFFOLDED | New. RSS-first, JSON fallback. NSE anti-bot may need a session cookie warm-up. |

### US equities

| File | Status | Notes |
|------|--------|-------|
| `us_equities/finnhub_calendar.py` | SCAFFOLDED | Alias of `economic_calendar/finnhub_calendar`. Naming required by FEATURES.md M1. |

### Self-custody

| File | Status | Notes |
|------|--------|-------|
| `self_custody/etherscan_eth.py` | SCAFFOLDED | Alias of `etherscan`. |

### Academic

| File | Status | Notes |
|------|--------|-------|
| `academic/arxiv_qfin.py` | EXTENDED | Now pulls 6 sub-feeds (qfin / PR / ST / RM / TR / CP), filters by watchlist keywords + default vocab. |

### Prefect flows

| File | Status | Cadence |
|------|--------|---------|
| `prefect/flows/ingest_crypto_hourly.py` | SCAFFOLDED | Every hour at :05 UTC. OHLCV every run; on-chain metrics once per day (configurable). |
| `prefect/flows/ingest_us_eod.py` | SCAFFOLDED | 22:30 IST weekdays = 17:00 UTC. yfinance/Stooq/Tiingo/EDGAR/Finnhub. Reads watchlist. |
| `prefect/flows/ingest_india_eod.py` | SCAFFOLDED | 16:30 IST weekdays = 11:00 UTC. Jugaad + bhavcopies + FII-DII + F&O + PIT + corp announcements. |
| `prefect/flows/ingest_mf_daily.py` | SCAFFOLDED | 22:00 IST = 16:30 UTC. AMFI only. |
| `prefect/flows/ingest_self_custody_6h.py` | SCAFFOLDED | 00:30/06:30/12:30/18:30 UTC. Reads `self_custody_addresses` (migration 0002). Env-var fallback (`BTC_ADDRESSES`, `ETH_ADDRESSES`, `SOL_ADDRESSES`). |
| `prefect/flows/ingest_fundamentals_weekly.py` | SCAFFOLDED | Sat 04:00 IST = Fri 22:30 UTC. SEC EDGAR + Screener + Finnhub + NDL. Watchlist-aware. |
| `prefect/flows/ingest_arxiv_weekly.py` | SCAFFOLDED | Sat 09:00 IST = Sat 03:30 UTC. |

### Schedules catalogue

| File | What |
|------|------|
| `backend/schedules/__init__.py` | Package marker. |
| `backend/schedules/prefect_deployments.py` | 20 deployment specs. Every cadence in WHY_AND_WHAT.md §0b accounted for. `plan`/`apply`/`pause`/`resume` subcommands. |

### Tests

| File | What |
|------|------|
| `backend/tests/test_ingest_adapters.py` | 11 unit tests covering AMFI parser, Frankfurter, CoinGecko, mempool.space, NDL (with + without key), SEC 8-K Atom, news pipeline helpers, source_health context manager, arxiv keyword filter. All pass. |

## What works end-to-end (verified in this pass)

- **All new modules import cleanly** (no syntax errors, no circular imports).
- **`schedules.prefect_deployments plan`** lists all 20 deployments correctly.
- **All 11 ingest unit tests pass** with mocked httpx.
- **Existing test suite (`test_health` etc.) still passes.**

## What is coded but unverified against live APIs

Sandbox here blocks outbound HTTP, so the following were not exercised against
real endpoints but compile + import cleanly:

- All new crypto adapters (coingecko, coinmetrics, mempool_space).
- All new commodity adapters (nasdaq_data_link, lbma_fix).
- All new news adapters (sec_8k_rss, rss_aggregator, _pipeline).
- MOSPI scrape.
- NSE corporate announcements (high-risk: NSE anti-bot may need additional
  cookie / referrer dance — adapter does a best-effort home page warm-up).
- All new Prefect flows (need a running Prefect server to register; spec'd
  through `schedules/prefect_deployments.py plan`).

User should run, on their Docker host:

```bash
docker exec pfip-backend python -m schedules.prefect_deployments plan
docker exec pfip-backend python -m schedules.prefect_deployments apply --stage 4
# Smoke-test individual flows:
docker exec pfip-backend python -m pfip.prefect.flows.ingest_crypto_hourly
docker exec pfip-backend python -m pfip.prefect.flows.ingest_mf_daily
docker exec pfip-backend python -m pfip.prefect.flows.ingest_us_eod
```

## What needs user input

| Item | Why |
|------|-----|
| `self_custody_addresses` rows | Self-custody flow no-ops until at least one row exists. User can either insert via the API once it's exposed or set `BTC_ADDRESSES`, `ETH_ADDRESSES`, `SOL_ADDRESSES` env vars (comma-separated). |
| `GLASSNODE_API_KEY` | Empty in `.env`. Glassnode free tier requires registration; until set, `crypto/glassnode.py` no-ops gracefully. |
| `NASDAQ_DATA_LINK_API_KEY` | Empty in `.env` template; user mentioned this is set — adapter will activate automatically. |
| `COINGLASS_API_KEY` | Empty — `crypto/coinglass.py` no-ops until set. |
| `CRYPTOPANIC_API_KEY` | Optional — `crypto/cryptopanic.py` falls back to public endpoint without it. |
| Solscan + Telegram + Reddit | Per user direction, those adapters' scaffolds remain but their flow tasks log + no-op gracefully when creds are missing. |
| Apply migration `0006_ingest_additions` | `cd /backend && alembic upgrade head` once Docker is back up. |

## Critical correctness rules — compliance

- **PIT discipline**: every fundamentals row uses `as_of_date = today` (when
  data was first available to us) and `report_date = obs_date` (period the
  data covers). Same in pre-existing modules — pattern preserved.
- **Survivorship awareness**: yfinance/stooq adapters don't filter out
  delisted tickers; they pass through whatever the upstream returns. (Tagging
  with `is_active` lives on the watchlist row, not the OHLCV row — design
  unchanged from pre-existing scaffold.)
- **Polite rate limiting**: every new adapter inherits `retry_http` from
  `_common.http` (3-attempt exp backoff). NDL and Etherscan have explicit
  per-call delays. NSE corp-announcements does a home-page warm-up to acquire
  a session cookie.
- **Idempotency**: all DB writes go through `upsert_*` helpers in
  `_common/upsert.py` which use `ON CONFLICT DO NOTHING` against composite PKs.
  Re-runs are safe.
- **Graceful failure**: each adapter checks for its API key at the top of its
  fetch function, logs a warning, and returns `[]` rather than raising when
  the key is missing. Network exceptions inside `retry_http` are logged then
  re-raised; the surrounding flow task records the error in `source_health`
  and the flow continues with `return_exceptions=True` in `asyncio.gather`.
