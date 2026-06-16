# PFIP Master Project Plan

> The end-to-end plan: what's built, what's left, in phases, with realistic timelines. Decisions
> here are grounded in two validated OSS/research reports (2026-06-16). Pairs with
> `PROJECT_TRACKER.md` (live status board) and `CAPABILITIES.md` (what each feature does).
> Notion-importable (clean headings/tables/checkboxes).

**Last updated:** 2026-06-16
**Horizon:** ~16–22 weeks part-time to a trustworthy, end-to-end advisory platform (MVP-usable
much sooner — see Phase 4). Estimates assume part-time work + autonomous build sessions + free-tier
compute (CPU-only; Colab for occasional GPU).

---

## 0. Executive summary

PFIP is **code-feature-complete for v0.5** but **operationally partial**: ~321 code files, 18
frontend pages, 43 ingest modules, full backtest/tax/agent engines — yet only 8/23 symbols have
live data and the ML signal layer is intentionally off. The work ahead is **not "build the
platform"** — it's **populate the data, stand up an honest scoring harness, then let researched
models/signals in one at a time, keeping only what beats a baseline after costs.**

**Three decisions locked in by research (validated against sources):**
1. **Models predict risk/volatility, not price.** TSFMs (esp. IBM TinyTimeMixer) feed the regime
   layer; they are not alpha engines. (Unanimous across 3 sources.)
2. **Signals are time-series, not cross-sectional.** Our 13–30 symbol universe is far too small for
   value/momentum/quality factor portfolios — use per-asset slow-trend / carry / vol-regime instead.
3. **Data has zero paid dependencies.** Every market has a free primary + fallback; the only key
   worth getting is the (genuinely free) Tiingo key.

---

## 1. Where we are (implemented & verified)

### ✅ Built and working
- **Cloud pipeline** — Neon Postgres + GitHub Actions (daily ingest 2×/day, weekly, manual backfill),
  `PFIP_PIPELINE_MODE` for headless auth. CI green (5 jobs).
- **Ingestion** — 43 modules, non-fatal per-source. Verified live: crypto (BTC/ETH/SOL, 1,200–1,406
  bars), India NSE (5 names, ~820 bars). 
- **Features** — 7 canonical technicals computing for all live symbols (7,885 rows).
- **Regime** — HMM 4-state, labels all 8 live symbols.
- **Portfolio/tax** — real mark-to-market, correlations, drawdown, VaR, risk manager, Indian tax
  engine, 10 broker CSV adapters.
- **Backtest engine** — vectorbt walk-forward, Monte Carlo, tearsheets (built, not yet exercised).
- **Agent** — LangGraph chat (SSE), morning brief / post-mortem / weekly / arXiv, privacy-gated.
- **Frontend** — 18 Next.js pages, auth/CSP hardened.
- **Docs** — architecture, contracts, 15+ runbooks, tracker, capabilities.

### ⚠️ Known gaps (today's verified state)
- US equities = 0 rows (no Tiingo key). FX = 0 (frankfurter timeout). India MFs + BNB/XRP not
  backfilled. Extras only on latest bar. MLflow not persisting in cloud. ML signals gated off.
  Precommitment Sharpe-gate is a no-op. KB empty.

---

## 2. Phased plan

> Effort key: **S** = ½–1 session · **M** = 1–2 sessions · **L** = 3–5 sessions.
> A "session" ≈ a focused autonomous build+review cycle. Calendar = part-time weeks.

### Phase 0 — Data hardening  ·  *~1 week*  ·  🔄 in progress
**Goal:** Full watchlist ingesting daily; the data is trustworthy before any modeling.
| Task | Effort | Owner |
|---|---|---|
| Free **Tiingo key** → GitHub secret → US equities populate | S | 👤 you (2 min) + auto |
| Fix **FX frankfurter timeout** (bump/await + fallback source) | S | code |
| Fix **MLflow cloud persistence** (`setuptools`, writable artifact path) | S | code |
| Wire **India MFs (MFAPI.in) + BNB/XRP** into backfill | M | code |
| **Backfill historical extras** (fundamentals/macro on history, not just latest bar) | M | code |
| Re-run backfill → verify full universe + extras coverage | S | auto |
**Exit gate:** ≥20/23 symbols with ≥2y history; extras present on historical rows; MLflow saving.

