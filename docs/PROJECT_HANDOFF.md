# PFIP — Project Handoff

Single canonical brain-dump. If you read this end-to-end you will know
**what PFIP is, why each thing was built the way it was, where every
file lives, how to run it, and what to ask Claude (or yourself) to do
next**.

If you're picking this up in a new chat: paste this entire file at the
start. That + `docs/FEATURES.md` + `docs/INPUTS_NEEDED.md` is the full
context.

Project root on your machine: `C:\Users\gaura\OneDrive\Desktop\PFIP_app\`.
Inside this sandbox: `/sessions/trusting-relaxed-cannon/mnt/Desktop/PFIP_app/`.

Current state (2026-05-30): **190 features shipped · 14 partial · 31 pending ·
5 deliberate non-goals · 451 backend tests passing · 0 type errors**.

> **Update 2026-06-04 — security & correctness audit.** Since the line above, an audit pass
> shipped security/correctness fixes + two portfolio features. Backend suite is now **477
> tests: 471 passing, 1 skipped (LightGBM), 5 failing only because `litellm` isn't installed
> in the local venv** (pinned + present in Docker, so green there). Headlines: loopback-only
> ports + fail-loud secrets in compose; Sentry actually wired; `/assets/*` authed; the chat
> agent structurally forces local-only routing for holdings; `OHLCVRow.ts`→`.time` synonym
> fix (unbroke `/tax/harvest`, `/changes-today`, agent price tool, `market_close`, 3 flows);
> **real mark-to-market** `/portfolio/summary` + new `/portfolio/marking` + real
> `/portfolio/correlations`. Per-asset **ML signal generation is still intentionally not
> enabled** (`signals_generate_daily` not deployed; `signals` table empty). Full grouped list:
> `docs/CHANGELOG.md`.

---

## 1. The 60-second pitch

PFIP — **Personal Financial Intelligence Platform** — is a single-user,
self-hosted Bloomberg-Terminal-equivalent for one engineer (you) who
manages their own money across six asset classes:

1. Crypto (BTC / ETH / SOL / BNB, self-custody included)
2. US equities
3. Indian equities
4. Indian mutual funds
5. PPF / EPF / NPS / FDs / SGBs / bonds
6. Self-custody wallets across the above

What it does, end-to-end:

- **Ingests** ~50 free data sources on schedule (OHLCV, fundamentals,
  news, macro, on-chain, prediction markets).
- **Computes features** + detects market regime via HMM.
- **Trains models** per regime, generates typed BUY/SELL/HOLD signals
  with SHAP explanations.
- **Validates** via walk-forward + CPCV + Monte Carlo backtests, with
  calibration tracking (Brier / ECE) per model.
- **Tracks portfolio** across all 6 asset classes with VaR / Sharpe /
  Sortino / Calmar / max-DD / correlation / Herfindahl concentration.
- **Computes Indian tax** for STCG / LTCG / VDA / dividend / debt-MF
  with 31-Jan-2018 grandfathering, Schedule FA, Form 67 (DTAA),
  80C optimizer, ITR JSON export, loss-harvesting suggestions.
- **Pre-commitment ladder** — a binding self-contract that gates
  real-capital deployment (5% → 10% → 25% → 100% over months of paper
  trading with measurable gates).
- **Agent surface** — chat agent answers questions, drafts morning
  brief / weekly review / market-close summary / post-mortem.
- **Alert system** — Telegram dispatcher with quiet hours, rate cap,
  severity tiers, escalation, digest mode.
- **Operations layer** — source health, Prefect deployments, model
  registry, alerts timeline, schedules.

It is **paper-trading-only in v1**. The LLM never decides trades. The
tax engine never files. The user's brain is the kill switch.

---

## 2. Non-negotiable design principles (the why behind the how)

These were locked in early. Every implementation decision derives from
them.

1. **Trust through transparency.** Every number cites its source.
   Every model's confidence is shown next to the prediction. The
   freshness dot on every KPI is the single most-clicked widget.
2. **Honest about uncertainty.** Empty states say *why* they're empty
   ("not yet ingested" vs "ingested but failing"). No fake numbers.
   No placeholder graphs.
3. **Privacy boundary is hard.** Holdings + tax data never leave the
   machine via cloud LLMs. The router pins `Sensitivity.PERSONAL`
   prompts to local Ollama, period. Public data (news, books) is
   eligible for cloud routing for speed/quality.
4. **No auto-execution, ever.** v1 is paper trading. The LLM produces
   recommendations the user evaluates. There is no broker integration
   that places orders. This is architectural, not just feature-flagged.
5. **Information density first.** This is a tool for a senior engineer
   who codes for a living. KPIs are 2 lines, not 6. Tables are dense.
   Mono numerics with tabular nums. Keyboard shortcuts everywhere.
6. **The pre-commitment ladder is the safety belt.** You cannot move
   from paper to 5% capital without 3 months of validated paper
   performance + a signed file + zero risk-rule breaches. The ladder
   refuses to advance even if asked nicely.
7. **Reproducibility.** Every monetary write carries the FX rate used.
   Every model artifact carries its `alembic_revision`. Every backtest
   is seeded.
8. **Don't build for what hasn't happened.** Failure-pattern clustering
   is heuristic until 50 closed entries exist. Trained model selector
   is deferred until 12 months of labels exist. The system doesn't
   pretend to have data it doesn't.

---

## 3. Tech stack and architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (Next.js 14 App Router · TypeScript · Tailwind)     │
│  - shadcn/ui primitives                                      │
│  - Tremor for KPI / chart cards                              │
│  - Recharts for finance charts (candlesticks, multi-axis)    │
│  - TanStack Query for all server state                       │
│  - next-auth (credentials provider, single user)             │
│  - Lucide React for icons                                    │
│  Slate & Teal Institutional palette (from Stitch DESIGN.md)  │
└──────────────────────────────────────────────────────────────┘
                              │ HTTPS
┌──────────────────────────────────────────────────────────────┐
│  FastAPI backend (Python 3.10, async)                        │
│  - SQLAlchemy 2 + Pydantic v2 + Alembic                      │
│  - Routers per domain (assets, signals, portfolio, tax, etc.)│
│  - JWT auth via NextAuth shim                                │
│  - SSE for chat streaming                                    │
└──────────────────────────────────────────────────────────────┘
        │                  │                  │           │
┌───────▼─────┐   ┌────────▼──────┐   ┌───────▼─────┐  ┌──▼───────┐
│ TimescaleDB │   │  Qdrant       │   │  Redis      │  │  Ollama  │
│ (Postgres + │   │ (KB + news    │   │ (alerts +   │  │ (local   │
│ time hyper- │   │  vectors)     │   │  rate caps) │  │  LLM)    │
│ tables)     │   └───────────────┘   └─────────────┘  └──────────┘
└─────────────┘
        ▲
        │
┌───────┴───────────────────────────────────────────────────────┐
│  Prefect 2 (orchestrator)                                      │
│  - Per-ingest-source flows on cron                             │
│  - Daily: regime detect, reconcile, anomaly scan,              │
│    market-close summary                                        │
│  - Weekly: backtest walk-forward, LGBM training, review        │
│  - Monthly: calibration, RAGAS eval, shadow rollup             │
│  - Annual: ITR drill                                           │
│  - Hourly: skipped-task watchdog                               │
│  - Every 30m: WARN-escalation watchdog                         │
└────────────────────────────────────────────────────────────────┘
        ▲
        │ (telemetry / artifacts)
┌───────┴──────┐  ┌──────────────┐
│   MLflow     │  │ Uptime Kuma  │
│ (experiments │  │ (per-service │
│  + artifacts)│  │  uptime)     │
└──────────────┘  └──────────────┘
```

**Why this stack:**

- **FastAPI + Pydantic v2** — typed contracts everywhere, async-first,
  auto-generated OpenAPI docs.
- **TimescaleDB** — same Postgres ergonomics, native time-series
  hypertables. One DB to rule them all (we don't need a separate OHLCV
  store).
- **Qdrant** — open-source vector DB; runs locally; SHA-deduped ingest.
- **Redis** — alert rate caps + escalation pending queue + agent cache.
- **Ollama** — local LLM endpoint for sensitive prompts. Default model:
  `llama3.1:8b-instruct`.
- **Prefect 2** — better than Airflow for our scale; great UI;
  per-deployment cron + retry.
- **MLflow** — experiment tracking + model registry mirror (artifact
  + metric source-of-truth).
- **Next.js 14 App Router** — server components for auth, client
  components for everything else. shadcn/ui + Tailwind for speed.
- **TanStack Query** — handles all the staleness + refetch + invalidation
  that React Query handles, with first-class TypeScript.

**Not chosen, and why:**

- **No Airflow** — too heavy for solo use.
- **No Kafka / pub-sub** — single-machine workload; Prefect handles
  the queue semantics we need.
- **No K8s** — single host, docker-compose is sufficient.
- **No microservices** — one Python service for the backend; one
  Next.js service for the frontend. Splitting further is premature.
- **No GraphQL** — REST + typed Pydantic schemas is faster to ship
  and easier to debug.

---

## 4. Directory layout

Project root: `PFIP_app/`.

```
PFIP_app/
├── .env                          ← Your secrets. gitignored.
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── alembic/
│   │   └── versions/             ← DB migrations (0001 → 0008)
│   ├── pfip/                     ← The Python package
│   │   ├── __init__.py           ← __version__
│   │   ├── api/                  ← FastAPI routers (one per domain)
│   │   ├── agent/                ← Chat agent + LLM router + morning brief
│   │   ├── alerts/               ← Telegram dispatcher + templates
│   │   ├── backtest/             ← Walk-forward, CPCV, MC, tearsheets
│   │   ├── brokers/              ← CSV adapters (10 brokers)
│   │   ├── calibration/          ← Brier / ECE / reliability
│   │   ├── core/                 ← Config, logging
│   │   ├── db/                   ← Session, base, helpers
│   │   ├── features/             ← Technical, fundamentals, derivatives
│   │   ├── ingest/               ← All ~50 data adapters
│   │   ├── kb/                   ← Knowledge base + RAG + RAGAS eval
│   │   ├── models/               ← SQLAlchemy ORM rows
│   │   ├── news/                 ← Article enrichment
│   │   ├── portfolio/            ← Allocation, risk, pre-commitment
│   │   ├── prefect/              ← Flows + deployments
│   │   ├── regime/               ← HMM detector
│   │   ├── scripts/              ← seed_demo, seed_watchlist, run_ragas_eval
│   │   ├── sentiment/            ← FinBERT classifier
│   │   ├── shadow/               ← Shadow portfolio
│   │   ├── signals/              ← LGBM, auto-selector, registry, SHAP
│   │   └── tax/                  ← Engine, harvest, FX, forms
│   └── tests/                    ← 41 pytest files · 451 passing
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tailwind.config.ts        ← Slate & Teal palette + Stitch tokens
│   ├── tsconfig.json
│   ├── app/                      ← Next.js 14 App Router routes
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   ├── page.tsx              ← /
│   │   ├── login/, watchlist/, signals/, portfolio/,
│   │   ├── tax/, tax/harvest/, journal/, chat/, calibration/,
│   │   ├── ops/sources/, ops/schedules/, ops/models/, settings/
│   ├── components/
│   │   ├── nav/                  ← Sidebar, mobile-nav, nav-items
│   │   ├── shared/               ← Kpi, RegimeBadge, FreshnessBadge, etc.
│   │   ├── dashboard/, portfolio/, signals/, journal/,
│   │   ├── tax/, chat/, calibration/, morning-brief/,
│   │   ├── agent/, charts/, settings/, ui/
│   ├── lib/                      ← api.ts, contracts.ts, utils.ts, auth.ts
│   └── public/
├── infra/
│   └── docker-compose.yml        ← The whole stack in one file
└── docs/
    ├── PROJECT_HANDOFF.md        ← This file
    ├── ARCHITECTURE.md           ← Deeper than section 3 above
    ├── FEATURES.md               ← 245-row feature inventory
    ├── INPUTS_NEEDED.md          ← What's blocking you
    ├── FRONTEND_DESIGN_PROMPT.md ← Reusable Stitch / v0.dev brief
    ├── HOW_TO_TEST_FRONTEND.md   ← 3 paths to run it
    ├── STITCH_INTEGRATION_REPORT.md
    ├── SESSION_LOG_2026-05-29.md, SESSION_LOG_2026-05-30.md
    ├── LLM_ROUTING.md, TAX_REFERENCE.md, GLOSSARY.md,
    ├── BACKUP.md, SECURITY.md, ONBOARDING.md, SCHEDULED_TASKS.md
    ├── CONTRACTS.md              ← All Pydantic schemas
    ├── runbooks/                 ← 14 incident runbooks
    └── checklists/
```

---

## 5. Feature implementation — how each major piece works

### 5.1 Data ingestion (M1)

Every adapter lives in `backend/pfip/ingest/<source>/`. They share:

- A single async `fetch_*` function that returns parsed rows.
- A schema-validation step via `pandera` before insert.
- A call to `pfip.ingest._common.source_health.record_run(source,
  rows, error=...)` on every batch — this populates the
  `source_health` table that the freshness dots + watchdog read.
- An idempotency key via `pfip.ingest._common.idempotency.make_batch_key`
  — SHA-256 of `(source, symbol, start, end)`. Prevents double-writes
  on retry.

Sources currently coded (adapter exists; flip from ⏳ to ✅ when first run):

| Source | Module |
|---|---|
| ccxt (Coinbase / Kraken / Bybit / OKX) | `ingest/crypto/` |
| yfinance + Stooq | `ingest/us/` |
| jugaad-data + NSE/BSE bhavcopy | `ingest/india/` |
| AMFI daily NAV CSV | `ingest/india_mf/` |
| SEC EDGAR (10-K/Q, 8-K) | `ingest/us_fundamentals/` |
| Frankfurter + RBI ref rates | `ingest/fx/` |
| FRED / DBnomics / World Bank / MOSPI | `ingest/macro/` |
| EIA commodities | `ingest/commodities/` |
| 10+ RSS feeds + GDELT | `ingest/news/` |
| arXiv q-fin | `ingest/news/` |
| Bluesky (atproto, no key) | `ingest/news/bluesky.py` |
| Polymarket / Kalshi | `ingest/prediction_markets/` |
| Mempool.space + Etherscan | `ingest/self_custody/` |

**How a typical flow runs:**

```
Prefect cron → ingest flow → adapter.fetch() → pandera validate
  → idempotency key check → upsert → source_health.record_run()
  → anomaly_scan (if daily) → reconcile (if applicable)
```

### 5.2 Features (M2)

`backend/pfip/features/technicals.py` — RSI / MACD / ATR / BB / returns
/ vol via the `ta` library, with a manual fallback path that activates
when `ta` isn't installed. RSI is patched to saturate at 100/0 on
pure-trend bars (the textbook behaviour; `ta` returns NaN otherwise).

`features/fundamentals_ratios.py` — P/E, P/B, D/E, current ratio, ROE,
ROIC, FCF yield, dividend yield. None-safe on missing/zero inputs.

`features/derivatives.py` — funding rate, OI, long/short ratio,
funding z-score, squeeze-setup label. ccxt-based, no key needed for
crypto.

`signals/universe.py` — survivorship-bias-aware universe selection.
`as_of_universe(rows, target_date)` returns the date-correct symbol
set (delisted-after-target retained, delisted-before-target dropped).

### 5.3 ML signal layer (M4)

`pfip/regime/hmm_detector.py` — `HMMRegimeDetector(n_states=3|4)`.
Uses `hmmlearn`'s Gaussian HMM when available, falls back to a
quantile-band fit. After fit, maps states to {bull_trend, bear_trend,
sideways, high_volatility} by mean + std.

`pfip/signals/lgbm_baseline.py` — single-model trainer. `make_label`
computes a forward-looking binary up/down label at horizon H.

`pfip/prefect/flows/train_lgbm_per_regime.py` — per-regime trainer
flow. For each `(symbol, regime, horizon)` slot, slices data + fits
LGBM + persists to the file-backed registry. Runs Saturday 03:00 UTC.

`pfip/signals/auto_selector.py` — regime → model heuristic per plan §7.2.
Hand-coded mapping (bull_trend → lgbm_trend_specialist, sideways →
xgb_meanrev + ttm_short, etc.) until 12 months of labels exist for the
trained selector.

`pfip/signals/explain.py` — per-prediction SHAP explanations. Tries
real SHAP (lazy import), falls back to permutation importance against
a background dataset. JSONB-ready serialization for the `signals.drivers`
column.

`pfip/signals/registry.py` — file-backed model registry. SHA-256
deduped uploads. `pin_model(id, slot)` marks an entry as the active
artifact for a `(task, regime, horizon)` slot.

`pfip/signals/news_attach.py` — for each signal, return top-5
supporting + top-3 opposing news. Ranks by `(impact, |sentiment|,
recency)`. BUY support = positive sentiment; SELL = negative; HOLD =
neutral (|s| ≤ 0.2).

### 5.4 Backtesting (M5)

`pfip/backtest/walk_forward.py` — 3-year window / 21-day step
walk-forward.

`pfip/backtest/cpcv.py` — Combinatorial Purged Cross-Validation with
5-day embargo (López de Prado).

`pfip/backtest/monte_carlo.py` — 1000-iteration block bootstrap.

`pfip/backtest/benchmarks.py` — buy-hold / MA 50-200 / RSI mean-rev.

`pfip/backtest/tearsheet.py` — QuantStats-style HTML report. Uses
`quantstats` when installed, falls back to a built-in template.
`monthly_returns_table()` pivots a daily-return series into the
year×month×YTD grid. `drawdown_series()` returns the underwater curve.

`pfip/backtest/vectorbt_engine.py` — `_sharpe / _sortino / _calmar /
_max_drawdown / _cagr / _hit_rate` — the pure-math primitives used by
the tearsheet.

`pfip/prefect/flows/backtest_walk_forward.py` — wired to Prefect.
Saturday 02:00 UTC.

### 5.5 Knowledge base + RAG (M6)

`pfip/kb/ingest.py` — PDF/EPUB ingestion. SHA-256 deduped. Chunks
via LangChain text splitter.

`pfip/kb/news_embed.py` — embeds news articles into the `news` Qdrant
collection.

`pfip/kb/search.py` — `search(query, k)` over `kb` collection;
`search_news(query, k)` over `news` collection. Min cosine 0.60 (KB) /
0.55 (news) — tighter on books because long-form noise is real.

`pfip/kb/book_to_rules.py` — extracts trading rules from book passages.
Heuristic patterns (`If X then Y`, `Never X`, `Always X`) + optional
LLM path with graceful fallback.

`pfip/kb/eval_qa.json` — 50 hand-built Q&A pairs covering Wyckoff,
Lefèvre, Graham, Taleb, Dalio, Tharp, Ammous, López de Prado, and
Indian tax law.

`pfip/kb/ragas_eval.py` — monthly RAGAS eval driver. Scores
`faithfulness + answer_relevancy + context_precision`, logs to MLflow.
Falls back gracefully if the `ragas` lib isn't installed.

`pfip/prefect/flows/ragas_eval_monthly.py` — Monthly first Saturday
10:00 IST. Fires Telegram WARN if faithfulness < 0.70 or drops > 0.10.

### 5.6 Chat agent (M7)

`pfip/agent/llm_client.py` — `MultiProviderClient` over LiteLLM.
Routes by `(TaskType, Sensitivity)`:
- `Sensitivity.PUBLIC` → cloud (Groq → Gemini → DeepSeek → OpenRouter)
- `Sensitivity.SENSITIVE` → cloud OR local based on `TaskType`
- `Sensitivity.PERSONAL` → **always local Ollama**. Holdings/tax never
  leave the machine.

Legacy `LLMRouter` shim preserves `router.generate(prompt)` /
`router.stream_chat(messages)` / `router.embed(text)` for older code.

`pfip/agent/intent.py` — heuristic intent classifier. Three buckets:
`DB_QUERY`, `RAG_LOOKUP`, `REASONING`. Pattern-matcher; no LLM call
per turn (latency reasons). Priority on tie: DB > RAG > REASONING.

`pfip/agent/tools.py` — tool registry for the DB_QUERY path.
`get_holdings`, `get_current_price`, `get_recent_pnl`, `get_open_signals`,
`get_tax_summary`. Each safe-fails to `{ok: false, error: ...}`.

`pfip/agent/graph.py` — LangGraph orchestration. Nodes: classify
intent → route → (tool-call | retrieve | reason) → cite → stream.
**Privacy hardening (2026-06-04):** feeds the user's open-holding symbols
into the privacy classifier and **structurally forces `SENSITIVE`**
whenever any holding row was retrieved into the prompt — so holdings
never route to a cloud LLM even on a classifier miss. Streaming uses the
sensitivity-routing `MultiProviderClient.stream`.

`pfip/agent/morning_brief.py` — 07:00 IST morning brief composer.
Pulls overnight moves, calendar, news, regime, watchlist deltas, risk,
calibration note, shadow vs actual. Posts to Telegram + dashboard.

`pfip/agent/market_close.py` — weekday 17:30 IST close summary.
Index moves, watchlist movers, closed trades, risk breaches, signal
counts, top news. Idempotent + side-effect-free.

`pfip/agent/weekly_review.py` — Sunday 19:00 IST. Trailing 7 days of
closed trades + top failure patterns + regime changes + Monday-prep
checklist.

`pfip/agent/post_mortem.py` — auto-draft post-mortem for a closed
trade. Used by `POST /agent/post-mortem` (the older holding-keyed
entry) and `POST /journal/entries/{id}/auto_draft_post_mortem` (the
newer journal-keyed entry — markdown output with 5-section format).

### 5.7 Portfolio + risk + tax (M8)

**Portfolio tracking:**
- `pfip/models/holdings.py` — `HoldingRow` across 6 asset classes.
- `pfip/portfolio/service.py` — `correlation_matrix()`,
  `portfolio_summary()`, `pnl_breakdown()`.
- `pfip/portfolio/marking.py` (**new 2026-06-04**) — currency resolution
  + mark-to-market valuation + return series. `/portfolio/summary`,
  `/exposure`, `/concentration` value holdings at the latest OHLCV close
  per symbol, converting USD→INR via the `fx_rates` table.
  Correctness-by-abstention: a holding whose currency can't be resolved,
  or a USD holding with no FX rate, falls back to cost basis (never a
  wrong rupee figure). `GET /portfolio/marking` exposes coverage
  (`marked` / `unmarked:[{symbol,reason}]`, reasons `no_price` /
  `unknown_currency` / `no_fx_rate`). `/portfolio/correlations` returns a
  **real** Pearson matrix of daily log-returns from each symbol's own
  OHLCV history (`{ window_days, symbols, matrix, note, disclaimer }`).
  Tests in `tests/test_marking.py`.
- 10 broker CSV adapters in `pfip/brokers/csv_adapters/` —
  Zerodha, ICICIdirect, Groww, INDmoney, Vested, WazirX, CoinDCX,
  Binance, Coinbase, Kraken.

**Risk:**
- `pfip/portfolio/risk_manager.py` — position-cap (10%), drawdown halt
  (20%), correlation guard (>0.7), daily new-positions cap (2),
  Van Tharp R-size calculator.
- `pfip/portfolio/var.py` — historical VaR 95% / 99% + Sharpe (30d).
- `pfip/portfolio/precommitment.py` — Stage 7 ladder. `LadderTier` enum
  (PAPER / 5% / 10% / 25% / FULL). `enforce_ladder()` refuses orders
  above the tier cap. `can_advance_tier()` runs the four progression
  checks (4 weeks in tier, zero breaches, Sharpe floor, no consecutive
  losing months).

**Tax (Indian):**
- `pfip/tax/engine.py` — capital-gains classifier (FIFO),
  `compute_stcg / ltcg / vda_tax / schedule_fa / form_67 /
  dividend_tax / 80c_optimizer / surcharge_cliff_check`.
- `pfip/tax/indian_rules.py` — 31-Jan-2018 grandfathering, VDA 30%+1% TDS,
  slab rates, surcharge brackets, disclaimer.
- `pfip/tax/fx_cost_basis.py` — RBI rate lookup with Frankfurter
  fallback and a 7-day business-day step-back.
- `pfip/tax/harvest.py` — loss-harvesting suggestions. **Critical bug
  fixed 2026-05-30** in the LTCG branch: was subtracting ₹1L exemption
  from harvested loss instead of taxable pool. Correct formula is
  `delta = taxable_before − taxable_after`. Test pins it.
- `pfip/tax/forms.py` — Schedule CG JSON, Schedule FA JSON, Form 67
  JSON, summary PDF via reportlab.

### 5.8 Alerts (M9)

`pfip/alerts/dispatcher.py`:

- `AlertKind` enum (12 kinds: MORNING_BRIEF, REGIME_CHANGE, SIGNAL_FIRED,
  RISK_BREACH, DRAWDOWN_HALT, INGEST_FAILURE, CALIBRATION_BREACH,
  PAPER_TRADE_REPORT, POST_MORTEM_REQUIRED, SYSTEM_HEALTH,
  WEEKLY_REVIEW, CUSTOM).
- `AlertSeverity` enum (INFO / WARN / CRITICAL).
- Quiet hours 23:00–07:00 IST. CRITICAL bypasses.
- Rate cap 10/hour via Redis sliding window.
- Digest mode for INFO.
- Kill switch flag `alerts:silenced=1`.
- `escalate_unacked_warns()` promotes unacked WARNs to CRITICAL after
  2 hours. `ack_alert(id)` clears pending.

`pfip/alerts/templates/*.md` — markdown per kind with `{key}`
substitutions.

`pfip/prefect/flows/escalate_unacked.py` — runs every 30 minutes.

### 5.9 Operations layer

`pfip/api/health.py` — `/health` (shallow), `/health/deep` (probes
backing services, **split 2026-06-04** into CORE = TimescaleDB + Redis
and OPTIONAL = Qdrant + Ollama + cloud LLM; returns `status`
`ok`/`degraded`/`down` + a `ready` boolean — Ollama-down on a local run
is `degraded`, not `down`), `/health/sources` (per-adapter freshness
with summary counts).

`pfip/api/schedules.py` — `/schedules` lists every Prefect deployment
with cron + last run + age. Returns empty + error string when Prefect
unreachable (no 500).

`pfip/api/model_registry.py` — `GET /models?task=&regime=&horizon=`,
`GET /models/{id}`, `POST /models/upload`, `POST /models/{id}/pin`,
`GET /models/pinned`.

`pfip/api/setup.py` — `/setup/status` (onboarding state + needs_setup
boolean), `/setup/bootstrap` (seeds watchlist + runs free ingests),
`/setup/demo` (synthetic seed), `DELETE /setup/demo` (clear demo).

`pfip/prefect/flows/skipped_task_alerter.py` — hourly watchdog. Per-
deployment staleness budgets in `_BUDGET_HOURS` map. Telegram WARN on
overdue.

`pfip/prefect/flows/anomaly_scan_daily.py` — IsolationForest per symbol
over `(log_return, range_pct, gap_pct, volume_z)`. Writes JSONL to
`data/anomaly_log/<date>.jsonl`. Telegram WARN if anomaly ratio > 1%.

`pfip/prefect/flows/reconcile_daily.py` — cross-source price
reconciliation. Flags pairs diverging > 0.5%. Telegram WARN.

---

## 6. Frontend pages — what each does

| Route | Purpose | Notable widgets |
|---|---|---|
| `/login` | Single-user credentials login | NextAuth credentials provider |
| `/` (dashboard) | 30-second-scan home | KPI strip with freshness dots, BTC chart, regime stack, watchlist movers, risk snapshot, what-changed feed, top news, recent journal |
| `/watchlist` | Watched symbols by market | Market-scope chip strip (Crypto/US/India/FX/Other), groups, add/remove dialog |
| `/signals` | Latest signals | Filters (regime/confidence/asset/direction), Cards ↔ Table toggle, ConfidenceBar, SHAP drivers expander, news drawer |
| `/portfolio` | Holdings + risk + correlations | Exposure donut, correlation matrix heatmap, VaR panel, **Macro Shock Sensitivity card (new)** |
| `/tax` | FY tax summary | STCG/LTCG/VDA breakdown, Schedule FA, Form 67, 80C optimizer, regime comparison, ITR export, CSV import wizard |
| `/tax/harvest` | **New** Loss harvesting | Inputs grid, summary tiles (lots / harvestable / saved), ranked suggestions table with FY-end warning chips, disclaimer card |
| `/chat` | Agent SSE chat | Thread list, citation footer, privacy badge (PUBLIC/PERSONAL routing) |
| `/journal` | Pre-trade checklist + post-mortems | New entry → 10-item Appendix B modal. Close trade → post-mortem dialog with Auto-draft button |
| `/calibration` | Reliability diagrams + ECE | Per-model card with Brier / ECE / 0.15 suspension threshold |
| `/ops/sources` | **Promoted** Source health | 4 KPI tiles + table + last-errors drawer, 60s auto-refresh |
| `/ops/schedules` | **New** Prefect deployments | Cron column, last run, age, status pill (On time/Overdue/Never run) |
| `/ops/models` | **New** Model registry | Filters (task/regime/horizon), pin button, SHA + version + metrics |
| `/settings` | Risk limits, alerts, schedules | Forms + embedded Source Health panel |

**Cross-cutting components:**

- `components/nav/sidebar.tsx` — 8-section grouped nav ("PFIP Terminal
  · INSTITUTIONAL GRADE" brand).
- `components/nav/mobile-nav.tsx` — bottom tab bar for mobile.
- `components/shared/kpi.tsx` — `<Kpi>` with `freshness` prop (green/
  amber/red dot inline).
- `components/shared/freshness-badge.tsx` — drop-in dot+tooltip for any
  card that depends on a known adapter.
- `components/shared/regime-badge.tsx` — `<RegimeBadge regime size />`.
- `components/shared/welcome-modal.tsx` — first-run picker (bootstrap
  real data / seed demo / dismiss).
- `components/shared/page-header.tsx` — sticky header with title +
  description + actions.
- `components/portfolio/macro-shock-card.tsx` — **new** stress-scenario
  bars with empty state until backend stress endpoint ships.
- `components/settings/source-health-panel.tsx` — reused on
  `/ops/sources` and `/settings`.

---

## 7. Design system

**Palette** — Slate & Teal Institutional, from Google Stitch's
`DESIGN.md`. Ported into `frontend/app/globals.css` + `tailwind.config.ts`:

- Light: background `#f8f9ff`, primary teal `#006b5f`, text
  `#0b1c30`, borders `#bbcac6`.
- Dark: background slate-900 `#0f172a`, primary teal-500 `#14b8a6`.

**Type**:

- **Inter** 13–14px UI, 600 weight headings.
- **JetBrains Mono** for every numeric (prices, percents, dates).
- Tabular nums via `font-feature-settings: "tnum"`.
- **Material Symbols Outlined** loaded for Stitch HTML compatibility,
  but authored components use **Lucide React**.

**Stitch tokens** carried into Tailwind so raw Stitch HTML drops in
unchanged: `bg-surface`, `text-on-surface`, `text-positive`,
`bg-surface-container-lowest`, etc.

**Stitch utility classes** in globals.css: `.freshness-dot`,
`.candlestick`, `.sidebar-item-active`, `.material-symbols-outlined`.

**Inspirations baked in:**

- Sidebar / shortcuts / palette: **Linear**.
- Mono numerics + minimal financial: **Mercury**.
- Chart depth: **TradingView**.
- KPI cards + sparklines: **Vercel Dashboard**.
- Connection-status pattern: **Plaid Dashboard**.
- Alert timeline: **Sentry**.

**Deliberately NOT used**: Robinhood (consumer-y), Coinbase Pro
(cluttered), trader-neon greens/reds.

---

## 8. Testing

Backend: **`pytest`**. 41 test files, 451 passing, 1 skipped
(LightGBM unavailable in test env), 0 failed.

```powershell
cd backend
PYTHONPATH=. python -m pytest tests/ -p no:warnings
```

Key test files added recently:
- `test_journal_auto_draft.py` — 10 tests on post-mortem auto-draft.
- `test_tax_harvest.py` — 11 tests; this file found the LTCG bug.
- `test_alerts_dispatcher.py` — 22 tests on quiet hours, templates,
  severity invariants.
- `test_precommitment.py` — 11 tests on ladder enum / template round-trip.
- `test_fx_cost_basis.py` — 8 tests on FX rate lookup + fallback chain.
- `test_signals_explain.py` — 7 tests on SHAP/permutation explanations.
- `test_regime_hmm.py` — 8 tests on HMM state→regime labeling.
- `test_model_registry.py` — 11 tests on upload/pin/load round-trip.
- `test_reconcile.py` — 7 tests on cross-source divergence detection.
- `test_universe_idempotency_news_pure.py` — 16 tests on survivorship,
  idempotency keys, URL normalization.
- `test_tearsheet.py` — 13 tests on Sharpe/Sortino/Calmar/monthly grid.
- `test_book_to_rules.py` — 12 tests on rule extraction.
- `test_train_lgbm_per_regime.py` — 9 tests on label/slice.

Frontend: **no JS unit tests yet** (suggested next item: Vitest setup).
Type-checked via `tsc --noEmit`. 0 real type errors as of 2026-05-30.

---

## 9. How to run it locally (deployment)

The whole stack is in `infra/docker-compose.yml`. See
`docs/HOW_TO_TEST_FRONTEND.md` for three paths in detail.

**TL;DR:**

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app
# After pulling new code, install frontend deps (2026-06-04 Next bump + new middleware/schemas):
cd frontend; pnpm install; cd ..
docker compose -f infra\docker-compose.yml --env-file .env up -d
```

> **2026-06-04 audit note.** `NEXTAUTH_SECRET` and `POSTGRES_PASSWORD`
> are now **mandatory** — compose uses `${VAR:?}` and aborts at startup
> if either is unset (no insecure dev defaults remain). Every host port
> binds to `127.0.0.1` (loopback), so nothing is reachable from the LAN.

Then **http://localhost:3000** (loopback only), log in with `.env` credentials, click
**Seed demo data** in the welcome modal to populate everything with
synthetic data instantly.

After first up, register all the Prefect cron jobs:

```powershell
docker exec pfip-backend python -m pfip.prefect.deploy
```

That registers ~15 scheduled flows.

---

## 10. Current state — what's shipped and what isn't

Live tally (from `docs/FEATURES.md`):

- **190 ✅ shipped** — see `FEATURES.md` for the full list grouped
  by module.
- **14 🟡 partial** — partially built; usually means "logic exists but
  not wired to UI" or "code path exists but only works on certain inputs".
- **31 ⏳ pending** — all 31 fall into one of four buckets, all listed
  in `docs/INPUTS_NEEDED.md`:
  - **A.** API keys (NVIDIA NIM, Gemini, DeepSeek, OpenRouter, Cohere,
    LangSmith, Neynar, Finnhub, Polygon).
  - **B.** Telegram credentials (bot token, chat ID; optional Telethon
    api_id/hash).
  - **C.** Self-custody crypto addresses (BTC + ETH).
  - **D.** One-time files (`itr_filed/<FY>.json`, broker CSVs, KB books,
    signed pre-commitment).
  - **E.** First docker-compose up + click Bootstrap (this alone flips
    ~25 ⏳ rows).
  - **F.** Server-level admin (LUKS, UFW, fail2ban — your call).
  - **G.** Accumulated runtime (trained selector at 12mo of labels;
    failure-pattern clustering at 50 closed entries).
- **5 🚫 deliberate non-goals** — Reddit (skipped), Telegram public
  channels (needs dedicated SIM), self-custody SOL (you don't have),
  others.

---

## 11. Reading guide — where to look for X

| If you want to know about… | Read… |
|---|---|
| The full feature inventory | `docs/FEATURES.md` (245 rows) |
| What changed (newest first) | `docs/CHANGELOG.md` |
| What's blocking further progress | `docs/INPUTS_NEEDED.md` |
| The architecture deeper | `docs/ARCHITECTURE.md` |
| How the LLM router routes | `docs/LLM_ROUTING.md` |
| Indian tax rules baked in | `docs/TAX_REFERENCE.md` |
| The Pydantic schemas | `docs/CONTRACTS.md` |
| The backup strategy | `docs/BACKUP.md` |
| Security posture | `docs/SECURITY.md` |
| Glossary of trading terms | `docs/GLOSSARY.md` |
| The full set of cron jobs | `docs/SCHEDULED_TASKS.md` |
| First-run setup | `docs/ONBOARDING.md` |
| **How to run the frontend** | `docs/HOW_TO_TEST_FRONTEND.md` |
| **How to brief Stitch/v0.dev for more pages** | `docs/FRONTEND_DESIGN_PROMPT.md` |
| **What's in the Stitch deliverable** | `docs/STITCH_INTEGRATION_REPORT.md` |
| **What landed in recent sessions** | `docs/SESSION_LOG_2026-05-29.md`, `SESSION_LOG_2026-05-30.md` |
| Failure runbooks | `docs/runbooks/*.md` (14 of them) |

---

## 12. Decisions log (the controversial ones)

These are the choices that took more than 5 minutes to make. Documenting
so future-you doesn't re-debate them.

1. **Slate & Teal palette (not pure dark/Bloomberg)** — Stitch
   recommended it; matches "modern institutional" aesthetic without
   being neon-trader or consumer-y.
2. **Material Symbols loaded but Lucide is the authored icon set** —
   tree-shaking + consistent stroke weights. Stitch HTML works either
   way.
3. **Notion as the cross-session tracker** — your Anthropic subscription
   moves between accounts; Notion persists across them. Tracker lives at
   <https://www.notion.so/35467c8c010a8157b662f72cf81ee9f7>.
4. **Local Ollama for PERSONAL sensitivity, not "best model"** —
   privacy boundary is more important than latency for tax queries.
5. **JSONL anomaly log, not a DB table** — append-only audit data;
   tail-greppable; no migration on day 1.
6. **File-backed model registry, not MLflow as primary** — registry is
   tiny + filesystem-deduped via SHA-256; MLflow tracks experiments,
   not artifacts. Two specialised stores beat one bloated one.
7. **Heuristic intent classifier, not LLM-per-turn** — latency,
   determinism, and the rules are short. LLM call has a 200ms minimum;
   regex is sub-ms.
8. **Loss harvesting LTCG fix (₹1L exemption)** — the engine had a
   real bug where it subtracted the exemption from the harvested loss
   instead of the taxable pool. Found by writing tests. Fixed.
9. **Welcome modal first-run flow with three options** — bootstrap
   real data / seed demo / dismiss. Solves the blank-dashboard problem
   that kills demo enthusiasm on first load.
10. **RAG eval (RAGAS) runs monthly, not per-PR** — eval is expensive
    + KB doesn't change often. Telegram WARN on regression > 0.10 or
    faithfulness < 0.70.

---

## 13. How to pick this up in a new chat

Copy this exact paragraph into the new chat:

> I'm continuing work on PFIP — Personal Financial Intelligence
> Platform, a single-user self-hosted financial intelligence platform
> for crypto + US equities + Indian equities + MFs + bonds + crypto
> self-custody. v1 is paper-trading only. Project lives at
> `C:\Users\gaura\OneDrive\Desktop\PFIP_app\` on my Windows machine.
> The full project handoff is in `docs/PROJECT_HANDOFF.md` — please
> read that first. Current state: 190 features shipped, 14 partial,
> 31 pending. 451 backend tests passing. Frontend uses the Slate &
> Teal palette from Google Stitch. The full feature inventory is in
> `docs/FEATURES.md` and what's blocking progress is in
> `docs/INPUTS_NEEDED.md`.

Then describe what you want to do next. The new chat will need to:

1. Read `docs/PROJECT_HANDOFF.md` (this file).
2. Read `docs/FEATURES.md` for the latest tally + per-feature status.
3. Read `docs/INPUTS_NEEDED.md` to know what's blocked on you.
4. Read the relevant session log (`SESSION_LOG_*.md`) for the most
   recent context.

That's enough to get a new agent productive in under 60 seconds of
reading.

---

## 14. Things I'd build next (without your input)

In priority order, if you give me another autonomous session:

1. **Frontend Vitest setup + smoke tests on every API hook.** Closes
   the trust gap on the JS side. ~2 hours.
2. **Calibration page redesign** with per-regime ECE breakdown. The
   logic is there; the UI is dated. ~2 hours.
3. **`/digest` page** — web preview of the morning brief / weekly
   review / market close. Currently only delivered via Telegram; the
   web preview is useful when quiet hours suppress. ~1 hour.
4. **`/backtest` results browser** — list past walk-forward runs from
   MLflow with quick comparison view. ~3 hours.
5. **Champion / challenger UI on `/ops/models`** — promote a model
   slot from shadow to champion with a one-click confirm dialog +
   audit log. ~2 hours.
6. **Per-page **freshness badge wiring** — every card that pulls from
   a known adapter should show its freshness dot. Most cards already
   have one via `<Kpi freshness>`; the chart cards don't yet. ~1 hour.
7. **`/journal` wizard mode** — the 10-item checklist is a wall of
   checkboxes today; a wizard with progress feels less intimidating
   and prevents the "click-all-true-to-bypass" pattern. ~2 hours.
8. **PowerShell setup script** — `scripts/setup.ps1` that walks a
   first-run user through `.env` creation, bcrypt-hashing the
   password, picking ports, and starting compose. ~1 hour.

Each of these is bounded, testable, and doesn't need anything from you.
Pick one or pick all when you're back.

---

## 15. Single line you can show anyone

PFIP is a self-hosted Bloomberg-Terminal-equivalent for one engineer
managing their own money across crypto + US equities + Indian equities +
mutual funds + bonds + self-custody, with an honest agent that cites
its sources and a binding self-contract that gates real-capital
deployment.

That's the elevator pitch. Everything else in this document is
implementation detail.
