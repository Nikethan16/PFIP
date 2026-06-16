# PFIP Project Tracker

> **The single at-a-glance board for where PFIP stands.** Status of every major area,
> what's left, and a realistic effort/ETA. Pairs with `docs/CAPABILITIES.md` (what each
> feature can actually do). For historical narrative see `BUILD_STATUS.md`; for the
> user-input punch list see `PLACEHOLDERS.md`.
>
> **Import to Notion:** drag this file into a Notion page (it has native Markdown import) —
> headings become toggles, tables become tables, `- [ ]` become checkboxes.

**Last updated:** 2026-06-16
**Overall state:** Platform code is ~feature-complete for v0.5 (321 code files, 70 test files,
18 frontend pages, 43 ingest modules). The gap is **operational, not architectural** — data
coverage is partial and the ML signal layer is intentionally off until enough history exists.

---

## Status legend

| Symbol | Meaning |
|---|---|
| ✅ | Done & verified working |
| 🟢 | Done in code, working but not fully exercised on real data |
| 🔄 | In progress |
| ⏳ | Planned / not started |
| ⚠️ | Broken or blocked — needs a fix |
| 🔒 | Intentionally gated off (by design, not a bug) |
| 👤 | Blocked on user input (a key, a file, a decision) |

---

## 1. Live system status (operational reality, 2026-06-16)

What is *actually flowing* in the cloud (Neon + GitHub Actions), from the verified backfill run.

| Market | Symbols seeded | Symbols with data | Bars/symbol | Status |
|---|---|---|---|---|
| Crypto | 5 (BTC, ETH, SOL, BNB, XRP) | **3** (BTC, ETH, SOL) | 1,200–1,406 | 🟢 BNB/XRP not yet backfilled |
| India equity (NSE) | 5 (RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK) | **5** | 815–841 | ✅ all live, regimes labeled |
| US equity | 5 (SPY, QQQ, AAPL, NVDA, MSFT) | **0** | — | ⚠️ no `TIINGO_API_KEY` → ingest no-op 👤 |
| FX | 3 (USD-INR, EUR-USD, GBP-USD) | **0** | — | ⚠️ frankfurter timed out >180s |
| India MF | 5 (AMFI schemes) | **0** | — | ⏳ not wired into backfill path |

**Totals:** 8 / 23 symbols live · 7,885 feature rows · 8 regimes labeled · 0 errors.

**Regime labels (latest run):** BTC bear (0.92) · ETH sideways (0.83) · SOL bear (0.90) ·
RELIANCE sideways (0.92) · TCS sideways (0.95) · HDFCBANK sideways (0.93) · **INFY bull (0.93)** ·
ICICIBANK sideways (0.95).

---

## 2. Milestones by area

### Data ingestion
| Item | Status | Notes | Effort left |
|---|---|---|---|
| Crypto OHLCV (ccxt) | ✅ | BTC/ETH/SOL backfilled 3y | — |
| India equity OHLCV (jugaad) | ✅ | 5 names, `.NS` resolution fixed | — |
| US equity OHLCV | ⚠️👤 | Tiingo key missing; yfinance/Stooq fallbacks exist | 0.5 day after key |
| FX rates (frankfurter) | ⚠️ | Times out >180s in cloud — bump timeout / swap source | 0.5 day |
| India MF NAVs (AMFI) | ⏳ | Adapter exists, not in backfill path | 0.5 day |
| Fundamentals (Finnhub/SEC/Screener) | 🟢👤 | Code real; Finnhub key gives best US coverage | key only |
| News (RSS/GDELT/keyless) | 🟢 | Keyless sources work; keyed ones no-op without keys | — |
| On-chain / derivatives | 🟢👤 | Free tiers thin; Glassnode/Coinglass paid | optional |
| 43 ingest modules total | 🟢 | Non-fatal per-source; each no-ops without its key | — |

### Features
| Item | Status | Notes | Effort left |
|---|---|---|---|
| 7 canonical technicals | ✅ | RSI, MACD×3, ATR, return_7d, volatility_30d | — |
| Extras: fundamentals/on-chain/derivatives/macro/cross-asset | 🟢 | Computed, but **only stamped on the latest bar** | see gap #5 |
| Historical extras backfill | ⚠️ | Historical bars get empty extras → limits supervised ML | 1–2 days |

### Regime detection
| Item | Status | Notes | Effort left |
|---|---|---|---|
| HMM 4-state detector | ✅ | Labels all 8 live symbols, persists label | — |
| MLflow model persistence (cloud) | ⚠️ | Fails: `pkg_resources` missing + `/mlflow` not writable | 0.5 day |
| Convergence warnings (2 symbols) | 🟢 | RELIANCE/HDFCBANK soft warnings, still label | low pri |

### Signals / models
| Item | Status | Notes | Effort left |
|---|---|---|---|
| LightGBM baseline (walk-forward, calibrated) | 🔒 | Code complete, gated by `FEATURE_ML_SIGNALS=false` | enable when history ≥756 bars |
| Regime-router (model per state) | 🔒 | Built, gated with the above | — |
| OSS forecasting model bake-off (Chronos/TimesFM) | ⏳ | Pending research report → zero-shot test on our data | 2–3 days |
| Enable ML signals end-to-end | 🔒 | Needs more history + sanity-check of first signals | 1 day after data |

### Backtesting
| Item | Status | Notes | Effort left |
|---|---|---|---|
| vectorbt walk-forward engine | 🟢 | Embargo, CPCV folds, transaction costs | needs data to exercise |
| Monte Carlo / shuffle / tearsheet | 🟢 | Built; unexercised on real signals | — |

