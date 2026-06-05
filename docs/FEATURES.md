# PFIP Features — what each part of the system does

Concrete inventory of every feature, page, and capability. Not "why we built X" (that's `WHY_AND_WHAT.md`); not "where the LLM helps" (that's `LLM_ROUTING.md`); this is **what the system can actually do for you**.

If a feature isn't listed here, it isn't a feature yet — it's either NOT_DONE or out of scope.

Status legend: ✅ shipped · 🟡 partially built · ⏳ pending · 🚫 deliberate non-goal

---

## Section 1 — Module-by-module feature catalog

### M1 — Data ingestion

What the user does: defines a watchlist, optionally adds self-custody crypto addresses, optionally provides API keys.
What the system does: pulls data from ~50 free sources on the schedules in `WHY_AND_WHAT.md` §0b.

| Feature | Status | Notes |
|---|---|---|
| Crypto OHLCV (BTC/ETH/SOL/BNB) hourly via ccxt | 🟡 | Coinbase working; ETH/SOL/BNB pending broader run. Backups: Kraken, Bybit, OKX. |
| US equities EOD via yfinance + Stooq | ⏳ | Adapters coded; not yet run. |
| US equities intraday via Finnhub free tier | ⏳ | Optional; deferred to later stage. |
| US fundamentals via SEC EDGAR (10-K/Q, 8-K) with PIT `as_of_date` | ⏳ | Adapter coded. |
| Indian equities EOD via jugaad-data + NSE/BSE bhavcopy | ⏳ | Adapter coded. |
| Indian fundamentals via Screener.in scrape | ⏳ | Adapter coded; personal-use scope. |
| Indian mutual fund NAVs via AMFI daily CSV | ⏳ | Adapter coded. |
| FX rates: Frankfurter (ECB) + RBI reference rates | ⏳ | RBI is authoritative for USD/INR — used in tax cost basis. |
| Macro: FRED + DBnomics + World Bank + MOSPI | ⏳ | FRED needs free key (already in `.env`). |
| Commodities: yfinance futures + LBMA fixes + EIA | ⏳ | EIA key in `.env`. |
| News RSS (10+ feeds) | ⏳ | CoinDesk, CoinTelegraph, Decrypt, The Block, Moneycontrol, ET, LiveMint, BS, MarketWatch, Yahoo per-ticker. |
| GDELT global news firehose | ⏳ | Most underused free news source. Entity + tone tagged. |
| arXiv q-fin daily ingest | ⏳ | Quantitative finance papers, weekly digest. |
| SEC 8-K real-time filings RSS | ⏳ | Authoritative US corporate event source. |
| Reddit ingest via PRAW (6 subs) | 🚫 | User skipped Reddit; deferred. |
| Telegram (Telethon) public channels | 🚫 | Needs dedicated SIM; user said maybe later. |
| Bluesky firehose (filtered) | ✅ | `pfip.ingest.news.bluesky.fetch_bluesky` + `ingest_bluesky` — keyword-filtered, atproto SDK, no API key needed. |
| Farcaster via Neynar | ⏳ | Crypto-native social. |
| Polymarket + Kalshi prediction markets | ⏳ | Macro regime features. |
| Self-custody BTC tracking (mempool.space) | ⏳ | User adds public addresses. |
| Self-custody ETH tracking (Etherscan) | ⏳ | Etherscan key in `.env`. |
| Self-custody SOL tracking | 🚫 | User has no self-custody SOL; skipped. |
| Historical backfill (5 years per asset) | ⏳ | Chunked, idempotent, resumable. |
| Per-source freshness tracking | ✅ | `source_health` table written by every flow via `pfip.ingest._common.source_health.record_run`. |
| Adapter health probe `/api/v1/health/sources` | ✅ | Returns per-adapter freshness with status (healthy/stale/failing/never_run) + summary counts. Surfaced in Settings → Source health UI. |
| First-run setup wizard (`/setup/bootstrap`, `/setup/demo`) | ✅ | `POST /api/v1/setup/bootstrap` seeds watchlist + runs free ingests; `/setup/demo` populates synthetic data. Welcome modal auto-shows on dashboard when `needs_setup=true`. |

### M2 — Feature & fundamentals store

What it does: normalizes ingested data into uniform schema; computes derived features.

