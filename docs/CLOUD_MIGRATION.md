# Cloud migration runbook — GitHub Actions + Neon

Make PFIP run as an **always-on cloud pipeline** with zero servers to babysit:

- **GitHub Actions** is the scheduler **and** the compute (cron-triggered jobs
  run the ingest/feature/regime/signal pipeline).
- **Neon** is the managed Postgres (free tier, 0.5 GB).
- Your **local app** can point at the same Neon DB, so the UI shows the same
  data the cloud job produces. Ollama + Qdrant stay local (privacy + cost).

The pipeline scripts are plain-async and depend only on `DATABASE_URL` — no
Prefect, no Docker. They reuse the exact ingest/feature/regime/signal functions
the Prefect flows wrap.

| Workflow | File | Trigger | Runs |
| --- | --- | --- | --- |
| Daily ingest | `.github/workflows/daily-ingest.yml` | cron 22:30 & 12:30 UTC (Mon–Fri) + manual | `scripts/run_daily_pipeline.py` |
| Backfill | `.github/workflows/backfill.yml` | manual only | `scripts/backfill_history.py` |
| Weekly | `.github/workflows/weekly.yml` | cron Sun 03:30 UTC + manual | `scripts/run_weekly.py` |

---

## (a) Create a free Neon project + get the async URL

1. Sign up at <https://neon.tech> → **New Project** (pick a region near you;
   any region is fine, the free tier is 0.5 GB).
2. On the project dashboard, open **Connection Details** and copy the
   connection string. It looks like:

   ```
   postgresql://myuser:mypassword@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

3. **Convert it to the app's async driver form.** PFIP uses SQLAlchemy with
   psycopg v3 (`postgresql+psycopg://`). Rewrite the scheme and make sure
   `sslmode=require` is present (Neon requires TLS):

   - change `postgresql://` → **`postgresql+psycopg://`**
   - keep everything else; ensure the query string ends with **`?sslmode=require`**

   Final value to use as the `DATABASE_URL` secret:

   ```
   postgresql+psycopg://myuser:mypassword@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

   > The app also accepts a plain `postgresql://...` URL and rewrites the scheme
   > to `postgresql+psycopg://` internally (see
   > `pfip/core/config.py::database_url_async`), **but** you must still keep
   > `?sslmode=require` in the string or Neon will refuse the connection. Using
   > the explicit `postgresql+psycopg://` form is the least surprising.

   If Neon gives you a **pooled** host (contains `-pooler`), that works too and
   is preferable for many short connections.

---

## (b) Add the GitHub repo Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**.

### Required

| Secret | Value |
| --- | --- |
| `DATABASE_URL` | the `postgresql+psycopg://…?sslmode=require` string from step (a) |

### Optional — data-source API keys (all free-tier)

Each adapter **no-ops gracefully** when its key is absent (logs a warning,
contributes 0 rows), so you only need the ones whose data you want. The pipeline
still runs end-to-end with **none** of these set — you'll just get keyless
sources only: crypto OHLCV (ccxt, public), India EOD (jugaad, public), FX
(Frankfurter, public), and public RSS news.

