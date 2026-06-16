# PFIP Capabilities Reference

> **What each part of PFIP can actually do** — a plain-language reference so you (or a
> collaborator) can understand the system without reading the code. Pairs with
> `docs/PROJECT_TRACKER.md` (status & what's left) and `docs/FEATURES.md` (feature-engineering
> math). Notion-importable.

**Last updated:** 2026-06-16

---

## At a glance

PFIP is a **personal financial intelligence platform**: it ingests market + alternative data
across 5 markets, engineers features, detects market regimes, (optionally) generates ML signals,
backtests them, and surfaces everything through a dashboard and an LLM chat agent that explains —
never decides. Advisory-only by design.

**Markets:** crypto · US equities/ETFs · Indian equities (NSE) · Indian mutual funds · FX.

---

## 1. Data ingestion (`pfip/ingest/`, 43 modules)

**What it can do:** Pull daily data from 40+ free/freemium sources across OHLCV, fundamentals,
on-chain, derivatives, macro, news, social, prediction markets, and academic feeds. Every source
is **non-fatal**: it runs under a wall-clock timeout and try/except, so one source failing
contributes 0 rows but never aborts the run. Writes are idempotent (`ON CONFLICT DO NOTHING`).

**Key capabilities by category:**
- **OHLCV:** crypto via ccxt (Coinbase/Kraken/Bybit/OKX); US via Tiingo→yfinance→Stooq; India via
  jugaad + NSE/BSE bhavcopy; FX via Frankfurter.
- **Fundamentals:** US via Finnhub + SEC EDGAR; India via Screener.in. P/E, P/B, D/E, ROE, ROCE.
- **On-chain / derivatives:** Glassnode/CoinGecko/CoinMetrics (MVRV, netflow, hash rate),
  Coinglass (funding, open interest, long/short).
- **News + social:** GDELT, Google News RSS, NewsAPI, Marketaux, Reddit, Bluesky, Farcaster,
  Telegram, CryptoPanic, SEC 8-K. Post-ingest pipeline: dedupe → entity-link → classify → embed.
- **Macro / commodities:** FRED, DBnomics, World Bank, EIA, LBMA gold, NASDAQ Data Link.
- **Other:** AMFI mutual-fund NAVs, NSE FII/DII + disclosures, Kalshi/Polymarket, arXiv q-fin.

**Current limitations:** Keyed sources no-op without their key (US/Tiingo, Finnhub, FRED, etc.).
FX currently times out in cloud. India MF NAVs not yet in the backfill path.

---

## 2. Feature engineering (`pfip/features/`)

**What it can do:** For each watchlist asset, compute a point-in-time feature bundle and upsert it.

- **7 canonical technicals** (typed columns): `rsi_14`, `macd`, `macd_signal`, `macd_hist`,
  `atr_14`, `return_7d`, `volatility_30d`.
- **Extras (JSONB):** fundamentals (equity), on-chain + derivatives (crypto), macro (VIX, DXY,
  US10Y, yield curve, USDINR), cross-asset correlations (BTC↔SPY/gold, target↔DXY/US10Y).

**Current limitation:** Extras are stamped **only on the latest bar** to keep writes light, so
historical feature rows carry technicals but empty extras — a constraint for any supervised model
that wants extras with history.

---

## 3. Regime detection (`pfip/regime/`)

**What it can do:** Fit a 4-state Hidden Markov Model on ~3y of trailing daily returns per symbol
and label today's regime (bull_trend / bear_trend / sideways / high-vol) with a confidence. Labels
persist to the `regime` table and drive the regime-router for signals. Deterministic state→regime
mapping.

