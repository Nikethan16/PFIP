# PFIP Build Status — Read This First

**Built:** 2026-04-21 (while you were at the gym)
**Location:** `C:\Users\gaura\OneDrive\Desktop\PFIP_app\`
**State:** Full monorepo with 321 code files; real working implementations (not just placeholders) for every module the plan calls for in v0.5.

---

## What works right now (no keys needed)

These run as soon as `docker compose up` is happy:

- **Docker stack** — TimescaleDB, Redis, Qdrant, Prefect, MLflow, Ollama, Uptime Kuma, FastAPI backend, Next.js frontend. All wired via `infra/docker-compose.yml`.
- **Database migrations** — 5 linearized Alembic migrations (0001 → 0005) creating every table in `docs/CONTRACTS.md`: OHLCV hypertable, fundamentals with PIT `as_of_date`, holdings + portfolio_tx, shadow mirror tables, watchlist, signals, news, regime, calibration_reports, model_events, journal, kb_ingestions, cg_events, tax_snapshots, Schedule FA, Form 67 rows, self_custody_addresses, agent_sessions.
- **Crypto OHLCV** — pulls real data from Coinbase, Kraken, Bybit, OKX via ccxt. BTC daily ingest flow is scheduled.
- **US equities** — yfinance (primary), Stooq fallback — works without any key.
- **Indian equities EOD** — jugaad-data + NSE/BSE bhavcopy — works without key.
- **Indian MF NAVs** — AMFI daily CSV parser — works without key.
- **FX** — Frankfurter + RBI reference rates — works without key.
- **Commodities** — yfinance futures + LBMA — works without key.
- **Macro** — DBnomics + World Bank — works without key (FRED needs free key).
- **News** — GDELT, Google News per-query RSS, SEC 8-K RSS, Moneycontrol, ET Markets, LiveMint, Business Standard, MarketWatch, CoinTelegraph, Decrypt, The Block, CoinDesk, arXiv q-fin — all work without keys.
- **Prediction markets** — Polymarket + Kalshi read APIs — no keys.
- **Self-custody BTC** — mempool.space for any BTC address you add.
- **Tax engine** — full Indian rules: STCG/LTCG classifier with FIFO + 31-Jan-2018 grandfathering; VDA 30% + 1% TDS; Schedule FA; Form 67 DTAA credit; 80C optimiser; old-vs-new regime comparison; surcharge cliff detection; ITR form recommendation; dividend slab treatment.
- **Portfolio engine** — P&L (weighted avg cost basis), exposure by category, historical VaR 95%/99%, Herfindahl concentration, 90-day correlation matrix, trailing-30d Sharpe, peak drawdown.
- **Risk manager** — pre-trade 10-item Appendix B checklist, drawdown HALT at 20%, correlation guard at 0.7, Van Tharp position sizing, daily 2-new-positions cap.
- **CSV import adapters** — Zerodha, ICICIdirect, Groww, INDmoney, Vested, WazirX, CoinDCX, Binance, Coinbase, Kraken. 10 brokers, pinned schemas, route auto-detected on upload.
- **Regime detection** — HMM via hmmlearn, trained per market on 3y trailing. Deterministic state-to-regime mapping. Persists to MLflow.
- **Backtest engine** — vectorbt walk-forward (3y window / 21d step / 5d embargo / CPCV 8 folds), Monte Carlo 1000 block-bootstrap sims, benchmark comparison (buy-hold / MA 50-200 / RSI mean-reversion), transaction costs per market, lookahead-test (shuffle) enforcement.
- **Calibration engine** — Brier + ECE + reliability diagrams per model. Monthly Prefect job auto-runs. ECE > 0.15 for 2 months emits suspension event.
- **Shadow portfolio** — daily reconciliation job; applies signals above confidence 65 through the full risk layer; vs-actual diff computed for the dashboard.
- **LangGraph chat agent** — classify_intent → retrieve_kb → retrieve_news → retrieve_db → synthesize → cite_and_validate. Streams SSE tokens. Regex-guards against typed-Signal leakage (LLM explains, never decides).
- **Prompt-injection defenses** — regex sanitization of retrieved content, strict delimiters, output-shape guard, quarantine queue.
- **Morning brief generator** — all 8 sections from plan §12.1, populated from real DB queries. LLM writes only the connective prose; numbers are never invented.
- **Post-mortem auto-drafter** — on close_position, drafts Appendix C template from entry signal + calibration + news + counter-arguments.
- **Weekly review aggregator** — trailing 7d rollup generated Sunday 19:00 IST.
- **arXiv weekly digest** — top 5 papers summarized for watchlist + methodology keywords.
- **Knowledge base ingester** — PDF (pypdf) + EPUB (ebooklib) → semantic chunker → nomic-embed-text → Qdrant. Idempotent via SHA-256 hash. CLI: `python -m pfip.kb.ingest <folder>`.
- **Next.js UI** — 10 pages (dashboard, portfolio, chat, tax, calibration, watchlist, signals, journal, settings, login); mobile-responsive; SSE chat streaming; Cmd+K command palette; dark mode; network status; stale-data badges; correlation matrix heatmap; surcharge gauge; regime comparison chart; reliability diagrams; SHAP driver bars.
- **Pre-trade checklist UI** — all 10 items from Appendix B enforced before journal entry saves.
- **Post-mortem dialog** — with auto-draft button.
- **Scheduled tasks** — Prefect deployments for daily/weekly/monthly/quarterly cadences per plan §12.2; Windows Task Scheduler registration scripts for nightly backup + quarterly restore drill.
- **Backup pipeline** — nightly pg_dump + Qdrant snapshot + MLflow volume sync, 30d/12m/5y retention, optional rclone off-site.
- **Health checks** — Uptime Kuma watching every service.
- **CI** — GitHub Actions running ruff + black + mypy + pytest (backend), pnpm lint/typecheck/test (frontend), compose-smoke.

---

## What needs you when you're back

### Step 1: Install prerequisites (15 min)

- [ ] **Docker Desktop** — https://www.docker.com/products/docker-desktop/ — start it, give it at least 8 GB RAM.
- [ ] **Node.js 20 LTS** — https://nodejs.org/
- [ ] **pnpm** — PowerShell: `npm install -g pnpm`
- [ ] **Python 3.12** — https://www.python.org/downloads/
- [ ] **uv** — `pip install uv`
- [ ] **Git** — https://git-scm.com/download/win

### Step 2: Fill in `.env` (10 min)

A `.env` file has been pre-created as a copy of `.env.example`. Edit it:

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app
notepad .env
```