| Secret | Source / what it unlocks | Get a key |
| --- | --- | --- |
| `TIINGO_API_KEY` | US equities EOD OHLCV (SPY, NVDA, …) | <https://tiingo.com> |
| `FINNHUB_API_KEY` | US company fundamentals metrics | <https://finnhub.io> |
| `SEC_EDGAR_USER_AGENT` | SEC filings — **must be `"Name email"`** (a URL-style UA is 403'd) | no key; set to e.g. `PFIP you@example.com` |
| `NASDAQ_DATA_LINK_API_KEY` | NASDAQ Data Link curated datasets | <https://data.nasdaq.com> |
| `FRED_API_KEY` | Macro series (rates, CPI, GDP) | <https://fred.stlouisfed.org/docs/api/api_key.html> |
| `EIA_API_KEY` | Energy / commodities | <https://www.eia.gov/opendata/register.php> |
| `CRYPTOPANIC_API_KEY` | Crypto news | <https://cryptopanic.com/developers/api/> |
| `GLASSNODE_API_KEY` | On-chain crypto metrics | <https://glassnode.com> |
| `COINGLASS_API_KEY` | Crypto derivatives metrics | <https://coinglass.com> |
| `COINGECKO_API_KEY` | Crypto market data (optional; public tier works without) | <https://www.coingecko.com/en/api> |
| `ETHERSCAN_API_KEY` | Self-custody ETH balances | <https://etherscan.io/apis> |
| `SOLSCAN_API_KEY` | Self-custody SOL balances | <https://solscan.io> |
| `NEWSAPI_API_KEY` | General news | <https://newsapi.org> |
| `MARKETAUX_API_KEY` | Market news | <https://marketaux.com> |
| `REDDIT_CLIENT_ID` | Reddit social ingest | <https://www.reddit.com/prefs/apps> |
| `REDDIT_CLIENT_SECRET` | Reddit social ingest | (same app) |
| `REDDIT_USER_AGENT` | Reddit UA string, e.g. `pfip:v0.1 (by /u/you)` | n/a |
| `NEYNAR_API_KEY` | Farcaster ingest | <https://neynar.com> |
| `BLUESKY_HANDLE` | Bluesky ingest | your handle |
| `BLUESKY_APP_PASSWORD` | Bluesky ingest | Bluesky → App Passwords |
| `TELEGRAM_API_ID` | Telegram channel ingest | <https://my.telegram.org> |
| `TELEGRAM_API_HASH` | Telegram channel ingest | (same) |

> **Never** paste any of these into the repo, `.env.example`, or a workflow
> file. They live only in GitHub Secrets and are injected as env vars at run
> time (see the `env:` block in each workflow).

The Screener.in (India fundamentals), jugaad (India EOD), ccxt (crypto OHLCV),
and Frankfurter (FX) sources need **no key**.

---

## (c) Run the backfill once

Seeds the empty Neon DB with ~3 years of history (re-pulled from the upstream
sources — there is nothing to export/import from the local Timescale DB).

1. Repo → **Actions → Backfill history → Run workflow**.
2. Leave `days = 1200` (≈ 3 years) and `skip_compute = false`.
3. Watch the run. It will:
   - `alembic upgrade head` (creates the schema; the TimescaleDB-specific bits
     are auto-skipped on plain Postgres/Neon),
   - page ~1100 daily crypto bars (BTC/ETH/SOL) via ccxt,
   - pull US EOD (Tiingo, if the key is set) + the 50 NIFTY-50 `.NS` names + FX,
   - compute features → regime → signals for the watchlist,
   - print a structured JSON summary at the end (rows/symbols per stage).

Expect ~10–30 min depending on which keys are set. It's **idempotent** — safe to
re-run if it's interrupted.

---

## (d) Confirm daily-ingest

1. Don't wait for the cron — trigger it manually first: **Actions → Daily ingest
   → Run workflow** (leave `stages` blank for all stages).
2. Confirm the run is green and the final log shows the per-stage summary, e.g.:

   ```json
   {
     "stages_run": ["ingest", "features", "regime", "signals", "retention"],
     "results": {
       "ingest": { "crypto_ccxt": 84, "us_tiingo": 18, "india_jugaad": 1024, "fx_frankfurter": 3, ... },
       "features": { "watchlist": { "symbols": 57, "rows_written": 42638, ... } },
       "regime":   { "watchlist": { "symbols": 57, "labeled": 56, ... } }
     }
   }
   ```

3. After this, the two daily crons run automatically Mon–Fri (22:30 UTC after
   the US close, 12:30 UTC after the India close).

> **Note on signals:** the `signals` stage respects the `FEATURE_ML_SIGNALS`
> kill-switch and stays OFF (status `skipped`) until you have enough OHLCV
> history for the walk-forward trainer to be trustworthy. After the backfill,
> add a repo secret/var `FEATURE_ML_SIGNALS=true` (or set it in the workflow
> `env:`) to enable signal generation.

> **GitHub schedule caveats:** cron is best-effort (can be delayed under load),
> and scheduled workflows are auto-disabled after **60 days of repo inactivity**
> — push a commit or re-enable from the Actions tab if that happens.

---

## (e) Point the LOCAL app at Neon

The local UI can read the cloud data directly — only the DB moves; Ollama and
Qdrant stay local.

1. In `backend/.env`, set `DATABASE_URL` to the same Neon async URL from
   step (a):

   ```dotenv
   DATABASE_URL=postgresql+psycopg://myuser:mypassword@ep-cool-name-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

2. Leave the local Ollama / Qdrant settings untouched (defaults point at the
   local Docker services):

   ```dotenv
   OLLAMA_HOST=http://localhost:11434   # or http://ollama:11434 inside compose
   QDRANT_URL=http://localhost:6333
   ```

3. Restart the backend (or the compose stack). The app now reads/writes the
   Neon DB while keeping inference + vector search local.

> The local Docker default DB (`postgresql+psycopg://pfip:pfip_dev@timescaledb:5432/pfip`)
> is unchanged — it remains the fallback whenever `DATABASE_URL` is not set in
> the environment. So you can flip between local Timescale and Neon just by
> setting/unsetting `DATABASE_URL`.

---

## (f) Free-tier storage (0.5 GB) — and how it stays bounded

Neon's free tier caps storage at **0.5 GB**. The pipeline keeps the DB under
that by pruning on every daily run (the `retention` stage in
`run_daily_pipeline.py`):

- **features** older than ~1200 days are deleted (features are recomputable from
  OHLCV, so they're the cheap thing to drop),
- **news** is pruned by both **relevance** (drop anything not tied to the tracked
  universe / market-moving macro) and **age** (drop rows older than ~60 days);
  only titles + short summaries are ever stored — never raw article bodies.

OHLCV history is retained (it's the training substrate) but it's small: ~57
symbols × ~1200 daily bars is well within budget. If you ever approach the cap,
check table sizes with:

```sql
SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;
```

and either trim the watchlist or lower `FEATURES_RETENTION_DAYS` /
`prune_old(days=...)`.