**Current limitation:** MLflow model persistence fails in the cloud runner (so models label but
aren't saved/versioned). Two symbols show soft convergence warnings.

---

## 4. Signals & ML (`pfip/signals/`) — 🔒 gated off today

**What it can do (when `FEATURE_ML_SIGNALS=true`):** Generate a per-asset directional signal from a
**LightGBM 3-day classifier**, walk-forward trained and isotonic-calibrated, with SHAP-derived
driver explanations. A **regime-router** picks a different model per HMM state. Signals are
**advisory only** — never auto-executed.

**Why it's off:** The walk-forward trainer needs ~756+ bars (≈3y) per asset; until the universe has
that history, signals stay gated. This is by design, not a bug.

**Planned:** Bake off OSS zero-shot forecasters (Chronos/TimesFM) against this baseline before
committing to a model.

---

## 5. Backtesting (`pfip/backtest/`)

**What it can do:** vectorbt-driven **walk-forward** backtests (expanding window, embargo, CPCV
folds) with realistic per-market transaction costs and slippage; **Monte Carlo** block-bootstrap
confidence intervals & drawdown analysis; **permutation/shuffle** significance testing; full
**tearsheets** (Sharpe, Sortino, max drawdown, hit rate, turnover); benchmark comparison vs
buy-hold / MA / RSI / SPY / NIFTY50.

**Current limitation:** Built and unit-tested, but not yet exercised on live signals (which are off).

---

## 6. Agent & knowledge base (`pfip/agent/`, `pfip/kb/`)

**What it can do:** A **LangGraph chat agent** that classifies intent, retrieves from the knowledge
base (Qdrant), recent news, and the DB, then synthesizes a cited answer over SSE streaming. It
**explains, never decides** — guarded so typed Signals never leak as recommendations.
**Privacy-gated:** any holdings-bearing prompt is forced to local-only Ollama and never reaches a
cloud LLM, even on a classifier miss. Multi-provider router (Ollama→Groq→Gemini→DeepSeek→OpenRouter).

Also generates: **morning brief**, close-time **post-mortem**, **weekly review**, **arXiv q-fin
digest** — all from real DB queries, with the LLM writing only connective prose.

**Current limitations:** Knowledge base is empty until books are supplied (agent cites news/DB
only). Chat history sidebar is an unwired placeholder.

---

## 7. Portfolio, risk & tax (`pfip/portfolio/`, `pfip/tax/`, `pfip/brokers/`)

**What it can do:**
- **Mark-to-market** valuation (latest OHLCV close, USD→INR via `fx_rates`, cost-basis fallback by
  abstention), real P&L, exposure, historical VaR 95/99, Herfindahl concentration, real Pearson
  correlation matrix, trailing-30d Sharpe, peak-to-current drawdown.
- **Risk manager:** 10-item pre-trade checklist, 20% drawdown halt, 0.7 correlation guard, Van
  Tharp position sizing, daily new-position cap.
- **Indian tax engine (advisory):** STCG/LTCG with FIFO + grandfathering, VDA 30% + 1% TDS,
  Schedule FA, Form 67 DTAA, 80C optimiser, old-vs-new regime comparison.
- **Broker CSV import:** 10 adapters (Zerodha, ICICIdirect, Groww, Vested, Binance, Kraken,
  Coinbase, CoinDCX, …) with auto-detected schemas.

**Current limitations:** Precommitment Sharpe-floor gate is a no-op. Broker imports await user CSVs.
Tax outputs are advisory ("consult a CA").

---

## 8. Frontend (`frontend/`, Next.js 14)

**What it can do:** 18 pages — dashboard, watchlist, portfolio, signals, shadow portfolio,
backtest, calibration, journal, tax (+ harvest), diligence, chat (SSE), settings, and ops pages
(model registry, schedules, source health). Mobile-responsive, dark mode, Cmd+K palette, stale-data
badges, correlation heatmap, reliability diagrams, SHAP driver bars. Auth via NextAuth + middleware,
CSP/security headers (14.2.35).

---

## 9. Infra & ops

**What it can do:** Two deployment modes — (a) **cloud**: Neon Postgres + GitHub Actions cron
(daily ingest 2×/day, weekly fundamentals/training, manual backfill), gated by `PFIP_PIPELINE_MODE`
for headless auth; (b) **local**: full Docker compose (TimescaleDB, Redis, Qdrant, Prefect, MLflow,
Ollama, Uptime Kuma). CI runs ruff/black/mypy/pytest + frontend lint/typecheck/test + integration
suite against a real Postgres. Backup/restore via `pg_dump` + Qdrant snapshots.

**Current limitation:** MLflow artifacts don't persist in the cloud runner yet.

---

## Design principles (why it's built this way)

- **Advisory, not autonomous** — the system informs decisions; a human always decides and executes.
- **Privacy first** — holdings never reach a cloud LLM; sensitive queries stay local.
- **Non-fatal ingestion** — partial data is normal; one dead source never breaks a run.
- **Honest ML** — signals stay off until there's enough history to train and calibrate them.
- **Free-tier by default** — CPU-only, free APIs; GPU only via Colab for occasional high-impact work.