| Feature | Status |
|---|---|
| Uniform OHLCV hypertable in TimescaleDB | ✅ |
| 150+ technical indicators via `ta` library (RSI, MACD, ATR, BB, etc.) | ✅ `pfip.features.technicals.compute_features`. Patched RSI saturation to 100/0 on pure trends (textbook behaviour; `ta` returns NaN otherwise). Tests pass. |
| Returns (1d, 7d, 30d, log, simple) | ✅ |
| Realized volatility windows (10d, 30d, 90d) | ✅ |
| Fundamentals ratios (P/E, P/B, debt-to-equity, etc.) | ✅ `pfip.features.fundamentals_ratios` — P/E, P/B, D/E, current ratio, ROE, ROIC, FCF yield, dividend yield. None-safe on missing/zero inputs. 7 tests pass |
| On-chain metrics (MVRV, exchange netflow, hash rate) | ⏳ |
| Derivatives features (funding rate, OI, long/short ratio) | ✅ `pfip.features.derivatives` — `DerivativesSnapshot`, `derive_from_history`, ccxt-based (no key needed). Squeeze-setup heuristic + funding z-score |
| FX-converted equivalents (everything in INR for tax) | ✅ `pfip.tax.fx_cost_basis.{get_fx_rate, convert_to_inr, rbi_peak_balance_usd_inr}` — DB→Frankfurter→static fallback chain, 7-day business-day step-back, paise quantization. 8 unit tests in `tests/test_fx_cost_basis.py` |
| Time-zone canonical (UTC stored, IST rendered) | ✅ |
| PIT discipline (`as_of_date` on every fundamental) | ✅ Schema enforces |
| Survivorship-bias-aware universes (delisted retained) | ✅ `watchlist.is_delisted` + `delisted_at` columns (alembic 0007); `pfip.signals.universe.as_of_universe` returns the date-correct symbol set (delisted-after-target retained, delisted-before-target dropped). 8 tests in `tests/test_universe.py` |
| Schema validation at ingest (pandera) | ✅ |
| Idempotent batch keys (no double-writes on retry) | ✅ `pfip.ingest._common.idempotency.make_batch_key` + `last_batch_key` column on `source_health` (alembic 0008). 7 tests in `tests/test_idempotency.py` |
| Cross-source price reconciliation | ✅ `pfip.ingest._common.reconcile.reconcile_latest_closes` + `reconcile-daily` Prefect deployment (18:45 UTC). Worst pair listed first; Telegram WARN when |diff| >= 0.5%. 7 tests in `tests/test_reconcile.py` |
| Anomaly detection (Isolation Forest on outliers) | ✅ `pfip.ingest._common.anomaly` + `anomaly_scan_daily` flow (00:00 IST). Per-symbol IsolationForest over `log_return / range_pct / gap_pct / volume_z`; writes JSONL to `data/anomaly_log/<date>.jsonl`; Telegram WARN if ratio > 1% |

### M3 — News & social pipeline

What it does: turns raw text streams into structured signal tied to assets.

| Feature | Status |
|---|---|
| RSS poll every 15 min (10+ feeds) | ✅ `ingest-news-15min` Prefect flow `pfip.prefect.flows.ingest_news_15min`; dedup + classify + entity link chain in `pfip.ingest.news._pipeline` |
| GDELT poll every 15 min | ✅ `ingest-gdelt-15min` adapter in `pfip/ingest/news/gdelt.py` + pipeline runs entity link |
| Telegram streaming via Telethon | 🚫 (deferred) |
| Bluesky streaming via atproto | ✅ Same module — polling adapter (true streaming = future enhancement) |
| Farcaster streaming via Neynar | ⏳ |
| Article deduplication (URL hash + title fuzzy) | ✅ `pfip.news.enrich.{url_dedup_key, title_fuzzy_key, dedup_articles}` — URL normalize + token-set hash |
| Sentiment classification per article (FinBERT/CryptoBERT) | ✅ `classify_sentiment` — lazy FinBERT primary; deterministic word-bag fallback |
| Entity linking (which ticker, sector, person, central bank) | ✅ `extract_entities` — ticker regex + crypto vocab + central bank + sector dict |
| Impact score 0–100 | ✅ `impact_score` — weighted keywords (40) + |sentiment| (30) + entities (20) + recency (10). 20 tests in `tests/test_news_enrich.py` |
| Embedding into Qdrant for semantic search | ✅ `pfip.kb.news_embed` + `pfip.kb.ingest`; vectors land in `news` and `kb` Qdrant collections |
| Top-N news per asset (queryable) | ✅ `search_news(query, k, filter)` in `pfip.kb.search` + dashboard NewsRow component |
| Sentiment aggregation rolling 7d per asset | ✅ `pfip.ingest.news._pipeline.classify_pending` + DB rollup query |
| News attached to signals (M4 → M3 join) | ✅ `link_entities` populates `entity_tickers` on news rows; agent joins by symbol at query time |
| Counter-argument extraction per signal | ✅ `pfip.signals.news_attach.select_news_for_signal` ranks news by `(impact, |sentiment|, recency)` and partitions into supporting + opposing. 4 tests pass |
| Prompt-injection sanitization on ingested text | ✅ Coded (needs validation) |

### M4 — ML signal layer + model registry

What it does: produces typed BUY/SELL/HOLD signals with confidence per asset.

> **Honest status (2026-06-04): live per-asset signal generation is NOT enabled.** The model
> code below (LightGBM walk-forward, isotonic calibration, SHAP drivers) is implemented and
> correct, and regime/backtest/calibration flows are scheduled — but the
> `signals_generate_daily` Prefect flow is **not in the deployment**, so the `signals` table
> stays empty and the daily shadow-reconcile reads nothing. The multi-asset
> `compute_features_daily` flow is also not deployed (only legacy BTC-only features run). The
> `FEATURE_ML_SIGNALS` config flag is defined but checked nowhere (dead). This is
> intentional: the walk-forward trainer needs ~3y / 756+ bars of OHLCV history per asset,
> which a fresh install lacks. It will be wired when enough history exists. The ✅ marks below
> mean "code exists and is tested", not "running in production today".

