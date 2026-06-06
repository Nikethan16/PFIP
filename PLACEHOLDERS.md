# PFIP Placeholders — Inputs You Still Need To Provide

**Read `BUILD_STATUS.md` first.** This file is the punch list of user-input items.

---

## Priority 0 — Post-audit action items (added 2026-06-04)

These came out of the full security/correctness audit. The code fixes are done;
these specific steps need **you** because they involve secrets, a package install,
or a product decision. Nothing here blocks the app from running in dev.

### 0.1 Apply the Next.js security bump (REQUIRED — 1 command)
`frontend/package.json` was bumped `next` and `eslint-config-next` `14.2.5 → 14.2.35`
(patches a critical middleware auth-bypass + dev-server info-leak). The lockfile was
**not** updated because pnpm wasn't available during the fix. Run:
```powershell
cd frontend
pnpm install            # refreshes pnpm-lock.yaml + pulls next@14.2.35
pnpm typecheck; pnpm lint   # verify the frontend edits (middleware, zod schemas, a11y) type-check
```
- [ ] `pnpm install` run, `next@14.2.35` resolved.
- [ ] `pnpm typecheck` and `pnpm lint` pass.

### 0.2 Secrets are now MANDATORY (fail-loud, no more silent dev defaults)
`infra/docker-compose.yml` no longer falls back to the publicly-known
`NEXTAUTH_SECRET=dev-change-me` / `POSTGRES_PASSWORD=pfip_dev`. Compose now **refuses
to start** if these are unset, and the backend (`core/config.py`) raises on boot if
`APP_ENV != dev` and any auth secret is still a default. Make sure `.env` has real
values (per §1.2 below). To get the stricter boot-time check in production, also set:
- [ ] `NEXTAUTH_SECRET` set to a real 32-byte value in `.env` (see §1.2).
- [ ] `POSTGRES_PASSWORD` set to a real value in `.env` (and matched inside `DATABASE_URL`).
- [ ] (When deploying for real) set `APP_ENV=prod` in `.env` to activate fail-loud secret validation.

### 0.3 Error tracking (OPTIONAL but recommended)
A Sentry hook is now wired in `api/main.py` — it activates only if `SENTRY_DSN` is set,
and is a no-op otherwise. `sentry-sdk[fastapi]` is pinned in `requirements.txt`.
- [ ] Fill `SENTRY_DSN` in `.env` (free tier — see §2 list) to get unhandled-exception alerts.

### 0.4 Ollama image was pinned (verify the version suits you)
`ollama/ollama:latest → ollama/ollama:0.30.4` for reproducibility. If you need a
different Ollama version, edit `infra/docker-compose.yml` and re-pull.
- [ ] Confirm `0.30.4` is acceptable, or change the pin.

### 0.5 Reranker — RESOLVED (wired 2026-06-04, privacy-gated)
The Cohere reranker is now wired into the live RAG path, **behind the privacy gate**: KB/news
hits are reranked via Cohere **only for non-sensitive queries**; SENSITIVE queries (incl. any
holdings-bearing prompt) use identity order and **never** call Cohere. No-op without
`COHERE_API_KEY`. This is no longer a pending decision — see `docs/LLM_ROUTING.md` §5.1.
- [ ] (Optional) Add `COHERE_API_KEY` to `.env` to actually get the rerank quality lift on
  non-sensitive RAG queries. Without it the path is a safe no-op (identity order).