### Phase 1 — Scoring harness + baselines  ·  *~1.5 weeks*  ·  ⏳
**Goal:** The honest rig that decides what's worth keeping. Highest-leverage, lowest-risk work.
| Task | Effort | Notes |
|---|---|---|
| `pandera` schemas on OHLCV/features/regime in ETL | S | data validation gate |
| `arch` **GARCH** volatility baseline | S | the bar every vol model must beat |
| `statsmodels` **Markov-switching** baseline | S | regime baseline |
| **Walk-forward + embargo harness** (reimplement simple purged CV; avoid copyleft mlfinlab) | M | the core rig |
| `vectorbt` + `QuantStats` + `empyrical-reloaded` wired as the **net-Sharpe-after-costs** scorer | M | acceptance gate |
**Exit gate:** Any signal/model can be scored end-to-end on real data with after-cost metrics.

### Phase 2 — Regime upgrade  ·  *~1 week*  ·  ⏳
**Goal:** More robust regimes than the lone HMM; keep definitions simple & frozen (anti-overfit).
| Task | Effort |
|---|---|
| `ruptures` change-point detection alongside HMM | S |
| Markov-switching filtered-probability regime feature | S |
| Consolidate to a simple 3-state (low/mid/high-vol) definition, frozen | S |
**Exit gate:** Regime labels from ≥2 methods agree and persist; no continuous threshold-tuning.

### Phase 3 — Risk/volatility models (TTM)  ·  *~1.5 weeks*  ·  ⏳
**Goal:** Add the one researched model with real evidence — as a risk-feature generator.
| Task | Effort |
|---|---|
| Integrate **IBM TinyTimeMixer** (CPU, Apache) → forecast realized vol per symbol | M |
| Bake-off: TTM vs GARCH vs naive vs (benchmark) Chronos-Bolt-Tiny, scored via Phase-1 harness | M |
| Keep TTM vol forecast as a feature only if it beats GARCH after costs | S |
**Exit gate:** A documented winner for vol forecasting; loser models discarded with evidence.

### Phase 4 — Signals layer (MVP value)  ·  *~2 weeks*  ·  ⏳
**Goal:** First real, advisory signals — time-series, not cross-sectional.
| Task | Effort |
|---|---|
| Implement **slow trend (1–12mo), carry, vol-regime filter** signals (`vectorbt` indicators) | M |
| Crypto overlays: **funding-rate / MVRV as regime/overheat filters** (not alpha) | S |
| Walk-forward validate each; keep only after-cost Sharpe > 1 across sub-periods | M |
| Enable `FEATURE_ML_SIGNALS`; sanity-check first live signals + calibration | M |
| Surface signals + drivers on the existing `/signals` page | S |
**Exit gate:** Signals page shows validated, explainable, advisory signals on live data. **← first end-to-end usable product.**

### Phase 5 — Portfolio construction & risk  ·  *~1.5 weeks*  ·  ⏳
**Goal:** Turn signals into sane target weights with real risk controls.
| Task | Effort |
|---|---|
| `PyPortfolioOpt` **HRP / risk-parity / shrinkage** (avoid naive Markowitz) | M |
| **Fractional Kelly + volatility targeting** position sizing | S |
| Risk controls: drawdown de-risk, concentration/correlation caps, INR-base multi-currency | M |
| Fix the **precommitment Sharpe-floor gate** (currently a no-op) | S |
**Exit gate:** Given signals, system proposes risk-budgeted target weights; safety gates fire.

### Phase 6 — Backtest rigor & calibration  ·  *~1 week*  ·  ⏳
**Goal:** Prove it's not overfit before trusting it.
| Task | Effort |
|---|---|
| Full walk-forward / Monte-Carlo / shuffle on the signal+portfolio stack | M |
| Calibration (Brier/ECE) on signal confidence; wire `/calibration` page to real data | S |
| Lookahead/survivorship/PIT audit of the pipeline | S |
**Exit gate:** Tearsheet + calibration on real data; documented assumptions & costs.