| Feature | Status |
|---|---|
| HMM regime detection (3-state: bull/bear/sideways) | ✅ `HMMRegimeDetector` (3 or 4 state) + hmmlearn primary + quantile fallback; Prefect deployment `regime-detect-btc-daily` (01:00 UTC); 8 tests in `tests/test_regime_hmm.py` |
| Per-regime LightGBM signal models | ✅ `train_lgbm_per_regime` Prefect flow (Sat 03:00 UTC) trains one model per (symbol, regime, horizon); persists to file-backed registry; auto-pins champion if slot is empty. 9 tests in `tests/test_train_lgbm_per_regime.py` cover labeling + per-regime slicing + edge cases |
| Confidence floor at 65 (signals below → HOLD) | ✅ Code path exists |
| Per-prediction SHAP explanations (top drivers) | ✅ `pfip.signals.explain` — real SHAP if installed, permutation-importance fallback otherwise. Signed contributions, JSONB-ready serialization. 7 tests in `tests/test_signals_explain.py` |
| Counter-argument extraction (what's against this signal) | ✅ Same module — opposing list returned alongside supporting; configurable top-N |
| Per-signal news attachment (top 5 supporting + top 3 against) | ✅ `attach_news_to_signal(session, symbol, direction)` DB-backed; 48h lookback; matches via `entity_tickers` |
| Model registry: upload `.pkl` / `.onnx` / HuggingFace | ✅ `pfip.signals.registry.upload_model` + `POST /api/v1/models/upload`; SHA-deduped; schema-revision pinned |
| Model registry: catalogue (pin known models) | ✅ `pin_model` / `get_pinned` per `(task, regime, horizon)` slot; `GET /models`, `GET /models/pinned`, `POST /models/{id}/pin`; 11 tests in `tests/test_model_registry.py` |
| Per-regime model selector (hand-coded mapping at Stage 4) | ✅ `pfip.signals.auto_selector`: bull_trend→lgbm_trend, sideways→xgb_meanrev+ttm_short, high_vol→catboost_riskoff(0.5x), accum/dist→full ensemble |
| Trained auto-selector (Stage 6+ stretch) | 🟡 Deferred until ≥12 months of labels |
| Foundation model integration (TTM/Chronos/Moirai) | ⏳ (optional, not on critical path) |
| Calibration job (Brier + ECE + reliability diagram) monthly | ✅ `calibration_monthly` Prefect flow; persists into `calibration_reports`; `pfip.calibration.brier_ece` module |
| Auto-suspend models with ECE > 0.15 for 2 months | ✅ `check_suspension_rule` emits `suspend` event into `model_events` |
| Typed signal contract (Pydantic, validated) | ✅ |

### M5 — Backtesting & validation

What it does: tells you whether a model would have worked, honestly.

| Feature | Status |
|---|---|
| Walk-forward validation (3y window / 21d step) | ✅ `run_walk_forward` + `backtest-walk-forward-btc-weekly` Prefect deployment (Sat 02:00 UTC) |
| CPCV with 5-day embargo (López de Prado) | ✅ `cpcv_folds(n_obs, n_splits, embargo)` purges + embargoes neighbours. 8 tests in `tests/test_cpcv.py` |
| Monte Carlo 1000 block-bootstrap simulations | ✅ `run_monte_carlo` in `pfip.backtest.vectorbt_engine` |
| Benchmark comparison (buy-hold, MA 50/200, RSI mean-rev) | ✅ `BENCHMARKS` dict in `pfip.backtest.benchmarks`; selectable via flow param |
| Transaction cost modeling per market | ✅ `transaction_cost_bps(market_kind)` applied per-trade |
| Shuffle test for leakage detection | ✅ `pfip.backtest.shuffle_test` |
| Lookahead-analysis enforcement | ✅ `lookahead_test` in `vectorbt_engine.py` |
| QuantStats-style tearsheets | ✅ `pfip.backtest.tearsheet.generate_tearsheet()` + `monthly_returns_table()` + `drawdown_series()`. Falls back to built-in HTML when `quantstats` not installed. 13 tests in `tests/test_tearsheet.py`. Fixed pre-existing `out_path` typo. |
| Shadow portfolio (parallel real-time backtest) | ✅ `shadow_holdings` table + `pfip.api.shadow` endpoints; mirrors live signals against a hypothetical portfolio |
| Daily shadow reconcile vs actual | ✅ `shadow_reconcile_daily` Prefect flow |
| Monthly shadow rollup | ⏳ |

### M6 — Knowledge base + RAG

What it does: makes the agent able to cite trading wisdom.

| Feature | Status |
|---|---|
| PDF ingestion (pypdf) | ✅ Coded |
| EPUB ingestion (ebooklib) | ✅ Coded |
| Semantic chunking (LangChain text splitters) | ✅ Coded |
| Embedding via nomic-embed-text local | ✅ |
| Embedding via NVIDIA NIM (planned upgrade) | ⏳ |
| Reranking via Cohere rerank-v3 (planned upgrade) | ⏳ |
| Storage in Qdrant with metadata (book, chapter, page) | ✅ |
| Idempotent ingest (SHA-256 hash) | ✅ Coded |
| RAG retrieval with citations | ✅ `pfip.kb.search.search` + `format_citations` rendered by agent graph |
| RAGAS quality evaluation | ✅ Harness in `pfip.kb.ragas_eval`; Prefect deployment `ragas-eval-monthly` (first Sat 10:00 IST); per-Q CSV under `data/.telemetry/ragas/`; regression guard fires Telegram WARN if faithfulness drops > 0.10 or breaches 0.70 floor |
| 50-Q held-out eval set | ✅ `backend/pfip/kb/eval_qa.json` — 50 hand-built Q&A across Wyckoff/Lefèvre/Graham/Taleb/Dalio/Tharp/Ammous/López-de-Prado/Indian-tax |
| Book → feature/rule translation layer | ✅ `pfip.kb.book_to_rules` — heuristic extractor + optional LLM path with graceful fallback. 12 tests in `tests/test_book_to_rules.py` |

### M7 — Chat agent

What it does: answers natural-language questions about your portfolio + the markets.

| Feature | Status |
|---|---|
| LangGraph orchestration | ✅ Scaffolded |
| Intent classification (DB query vs reasoning vs RAG) | ✅ `pfip.agent.intent.classify_intent` — heuristic patterns, priority DB>RAG>REASONING; 9 routing tests pass |
| Privacy classifier (route to local for sensitive prompts) | ✅ `pfip.agent.privacy` + `Sensitivity` enum (PUBLIC/SENSITIVE/PERSONAL); PERSONAL pins routing to local Ollama. **Hardened 2026-06-04:** `agent/graph.py` feeds open-holding symbols into the classifier and **structurally forces SENSITIVE** whenever a holding row is in the prompt — holdings never reach a cloud LLM even on a classifier miss. Streaming uses `MultiProviderClient.stream`. |
| Tool-calling for DB queries | ✅ `pfip.agent.tools.REGISTRY` — `get_holdings/get_current_price/get_recent_pnl/get_open_signals/get_tax_summary`; each safe-fails to `{ok: false}` |
| RAG over knowledge base | ✅ `kb` collection in Qdrant + agent graph KB retrieval node |
| RAG over news (last N days) | ✅ `search_news` accepts time-window filter; agent graph news retrieval node |
| Source citations on every claim | ✅ `format_citations` block appended to every agent response that retrieved evidence |
| Streaming via SSE | ✅ Endpoint coded |
| Multi-provider routing via LiteLLM | ✅ `pfip.agent.llm_client.MultiProviderClient` over LiteLLM; routes by `(TaskType, Sensitivity)` |
| Fallback chain (Groq → Gemini → Ollama) | ✅ Router walks providers in order with `LLMAllProvidersFailed` aggregation; final fallback is local Ollama for PERSONAL sensitivity |
| Architectural rule: never produces typed signals | ✅ Enforced |

### M8 — Portfolio + risk + allocation + tax

What it does: tracks what you own and what you owe.

#### Portfolio tracking
| Feature | Status |
|---|---|
| Manual holdings entry via UI | ✅ Backend ready |
| CSV import: Zerodha (equity + F&O + MF) | ✅ Adapter coded |
| CSV import: ICICIdirect | ✅ Coded |
| CSV import: Groww | ✅ Coded |
| CSV import: INDmoney (US stocks for Indians) | ✅ Coded |
| CSV import: Vested | ✅ Coded |
| CSV import: WazirX | ✅ Coded |
| CSV import: CoinDCX | ✅ Coded |
| CSV import: Binance | ✅ Coded |
| CSV import: Coinbase | ✅ Coded |
| CSV import: Kraken | ✅ Coded |
| Holdings ledger across 6 categories | ✅ Schema |
| FX-aware cost basis (RBI rate per tx) | ✅ Coded |
| Self-custody vs exchange flag | ✅ Schema |

#### Portfolio analytics
| Feature | Status |
|---|---|
| Per-holding P&L (realized + unrealized) | ✅ Coded |
| Weighted-average cost basis | ✅ Coded |
| Portfolio summary (total INR, exposure by category) | ✅ **Mark-to-market** (2026-06-04): latest OHLCV close per symbol, USD→INR via the `fx_rates` table; correctness-by-abstention falls back to cost basis when currency/FX can't be resolved. `/exposure` + `/concentration` use the same live prices. |
| Mark-to-market coverage endpoint | ✅ `GET /portfolio/marking` (2026-06-04) — `{ as_of, usdinr, marked, unmarked:[{symbol,reason}], mark_prices_inr, coverage, disclaimer }`; reasons `no_price`/`unknown_currency`/`no_fx_rate`. Logic in `pfip.portfolio.marking`; tests in `tests/test_marking.py`. |
| Correlation matrix (rolling, `window_days` 10–365) | ✅ `GET /portfolio/correlations` (2026-06-04) returns a **real** Pearson matrix of daily log-returns from each symbol's own OHLCV history (currency-agnostic). Shape `{ window_days, symbols, matrix, note, disclaimer }`. |
| Historical VaR (95% / 99%) | ✅ Coded |
| Concentration score (Herfindahl) | ✅ Coded |
| Trailing 30-day Sharpe | ✅ Coded |
| Peak-to-current drawdown | ✅ Coded |

#### Risk management
| Feature | Status |
|---|---|
| Position-size cap (10% per holding) | ✅ Configurable |
| Drawdown HALT at 20% peak-to-trough | ✅ Coded |
| Correlation guard (no two positions at >0.7 correlation) | ✅ Coded |
| Daily new-positions cap (2/day) | ✅ Coded |
| Van Tharp position sizing calculator | ✅ Coded |
| 10-item pre-trade checklist (Appendix B) | ✅ UI (`pre-trade-checklist.tsx`) + backend `POST /journal/entries` enforces all 10 keys True before insert |
| Mandatory post-mortem on close | ✅ UI (`post-mortem-dialog.tsx`) + backend `POST /journal/entries/{id}/close` rejects empty post-mortem |
| Pre-commitment file before live capital | ✅ `pfip.portfolio.precommitment` generates the markdown contract; `LadderTier` enum + `enforce_ladder()` gate + `can_advance_tier()` checks (4 wks in tier, zero risk breaches, Sharpe floor, no consecutive losing months). Signing step still requires user. |

#### Allocation
| Feature | Status |
|---|---|
| Strategic targets (equity/debt/gold/crypto %) | ✅ Coded |
| Tactical adjustments (regime + sentiment tilts) | ✅ Coded |
| Rebalance suggestions (drift > 5%) | ✅ Coded |

#### Indian tax engine
| Feature | Status |
|---|---|
| Per-lot capital-gains classifier (FIFO) | ✅ Coded |
| 31-Jan-2018 grandfathering for equities | ✅ Coded |
| STCG @ 15% (equity) | ✅ |
| LTCG @ 10% over ₹1L (equity) | ✅ |
| Debt MF post-2023 slab-rate taxation | ✅ |
| Crypto VDA: 30% flat + 1% TDS, no loss set-off | ✅ |
| Schedule FA (peak USD balance + dividends) | ✅ Coded |
| Form 67 (DTAA Section 90 credit) | ✅ Coded |
| Old vs new tax regime comparison | ✅ Coded |
| 80C / 80D / 80CCD(1B) optimizer | ✅ Coded |
| ELSS vs PPF vs NPS ranking | ✅ Coded |
| Surcharge cliff detection (50L/1Cr/2Cr/5Cr) | ✅ Coded |
| ITR form recommendation (1/2/3) | ✅ Coded |
| Dividend slab-rate taxation post-2020 | ✅ Coded |
| Form 26AS reconciliation | ⏳ |
| Tax-loss harvesting suggestions | ✅ `pfip.tax.harvest` module + `POST /api/v1/tax/harvest` endpoint. Ranked by est. tax saved, VDA skipped, ₹1L LTCG threshold honored, surcharge-adjusted rates, FY-end re-buy warning |
| PDF report generation for CA handoff | ✅ Coded (reportlab) |
| ITR JSON export (Schedule CG + Schedule FA shape) | ✅ Coded |
| Calibration: reproduce last year's ITR ±2% | ⏳ Test |

### M9 — Dashboard + alerts + journal

What it does: gives the user a UI and notifications.

#### UI pages (10 total)
| Page | What you do there | Status |
|---|---|---|
| **Dashboard** (/) | Morning brief, BTC chart, regime badge, top news | 🟡 Renders (empty data) |
| **Portfolio** (/portfolio) | Holdings list, P&L, exposure, correlations | 🟡 Renders (empty) |
| **Watchlist** (/watchlist) | Add/remove tickers per market | 🟡 Renders (empty) |
| **Signals** (/signals) | Latest signals + drivers + counter-args | 🟡 Renders (empty) |
| **Calibration** (/calibration) | Reliability diagrams + ECE per model | 🟡 Renders (empty) |
| **Tax** (/tax) | CSV upload + summary + Schedule FA + Form 67 + 80C optimizer + regime comparison | 🟡 Renders (empty) |
| **Chat** (/chat) | Natural-language Q&A with SSE streaming | 🟡 Renders; agent needs LLM router |
| **Journal** (/journal) | Pre-trade checklist + post-mortem | 🟡 Renders; checklist enforcement pending |
| **Settings** (/settings) | Risk limits, schedules, watchlist config | 🟡 Renders |
| **Login** (/login) | Single-user auth | ✅ Working |

UI infrastructure:
| Feature | Status |
|---|---|
| Mobile-responsive (390×844, 360×780, 768×1024) | ✅ |
| Dark mode | ✅ |
| Cmd+K command palette | ✅ |
| Network status indicator | ✅ |
| Stale-data freshness badges | ✅ `<FreshnessBadge>` component reads cached `useSourceHealth`; wired into BTC chart, regime stack, watchlist movers, risk snapshot, top news; drop-in for any other card |
| Welcome / first-run modal on dashboard | ✅ `frontend/components/shared/welcome-modal.tsx` auto-shows when `needs_setup=true`; 3 tracks (bootstrap real ingest, seed demo, dismiss) |
| Settings → Source health panel | ✅ `components/settings/source-health-panel.tsx` — table + 4 KPI cards + error drawer; 60s poll |
| "What changed today" dashboard card | ✅ `GET /api/v1/changes-today/` aggregates new signals, regime flips, 5σ movers, and top-impact news. Card on dashboard auto-refreshes every 5 min. 6 tests in `tests/test_changes_today.py` |
| Toast notifications | ✅ |
| SSE streaming for chat + signals | ✅ Endpoint level |
| Recharts candle charts | ✅ |
| Tremor KPI cards | ✅ |
| Correlation heatmap | ✅ Component exists |
| Reliability diagram | ✅ Component exists |
| Surcharge gauge | ✅ Component exists |
| SHAP driver bars | ✅ Component exists |

#### Alerts (Telegram)
| Feature | Status |
|---|---|
| Severity tiers (INFO / WARN / CRITICAL) | ✅ `AlertSeverity` enum in `pfip.alerts.dispatcher` |
| Daily digest mode for INFO | ✅ INFO events buffered in Redis, flushed once per day |
| Instant for WARN/CRITICAL | ✅ Bypasses digest queue |
| Quiet hours (23:00–07:00 IST) except CRITICAL | ✅ Coded; CRITICAL still fires |
| Rate caps (≤10/hour) | ✅ Redis-backed sliding window |
| Kill switch (silence all) | ✅ `alerts:silenced=1` Redis flag |
| Escalation (WARN unack 2h → CRITICAL) | ✅ `escalate_unacked_warns` in dispatcher + `escalate-unacked` Prefect flow (every 30m); `ack_alert(id)` clears pending |
| `AlertKind` taxonomy (morning_brief / regime_change / signal_fired / risk_breach / drawdown_halt / ingest_failure / calibration_breach / post_mortem_required) | ✅ Enum + markdown templates in `backend/pfip/alerts/templates/` |
| Telegram bot setup via @BotFather | ⏳ User action — needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_BOT_CHAT_ID` in `.env` |

#### Decision journal
| Feature | Status |
|---|---|
| Pre-trade checklist required before journal entry | ✅ 10/10 boolean checks enforced server-side |
| Post-mortem auto-draft on close | ✅ Two entrypoints: `POST /agent/post-mortem` (by holding_id, contract-shaped PostMortem) wired into PostMortemDialog via `usePostMortemDraft`; `POST /journal/entries/{id}/auto_draft_post_mortem` (by entry_id, markdown) for free-form drafting — both route via `LLMRouter.generate()` with static fallback if router unavailable |
| Failure-pattern tagging (entry-timing, stop-too-tight, etc.) | ✅ `GET /journal/patterns` aggregates last-N-days post-mortems by first-clause key; clustering upgrade once ≥50 closed entries |
| Monthly aggregation: top 3 failure patterns | ✅ Rendered in `FailurePatternsCard` on `/journal` |
| Weekly review (auto-generated Sunday) | ✅ `weekly_review` flow (Sun 19:00 IST) writes `data/weekly_reviews/weekly-review-YYYY-MM-DD.md` + Telegram digest INFO alert |

---

## Section 2 — Cross-cutting features

### Scheduling
| Feature | Status |
|---|---|
| Prefect deployments per task type | ✅ `pfip/prefect/deploy.py` registers ingest_btc_daily, compute_features, ragas_eval_monthly, weekly_review, anomaly_scan_daily, regime_detect_btc_daily, reconcile_daily, backtest_walk_forward, train_lgbm_per_regime |
| Daily morning brief at 07:00 IST | ✅ `morning_brief` flow + `pfip.agent.morning_brief` composer |
| Daily market-close summary at 17:30 IST | ✅ `pfip.agent.market_close.render_markdown` + `market_close_summary` Prefect flow (12:00 UTC weekdays) + Telegram digest. 4 tests in `tests/test_round2_pure.py` |
| Daily shadow reconcile at 23:30 IST | ✅ `shadow_reconcile_daily` flow; needs schedule binding per market |
| Weekly post-mortem at Sun 19:00 | ✅ `weekly_review` flow (Sun 19:00 IST = 13:30 UTC) |
| Weekly arXiv digest at Sat 09:00 | ✅ `ingest_arxiv_weekly` + `pfip.agent.arxiv_digest` composer |
| Monthly calibration report (first Sat 10:00) | ✅ Flow defined; deployment registered |
| Monthly RAGAS eval (first Sat 10:00) | ✅ `ragas_eval_monthly` flow + deployment + regression guard |
| Monthly shadow rollup (last Sun 19:00) | ✅ `shadow_rollup_monthly` Prefect flow (cron `30 13 25-31 * 0`) + Telegram digest |
| Quarterly restore-from-backup drill | ✅ `scripts/restore_drill.sh` — spins up isolated docker compose project on shifted ports, restores pg dump + Qdrant snapshots, verifies table counts, writes timestamped report to `data/restore_drills/`. Run quarterly via cron. |
| Quarterly Tier-S/A/B review | 🟡 Self-review; no scheduled flow (calendar reminder via Telegram instead) |
| Annual ITR calibration run | ✅ `annual_itr_drill` Prefect flow (June 15 09:00 IST); compares engine to user-supplied `data/itr_filed/<FY>.json`; ±2% band; WARN on OOB |
| Skipped-task alerting | ✅ `skipped_task_alerter` Prefect flow runs hourly; per-deployment staleness budget; Telegram WARN when overdue |

### Backups & DR
| Feature | Status |
|---|---|
| Nightly pg_dump TimescaleDB → encrypted external | ✅ Script coded |
| Nightly Qdrant snapshot via /collections/{name}/snapshots API | ✅ Script coded |
| Nightly MLflow artefact sync | ✅ Script coded |
| Retention policy (30 daily / 12 monthly / 5 yearly) | ✅ Coded |
| Optional rclone push to off-site (B2, Drive) | ✅ Coded; needs `RCLONE_REMOTE` env |
| Quarterly restore drill (isolated compose project) | ✅ Script coded; not yet run |

### Observability
| Feature | Status |
|---|---|
| Sentry exception capture (free tier) | ✅ Wired |
| Loguru structured logging | ✅ |
| Uptime Kuma per-service ping | ✅ Container running; first-time wizard pending |
| LangSmith LLM call tracing (free tier) | ⏳ Optional |
| Health endpoint `/api/v1/health` (shallow) | ✅ Returns 200 |
| Health endpoint `/api/v1/health/deep` | ✅ (2026-06-04) Separates CORE (TimescaleDB, Redis) from OPTIONAL (Qdrant, Ollama, cloud LLM). Reports `ok`/`degraded`/`down` + a `ready` boolean — a local run with Ollama down is `degraded`, not `down`. |
| Source health endpoint `/api/v1/health/sources` | ✅ Per-adapter freshness + summary; rendered in Settings → Source health panel; auto-refresh every 60s |

### Security
| Feature | Status |
|---|---|
| Single-user JWT auth via NextAuth + bcrypt | ✅ |
| Frontend route protection (middleware) | ✅ (2026-06-04) `frontend/middleware.ts` gates all routes except `/login`, `/api/auth`, static assets; `apiFetch` redirects to `/login` on 401. |
| Auth required on `/assets/*` endpoints | ✅ (2026-06-04) All 4 endpoints now require `CurrentUser` (were unauthenticated). |
| Upload cap + broker validation on `/tax/import` | ✅ (2026-06-04) 10 MB cap; broker validated against the known adapter registry. |
| Security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP) | ✅ (2026-06-04) Set in `frontend/next.config.mjs`. |
| Fail-loud auth secrets in compose | ✅ (2026-06-04) `${NEXTAUTH_SECRET:?}` + `${POSTGRES_PASSWORD:?}`; insecure `:-` defaults removed; config validator raises on defaults when `APP_ENV != "dev"`. |
| Loopback-only host ports (compose-enforced) | ✅ (2026-06-04) Every port mapped `127.0.0.1:PORT:PORT`; nothing on `0.0.0.0`/LAN. |
| Non-root containers + prod/dev Docker targets | ✅ (2026-06-04) `backend` runs as `appuser`; frontend dropped the lockfile-defeating `|| pnpm install`. |
| Auth secrets via `.env`, not git | ✅ |
| Docker network isolation (services not exposed beyond compose) | ✅ |
| LUKS disk encryption | ⏳ User action |
| UFW firewall + SSH keys + fail2ban | ⏳ User action |
| `.env` Docker Compose `$$` escaping documented | ✅ |
| API keys rotated when leaked in chat | 🟡 Should rotate Groq + Sentry DSN periodically |

### Dev / quality
| Feature | Status |
|---|---|
| pytest unit + property-based (hypothesis) | ✅ Suite exists |
| ruff + black + mypy + pre-commit | ✅ Configured |
| GitHub Actions CI on PR | ✅ Workflow exists |
| Alembic migrations 0001–0005 (linearized) | ✅ |
| Reproducible Docker build | ✅ |
| ONBOARDING.md for future-Suresh | ✅ Template; needs updating per stage |
| Runbook library (`docs/runbooks/`) | ✅ 14 seeded (compose env-file, postgres password, source_health cast, prefect signature, NSE cookie, yfinance throttle, ollama OOM, telegram flood-wait, port conflict, timescale disk-full, prefect stuck, welcome modal stuck, telegram alerts not firing, capital ladder blocked) |

---

## Section 3 — User-visible workflows

These chain features into specific user goals.

### Workflow A — Morning routine
1. 07:00 IST: morning brief lands on phone (Telegram) and dashboard home.
2. User scans 8 sections in ~30 sec: overnight moves, calendar, news, regime, watchlist deltas, risk, calibration note, shadow vs actual.
3. If something interesting: open chat agent, ask "why did NVDA gap up overnight?"
4. Agent answers with cited news + current sentiment + regime.
5. User decides: do nothing / add to watchlist / open journal entry for considering a trade.

### Workflow B — Considering a trade
1. User opens Journal page.
2. Clicks "New entry" → form with 10-item pre-trade checklist (Appendix B).
3. Agent auto-fills checklist from data: thesis, counter-argument, signal+confidence, news context, correlation check, regime fit.
4. User edits, ticks each box.
5. Save → entry locked. If trade taken: status flips to "Open".
6. Risk manager checks: position size, correlation guard, drawdown halt. Either OK or warning surfaced.

### Workflow C — Closing a position
1. User marks position closed in portfolio.
2. System triggers post-mortem auto-draft (uses entry signal + news at entry/exit + calibration).
3. Agent drafts structured analysis: thesis-correct?, signal model performance, counter-argument that played out, suggested-do-differently.
4. User reviews + edits + confirms.
5. Tagged failure pattern feeds monthly aggregation.

### Workflow D — Tax preparation (annual)
1. April: user uploads broker CSVs (Zerodha, INDmoney, WazirX, etc.) via Tax page.
2. System parses + classifies: STCG vs LTCG, equity vs debt MF vs crypto VDA.
3. Computes Schedule FA (US stock peak balance + dividends).
4. Computes Form 67 (DTAA credit on US dividend withholding).
5. Old vs new tax regime comparison shown.
6. 80C/D/CCD optimizer flags marginal moves.
7. PDF report + JSON export → handoff to CA.
8. After filing: enter actuals → calibration check (±2%).

### Workflow E — Weekly retro
1. Sunday 19:00: agent generates weekly review draft.
2. User opens Notion → Weekly Review → moves "This week" to "Past weeks" → reads + edits draft.
3. Pattern aggregation across 4 weeks → reveals systematic issues.

### Workflow F — Quarterly review
1. First Saturday of Jan/Apr/Jul/Oct: restore-from-backup drill runs.
2. Tier-S/A/B review: anything Tier-S pending > 60 days = flag.
3. Calibration deep-dive: which models drifted, retrain candidates.
4. Decision Log review: any Pending decisions overdue.

---

## Section 4 — What's NOT supported (by design)

| Non-feature | Why not |
|---|---|
| Auto-execution of trades | v1 paper-trading only. Real capital after Stage 7+ paper validation. |
| LLM-issued trade decisions | Architectural rule. LLMs explain; ML models decide. |
| Tax filing itself | Module advises; user files via CA or ITR portal. |
| Multi-user / SaaS | Solo use only. No auth flows beyond single user. |
| FX trading (as an asset class) | FX in for cost basis; not as traded asset. |
| Options trading execution | Options analytics in; execution deferred. |
| Real-time intraday Indian equities | Not free; requires broker API. Deferred. |
| US tax for direct US brokerage | Out of scope; INDmoney/Vested are reported on Indian side via Schedule FA. |
| GST / TDS for businesses | Personal finance only. |
| Public-facing API | Internal only; localhost. |
| Mobile native app | Mobile-responsive web is enough. |

---

## Section 5 — Future feature wishlist (not on roadmap)

If we ever extend past Stage 7:

- **Knowledge graph layer** over news entities (companies, people, sectors, events)
- **Voice interface** via Whisper + Piper TTS for morning brief on commute
- **Multi-agent personas** (Buffett-vs-Druckenmiller debate)
- **Anti-fragility tests** (intentional small simulated failures)
- **Counterfactual engine** ("what if I'd followed every signal?")
- **Public track record / reputation** if PFIP outputs ever get shared
- **Fine-tuned LLM** on PFIP's accumulated decision journal

---

## How this doc relates to others

| Doc | Purpose |
|---|---|
| `WHY_AND_WHAT.md` | **Why** every dependency, model, data source exists. The architecture rationale. |
| **`FEATURES.md` (this doc)** | **What** the system does. The feature inventory. |
| `LLM_ROUTING.md` | **Where** LLMs help. The routing decisions. |
| `BUILD_STATUS.md` | What was built in the initial scaffold pass. |
| `PLACEHOLDERS.md` | Outstanding inputs needed from user. |
| `LOGIN.md` | Credentials + how to rotate. |
| `docs/CONTRACTS.md` | API + DB authoritative spec. |
| `docs/runbooks/*.md` | Operational runbooks. |
| Notion *Build Items* | Live progress tracker. |
| Notion *Decisions Log* | Architectural choices made + pending. |
| Notion *Weekly Review* | Running log of what shipped each week. |
| Notion *LLM Routing* | Scannable summary of routing decisions. |

---

*Last updated: 2026-06-04 (security/correctness audit + portfolio MTM/marking/correlations + honest ML-signal status). Update Status column whenever a feature ships.*