### 0.5b Mark-to-market + correlations are now LIVE — operational notes
`/portfolio/summary` is now real mark-to-market, `/portfolio/correlations` returns a real
matrix, and `/exposure` + `/concentration` use live prices. A new `GET /portfolio/marking`
reports coverage (which holdings are live-priced vs cost-basis, the USD/INR used, and why any
holding fell back). For these to show real numbers:
- [ ] **Ingest OHLCV** for your held symbols (the dashboards mark to the latest close).
- [ ] **Populate the `fx_rates` table** (USD→INR) — required to value USD assets (crypto/US
  equities). FX ingestion is now real: either let the **`ingest-fx-daily`** Prefect flow run
  (`pfip.ingest.macro.fx_rates`, Frankfurter — free, no key), or run the manual backfill once:
  ```powershell
  python -c "import asyncio; from pfip.ingest.macro.fx_rates import ingest_fx_rates; asyncio.run(ingest_fx_rates(mode='backfill', lookback_days=730))"
  ```
  Without rates, USD holdings safely fall back to cost basis and appear under
  `unmarked: [{reason: "no_fx_rate"}]` in `/portfolio/marking` (never a wrong rupee figure).
- [ ] **Sanity-check the rupee figures** against a known holding once real data is in — the
  valuation logic is unit-tested, but I couldn't validate against your live OHLCV here.
- Optional UI: wire a small "X/Y live-priced, as of …" badge from `GET /portfolio/marking`.

### 0.5c Asset endpoints — RESOLVED (now real, 2026-06-04)
`/assets/{symbol}/features` (latest feature row), `/assets/{symbol}/news` (recent news,
newest-first, `limit` param), and `/assets/{symbol}/regime` (latest regime label; returns
`regime:"unknown"` when none) are now real (were `501` stubs). They return data as soon as the
underlying tables are populated by ingest/feature/regime flows. The Schedule FA peak-balance
approximation remains a stage-gated stub — implement when you reach the relevant stage.

### 0.5d Turning ML signals ON later (they are OFF by design today)
`FEATURE_ML_SIGNALS` is now a **real runtime gate** — the `signals-generate-daily` flow no-ops
(logs) while it's off, and signals are stage-gated (stage 3). ML signals are **not** producing
data today, and that's intentional: the walk-forward trainer needs ~months / ~3y / 756+ bars
of OHLCV history per asset, which a fresh install lacks. When you have enough history and want
to enable them:
- [ ] Set `FEATURE_ML_SIGNALS=true` in `.env`.
- [ ] Apply the stage-3 deployments: `python -m schedules.prefect_deployments apply --stage 3`.
- [ ] Sanity-check the first few signals + their calibration before trusting them.

### 0.6 Integration-test gap — now partly closed (2026-06-04)
The backend suite grew to **557 tests** (was 484). A **real-DB integration suite** was added
this pass (alongside `test_close_position`, `test_marking`, `test_ohlcv_columns`,
`test_drawdown`, `test_fx_ingest`, `test_assets_live`, `test_reranker_wiring`, `test_backup`,
`test_deployments_resolve`), so the SQL layer is no longer only exercised against a fake DB.
All green except 5 `litellm`-not-installed-locally failures (pinned + present in Docker) and a
few Docker-gated integration skips.
- [ ] Run the Docker-gated integration suite locally (needs Docker up) to confirm the
  real-Postgres joins pass on your machine.

---

## Priority 1 — Required before first run