### Agent / RAG
| Item | Status | Notes | Effort left |
|---|---|---|---|
| LangGraph chat agent (SSE) | 🟢 | Intent→retrieve→synthesize→cite; privacy-gated | — |
| Morning brief / post-mortem / weekly / arXiv | 🟢 | Real DB-backed; LLM writes prose only | — |
| Knowledge base (books) | ⏳👤 | Ingester ready; **no books supplied** → cites news/DB only | user-supplied |
| Chat history sidebar | ⚠️ | Unwired placeholder | 0.5 day |

### Portfolio / tax
| Item | Status | Notes | Effort left |
|---|---|---|---|
| Mark-to-market + correlations + drawdown | ✅ | Real (since 2026-06-04) | — |
| Risk manager (pre-trade checks) | 🟢 | 10-item checklist, drawdown halt | — |
| Indian tax engine (advisory) | 🟢 | STCG/LTCG, VDA, Schedule FA approx | — |
| Broker CSV import (10 adapters) | 🟢👤 | Built; awaiting user exports | user-supplied |
| Precommitment Sharpe-floor gate | ⚠️ | **No-op** — safety control never fires | 1 day |

### Frontend
| Item | Status | Notes | Effort left |
|---|---|---|---|
| 18 Next.js pages | 🟢 | dashboard, portfolio, signals, chat, tax, etc. | — |
| Security (auth middleware, CSP, 14.2.35) | ✅ | Patched 2026-06-04 | — |
| Live-priced badge from `/portfolio/marking` | ⏳ | Optional UI polish | 0.5 day |

### Infra / pipeline
| Item | Status | Notes | Effort left |
|---|---|---|---|
| Cloud pipeline (Neon + GitHub Actions) | ✅ | Daily ingest + backfill live; `PFIP_PIPELINE_MODE` | — |
| CI (5 jobs) | ✅ | All green | — |
| Docker stack (local) | 🟢 | Full compose; not run in cloud | — |
| MLflow artifacts in cloud | ⚠️ | See regime persistence gap | 0.5 day |

### Documentation
| Item | Status | Notes |
|---|---|---|
| This tracker + CAPABILITIES.md | ✅ | New 2026-06-16 |
| ARCHITECTURE / CONTRACTS / runbooks (15+) | ✅ | Existing |

---

## 3. Known gaps & bugs (prioritized)

| # | Issue | Impact | Priority | Fix owner |
|---|---|---|---|---|
| 1 | US equities = 0 rows (no Tiingo key) | Biggest market empty; halves usable universe | **P0** | 👤 key → then auto |
| 2 | FX ingest times out >180s | No USD→INR; blocks US/crypto rupee MTM | **P0** | code |
| 3 | MLflow persistence fails in cloud | Regime/signal models not saved or versioned | **P1** | code |
| 4 | India MFs + BNB/XRP not backfilled | 7 watchlist symbols stay no-data | P1 | code |
| 5 | Extras only on latest bar | Supervised ML effectively sees 5 features, no history | P1 | code |
| 6 | Precommitment Sharpe-floor gate is a no-op | Safety gate silently never fires | P2 | code |
| 7 | Shadow `/vs-actual` thinner than CONTRACTS spec | No Sharpe/return comparison | P2 | code |
| 8 | Chat history sidebar unwired | Minor UX | P3 | code |
| 9 | Missing unit tests for portfolio service/risk/allocation | Load-bearing money code only covered indirectly | P2 | code |

---

## 4. Next-up queue (ordered)

1. **[P0] Get free Tiingo key** → add GitHub secret → re-run backfill (populates US). 👤 *2 min you + auto*
2. **[P0] Fix FX timeout** (bump frankfurter timeout / swap source). *code, 0.5 day*
3. **[P1] Fix MLflow cloud persistence** (`setuptools`/`pkg_resources`, writable artifact path). *code, 0.5 day*
4. **[P1] Wire India MFs + remaining crypto into backfill.** *code, 0.5 day*
5. **OSS model survey** (research report → paste back) → zero-shot bake-off on verified data. *2–3 days*
6. **[P1] Backfill historical extras** so supervised models have real feature history. *1–2 days*
7. **Enable ML signals** once history is sufficient + sanity-check. 🔒 *1 day*

---

## 5. Roadmap phases (rough timeline)

| Phase | Goal | Rough effort |
|---|---|---|
| **Phase 0 — Data hardening** *(now)* | Full universe ingesting daily; extras have history; MLflow persists | ~3–5 days |
| **Phase 1 — OSS model bake-off** | Test Chronos/TimesFM/FinBERT/backtest libs on our data; keep what beats baseline | ~1 week |
| **Phase 2 — Signals live** | Enable `FEATURE_ML_SIGNALS`, integrate winning models, walk-forward validated | ~1 week |
| **Phase 3 — Product polish** | Agent + UI consuming signals end-to-end; KB seeded; chat history | ~1 week |
| **Phase 4 — Personal-use ops** | Broker CSVs imported, tax run against actuals, alerts wired | ongoing |

*Estimates assume part-time work + the existing free-tier compute (CPU only, Colab for occasional GPU).*

---

## 6. How to keep this current

- Update the **Live system status** table after each backfill/major ingest run.
- Flip status symbols as items move ✅/⚠️/🔒; move done items out of *Next-up queue*.
- Add new bugs to **Known gaps** with a priority; delete when fixed (or move to CHANGELOG).
- Keep effort/ETA honest — this doc is only useful if it's trusted.
- When a feature ships, add its *capability* to `docs/CAPABILITIES.md`.
