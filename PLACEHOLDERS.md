# PFIP Placeholders — Inputs You Still Need To Provide

**Read `BUILD_STATUS.md` first.** This file is the punch list of user-input items.

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