### 1.1 Install prerequisites (Windows)
- [ ] Docker Desktop (https://www.docker.com/products/docker-desktop/) — at least 8 GB RAM allocated.
- [ ] Node.js 20 LTS (https://nodejs.org/)
- [ ] pnpm — `npm install -g pnpm`
- [ ] Python 3.12 (https://www.python.org/downloads/)
- [ ] uv — `pip install uv`
- [ ] Git (https://git-scm.com/download/win)

### 1.2 Generate auth secrets
- [ ] `NEXTAUTH_SECRET` — `.\scripts\gen_nextauth_secret.ps1`
- [ ] `PFIP_USER_PASSWORD_HASH` — `python .\scripts\make_password_hash.py`

### 1.3 Answer the 4 pending plan decisions
Per v0.5 plan Section 16 — default used in build noted in brackets:
1. [ ] Starting market for Stage 1 [default: crypto BTC]
2. [ ] Dedicated Telegram account for Telethon [default: not yet set up]
3. [ ] ~$5/mo Hetzner ARM VPS secondary [default: not provisioned]
4. [ ] Auto-execution aspiration (eventual goal or advisory forever?) [default: architected for eventual, advisory-only in v1]

---

## Priority 2 — Recommended free-tier API keys (each < 2 min to register)

Code is built and will ingest as soon as each key is filled. Missing keys cause a warning log and empty result, never a crash.

- [ ] `FRED_API_KEY` — https://fred.stlouisfed.org/docs/api/api_key.html — **macro backbone, do this first**
- [ ] `FINNHUB_API_KEY` — https://finnhub.io — earnings + econ calendar + news
- [ ] `TIINGO_API_KEY` — https://tiingo.com — US equities EOD + news
- [ ] `ETHERSCAN_API_KEY` — https://etherscan.io/apis — ETH self-custody tracking
- [ ] `SOLSCAN_API_KEY` — https://solscan.io — SOL self-custody tracking
- [ ] `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` + `REDDIT_USER_AGENT` — https://www.reddit.com/prefs/apps (create "script" app)
- [ ] `NEWSAPI_API_KEY` — https://newsapi.org — general financial news aggregator
- [ ] `CRYPTOPANIC_API_KEY` — https://cryptopanic.com/developers/api/
- [ ] `MARKETAUX_API_KEY` — https://www.marketaux.com/
- [ ] `EIA_API_KEY` — https://www.eia.gov/opendata/ — US energy data
- [ ] `FMP_API_KEY` — https://financialmodelingprep.com — US fundamentals fallback
- [ ] `POLYGON_API_KEY` — https://polygon.io — US delayed quotes (free tier)
- [ ] `ALPACA_API_KEY` + `ALPACA_API_SECRET` — https://alpaca.markets (paper account)
- [ ] `GROQ_API_KEY` — https://groq.com — cloud LLM fallback
- [ ] `SENTRY_DSN` — https://sentry.io — error tracking
- [ ] `LANGSMITH_API_KEY` — https://smith.langchain.com — LLM call tracing

---

## Priority 3 — Optional paid / complex keys

- [ ] `GLASSNODE_API_KEY` — https://glassnode.com — most useful metrics are paid-only post-2024 (~$30/mo, recommended at Stage 4 only)
- [ ] `COINGLASS_API_KEY` — https://coinglass.com — derivatives analytics
- [ ] `BINANCE_API_KEY` + `BINANCE_API_SECRET` — only needed for private-balance reads on Binance. Binance spot is restricted for Indian users since 2024.
- [ ] `COINBASE_API_KEY` + `COINBASE_API_SECRET` — only needed for private reads; public OHLCV doesn't need them.

---

## Priority 4 — Dedicated Telegram account (recommended)

Running Telethon on your personal Telegram number risks a ban. Use a dedicated account:

- [ ] Get a secondary SIM or use a virtual number service (recommended since Telegram requires SMS).
- [ ] Register the new number on Telegram.
- [ ] Go to https://my.telegram.org and get `api_id` and `api_hash`.
- [ ] Fill `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in `.env`.
- [ ] Run `docker exec -it pfip-backend python -m pfip.ingest.news.telegram_telethon --login` — it'll prompt for the SMS code and save a session file.
- [ ] Session file path: `backend/pfip/ingest/telegram/pfip_session.session` — gitignored.
- [ ] Create a Telegram bot via @BotFather for outbound alerts, fill `TELEGRAM_BOT_TOKEN` + `TELEGRAM_BOT_CHAT_ID`.

---

## Priority 5 — Bluesky + Farcaster (if you want X-replacement feeds)

- [ ] `BLUESKY_HANDLE` — your Bluesky handle (e.g., `suresh.bsky.social`)
- [ ] `BLUESKY_APP_PASSWORD` — Settings → App passwords on Bluesky
- [ ] `NEYNAR_API_KEY` — https://neynar.com — free tier for Farcaster hub access

Public search mode works without these; they only increase rate limits.

---

## Priority 6 — Broker CSV exports (when tax module is exercised)

The adapters are built; you need to provide the exports when you want to use them. Placeholder sample CSVs exist in `backend/tests/fixtures/` so the adapters compile.

- [ ] Zerodha — download tradebook + ledger + MF statements from Console
- [ ] ICICIdirect — Reports → Transaction history
- [ ] Groww — Reports → Stocks + MF
- [ ] INDmoney — Statements → Transactions (USD + INR columns needed)
- [ ] Vested — Statements → Transactions
- [ ] WazirX — Reports → Trade history (multiple export types; the adapter auto-detects)
- [ ] CoinDCX — Reports → Trade history + Wallet
- [ ] Binance — Export trade history (USDT-quoted)
- [ ] Coinbase — Reports → Transactions
- [ ] Kraken — Ledger export

If a CSV fails to import, the adapter raises `UnknownSchemaError` and the UI shows which columns didn't match. Drop the failing CSV in `backend/tests/fixtures/` and re-run — I'll extend the detector.

---

## Priority 7 — Knowledge base (when you want the agent to cite books)

- [ ] Acquire the 20 books from v0.5 plan Section 10 (legally — purchase or library).
- [ ] Place them in `C:\Users\gaura\OneDrive\Desktop\PFIP_app\data\kb_sources\` (folder is gitignored, safe for copyrighted material).
- [ ] Run:
  ```powershell
  docker exec -it pfip-backend python -m pfip.kb.ingest /data/kb_sources/
  ```
  Expect 30–60 min for all 20 books (chunk + embed).
- [ ] Verify ingestion via Qdrant dashboard http://localhost:6333/dashboard.

---

## Priority 8 — Self-custody wallet addresses

If you hold any of these outside exchanges, add them via the Next.js UI (Settings → Self-custody wallets) or directly:

- [ ] BTC public addresses → hourly balance check via mempool.space (no key).
- [ ] ETH / ERC-20 addresses → Etherscan (needs `ETHERSCAN_API_KEY`).
- [ ] SOL addresses → Solscan (needs `SOLSCAN_API_KEY`).

---

## Priority 9 — Calendar the scheduled tasks

Once the stack is up:

- [ ] Run `.\schedules\register_windows_tasks.ps1` as admin to register nightly backup + quarterly restore drill in Windows Task Scheduler.
- [ ] Start Prefect worker: `docker exec -it pfip-prefect prefect worker start --pool default`
- [ ] Deploy schedules: `docker exec -it pfip-backend python -m schedules.prefect_deployments apply --stage 1`
- [ ] Verify all deployments active in Prefect UI http://localhost:4200.

---

## Priority 10 — First-week operational hygiene

- [ ] First restore drill (don't wait for quarterly): `.\scripts\restore_drill.ps1` after first nightly backup runs. Verify report in `backups/drill-YYYYMMDD.log`.
- [ ] Enable BitLocker on your data drive (see `docs/SECURITY.md`).
- [ ] Tighten Windows Defender Firewall so the backend/frontend ports are localhost-only (docs/SECURITY.md).
- [ ] Enable 2FA on GitHub if pushing there.
- [ ] Set up a personal `ONBOARDING.md` update reminder — edit it at the end of every session so future-you can pick up where present-you left off.

---

## Ongoing — `TODO(user):` tags in code

Grep the repo for `TODO(user):` to find every inline input point. Current concentration:

- Agent persona files: `backend/pfip/agent/prompts/*.md` — tune voice/tone after first week of chat use.
- Morning brief connective prose: `backend/pfip/agent/morning_brief.py` — tune after you see a week of briefs.
- Risk limit defaults: adjust via Settings page in UI, not code.
- Ticker autocomplete data source: `frontend/app/watchlist/page.tsx` — plug in when `/assets/search` endpoint exists.

---

## When everything above is resolved

Delete this file and replace with an updated `docs/ONBOARDING.md` reflecting resolved state.