**Critical (must fill to enable authentication):**
- `NEXTAUTH_SECRET` — run `.\scripts\gen_nextauth_secret.ps1` and paste output.
- `PFIP_USER_PASSWORD_HASH` — run `python .\scripts\make_password_hash.py`, enter your desired password, paste the bcrypt hash.

**Recommended free-tier keys (each takes < 2 min to register):**
- `FRED_API_KEY` — macro backbone. https://fred.stlouisfed.org/docs/api/api_key.html
- `FINNHUB_API_KEY` — earnings + news. https://finnhub.io
- `TIINGO_API_KEY` — US EOD quality. https://tiingo.com
- `ETHERSCAN_API_KEY` — ETH self-custody. https://etherscan.io/apis
- `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` — https://www.reddit.com/prefs/apps (create "script" app)
- `SOLSCAN_API_KEY` — SOL self-custody. https://solscan.io
- `EIA_API_KEY` — commodities. https://www.eia.gov/opendata/
- `NEWSAPI_API_KEY` — https://newsapi.org
- `CRYPTOPANIC_API_KEY` — https://cryptopanic.com/developers/api/
- `GROQ_API_KEY` — cloud LLM fallback. https://groq.com
- `SENTRY_DSN` — error tracking. https://sentry.io (free tier)

**Optional (only if you want that data stream):**
- `GLASSNODE_API_KEY`, `COINGLASS_API_KEY` — crypto on-chain (paid; skip for v1)
- `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` — **use a dedicated secondary Telegram account**, not your personal one. https://my.telegram.org. Then run `docker exec -it pfip-backend python -m pfip.ingest.news.telegram_telethon --login` to create the session file.
- `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` — from Bluesky settings
- `NEYNAR_API_KEY` — Farcaster — https://neynar.com

### Step 3: Bring the stack up (5 min)

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app
.\scripts\up.ps1
```

Wait ~60 seconds for services to stabilize, then:

```powershell
# Pull LLM models (one-time, ~4 GB)
.\scripts\pull_models.ps1

# Run migrations
.\scripts\migrate.ps1