### Phase 7 — Agent & knowledge base  ·  *~2 weeks*  ·  ⏳
**Goal:** The chat agent becomes genuinely useful over the live data.
| Task | Effort |
|---|---|
| Swap agent model to **Qwen3 / Llama 3.2** (not Phi-3); tool-use over SQL+RAG+backtest+explain | M |
| Guardrails (`guardrails-ai` output-shape, injection defense, privacy-local-only) | M |
| **RAGAS** eval set (30–50 personal Q&A) + regression tests | M |
| Seed **knowledge base** (your books) | S | 👤 you supply books |
| Wire chat-history sidebar (currently placeholder) | S |
**Exit gate:** Agent answers portfolio/signal questions with citations; RAGAS scores tracked.

### Phase 8 — News/sentiment upgrade  ·  *~1 week*  ·  ⏳
**Goal:** Standardize and sharpen sentiment.
| Task | Effort |
|---|---|
| **FinBERT vs DistilRoBERTa** A/B on our news; adopt faster if accuracy ties | M |
| **CryptoBERT** on crypto-tagged headlines (keep only if it beats FinBERT there) | S |
| Add **GDELT + Crypto Fear&Greed** as regime/sentiment features | S |
**Exit gate:** One sentiment head per domain, evaluated; sentiment features feed regimes.

### Phase 9 — Production hardening  ·  *~1 week*  ·  ⏳
**Goal:** Keep it healthy unattended.
| Task | Effort |
|---|---|
| `Evidently` drift/quality monitoring (monthly) | M |
| MLflow discipline (git hash + data tag + metrics on every run; model registry for candidates) | S |
| Source-health + data-quality dashboards wired to real metrics | S |
**Exit gate:** Drift reports + source health visible; bad data caught before it reaches models.

### Phase 10 — Personal-use ops  ·  *ongoing*  ·  ⏳
**Goal:** Day-to-day usefulness for real decisions.
| Task | Effort |
|---|---|
| Read-only **broker sync** (Zerodha Kite / Upstox) — advisory, never auto-execute | M | 👤 keys |
| Import **broker CSVs**, run tax engine against FY actuals (±2% gate) | M | 👤 exports |
| **Alerts** (Telegram/email) on signals/regime shifts/risk breaches | M | 👤 setup |

---

## 3. Timeline at a glance

| Phase | Theme | Calendar (part-time) | Cumulative |
|---|---|---|---|
| 0 | Data hardening | ~1 wk | 1 wk |
| 1 | Harness + baselines | ~1.5 wk | 2.5 wk |
| 2 | Regime upgrade | ~1 wk | 3.5 wk |
| 3 | Risk/vol models (TTM) | ~1.5 wk | 5 wk |
| 4 | **Signals (MVP usable)** | ~2 wk | **7 wk** |
| 5 | Portfolio & risk | ~1.5 wk | 8.5 wk |
| 6 | Backtest rigor | ~1 wk | 9.5 wk |
| 7 | Agent & KB | ~2 wk | 11.5 wk |
| 8 | Sentiment | ~1 wk | 12.5 wk |
| 9 | Hardening | ~1 wk | 13.5 wk |
| 10 | Personal ops | ongoing | ~16–22 wk to "complete" |

**Key milestones:** MVP end-to-end usable at **~Phase 4 (≈7 weeks)**; trustworthy backtested
advisory platform at **~Phase 6 (≈9.5 weeks)**; full personal-ops platform **~16–22 weeks**.
With heavier autonomous-session cadence these compress significantly.

---

## 4. Dependencies & sequencing rules

- **Phase 0 blocks everything** — no modeling on a half-empty DB.
- **Phase 1 (harness) blocks Phases 3–6** — without the scorer, model choices are guesses.
- Phases **7, 8, 9** can run in parallel with 4–6 (different subsystems).
- Phase **10** needs your keys/CSVs; start anytime after Phase 5.
- **Anti-overfit discipline throughout:** freeze regime defs, limit strategy count, require
  after-cost Sharpe stable across sub-periods — never tune on the test window.

---

## 5. What we deliberately are NOT doing (and why)

- ❌ Cross-sectional factor portfolios — universe too small (needs 100+ names).
- ❌ Raw price/return prediction with TSFMs — doesn't beat naive after costs.
- ❌ TimesFM-200M / Moirai (license) / FinRL-RL / Nautilus / Zipline — wrong fit for CPU + small data + personal scale.
- ❌ Paid data dependencies — every market has a free path.
- ❌ Auto-execution — advisory only; a human always confirms.