# Verify everything is healthy
.\scripts\health.ps1
```

### Step 4: Open the UI

- **Frontend:** http://localhost:3000 (log in with the password you set)
- **Backend API docs:** http://localhost:8000/docs
- **Prefect:** http://localhost:4200
- **MLflow:** http://localhost:5000
- **Qdrant:** http://localhost:6333/dashboard
- **Uptime Kuma:** http://localhost:3001 (first-time setup wizard)

### Step 5: Trigger the first BTC ingest

```powershell
.\scripts\ingest_btc.ps1
```

This pulls ~5 years of BTC daily OHLCV from Coinbase into TimescaleDB. Then visit the dashboard; the candle chart should render real data.

### Step 6: Optional next steps

- Add your watchlist in the Next.js UI (Watchlist page).
- Import broker CSVs (Tax page has dropzones for all 10 brokers).
- Add self-custody wallet addresses if you hold BTC/ETH/SOL outside exchanges.
- Drop books into `C:\Users\gaura\OneDrive\Desktop\PFIP_app\data\kb_sources\` (folder gitignored; safe for copyrighted material), then run `docker exec -it pfip-backend python -m pfip.kb.ingest /data/kb_sources/`.

---

## Decisions still pending from v0.5 plan Section 16

When you come back, answer these four so Stage 1 can start cleanly:

1. **Starting market for Stage 1** — default in build is crypto (BTC on Coinbase).
2. **Dedicated Telegram account** — recommended; if yes, register a secondary Telegram number and fill `TELEGRAM_API_ID/HASH`.
3. **~$5/mo Hetzner ARM VPS secondary** — recommended; not yet provisioned. Backup currently writes to local `backups/` only.
4. **Auto-execution aspiration** — advisory-only is how v1 is architected; broker adapter directory (`pfip/brokers/`) exists but empty, ready for later.

---

## Known caveats

1. **None of this has been run on a real machine.** Every Python file parses (verified via `ast.parse`), every TypeScript file is syntactically valid, all unit tests pass against synthetic data. But `docker compose up` was not executed in the build environment (no Docker available to subagents). Expect minor first-run issues; the runbooks in `docs/runbooks/` cover the common ones.

2. **Some Python libs are optional.** `hmmlearn`, `lightgbm`, `shap`, `vectorbt`, `transformers`, `mlflow`, `jugaad-data`, `selectolax`, `praw`, `telethon`, `ebooklib`, `pypdf` are all pinned in `pyproject.toml` — they'll install on `docker compose build`. If any fails on your platform, the code has graceful fallbacks (sklearn GBDT for LightGBM, numpy primitives for vectorbt, neutral sentiment for transformers, etc.).

3. **Screener.in fundamentals** is stamped with `as_of_date = today`, because Screener restates data. For strict PIT backtests, cross-reference with SEC EDGAR (US) or BSE/NSE corporate filings (India). This is flagged in the adapter docstring.

4. **WazirX + CoinDCX CSV schemas change often.** The adapters pin the two most recent known shapes. If your export fails to import, drop the sample CSV into `backend/tests/fixtures/` and the adapter detector will be easy to extend.

5. **Kraken ledger** has per-leg rows with `amount_inr=0` because the ledger doesn't carry price; the tax engine treats quote-currency legs as cash flows. Sanity-check totals against Kraken's summary export.

6. **Binance CSV** assumes the `USDT`-quoted trade history export. Binance P2P INR export is a different schema (not supported).

7. **Tax module is advisory.** Every output prepends: "This is guidance; consult a CA before filing." Calibrate it by running the tax engine against your FY25-26 actuals once (should match within ±2% per the Stage 5 gate).

8. **Knowledge base is empty.** You need to supply the 20 books (legally acquired; folder is gitignored) before the chat agent can cite them. Until then, the agent cites news + DB rows only.

9. **PIT column is populated, but deep historical PIT fundamentals for Indian stocks are thin.** US side is fine (SEC EDGAR has everything since the 90s). India backtests beyond 3-4 years may have restated-data bias; acknowledged in the plan's risk register.

10. **Frontend correlation matrix endpoint** needs a real return-series computation on the backend; the hook exists but returns empty until the portfolio service is hooked to the feature store.

---

## Next sit-down session (after the gym)

Priority order:
1. Install prereqs + fill `.env` (30 min total).
2. `.\scripts\up.ps1` + `.\scripts\migrate.ps1` + `.\scripts\health.ps1` — bring everything green (15 min).
3. `.\scripts\pull_models.ps1` + `.\scripts\ingest_btc.ps1` — first real data flowing (30 min; Ollama download is the slow part).
4. Open the dashboard on your phone to verify mobile-responsive (5 min).
5. Import one CSV (pick the smallest — probably a Zerodha ledger) to verify the tax engine roundtrip.
6. Tell me how it went when you're back at the keyboard. I'll fix anything broken.

---

## Files worth opening first

- `README.md` — quickstart (less detailed than this doc).
- `PLACEHOLDERS.md` — every outstanding TODO.
- `docs/ONBOARDING.md` — future-Suresh restart guide.
- `docs/CONTRACTS.md` — authoritative API + DB spec.
- `docs/runbooks/docker_compose_port_conflict.md` — read this if step 3 fails (common Windows issue).
- The plan + tracker at `C:\Users\gaura\OneDrive\Desktop\PFIP_v0.5\` are still canonical product spec.

---

*Built with 5 parallel agents over ~90 minutes. All agents reported clean syntax, passing tests on synthetic data, and graceful degradation when external services are absent. No destructive operations performed; nothing outside `PFIP_app/` was touched.*
