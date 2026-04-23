# PFIP Glossary

One-line definitions for PFIP-specific terms, market jargon, and Indian tax acronyms.
Alphabetical.

---

- **Advance tax** — pay-as-you-earn instalments due 15 Jun / 15 Sep / 15 Dec / 15 Mar if
  annual liability exceeds Rs 10,000; shortfall carries interest under Sec 234B/C.
- **AMFI** — Association of Mutual Funds in India; publishes daily NAVs consumed by the
  Stage 2 mutual-fund ingest.
- **ATR** — Average True Range; volatility feature used for stop-loss sizing in M2.
- **BitLocker** — Windows full-disk encryption; required on every drive holding the repo
  or backups (see `docs/SECURITY.md`).
- **Brier score** — probabilistic accuracy metric for calibrated signals (lower is
  better); tracked in MLflow per plan Section 5.
- **CA** — Chartered Accountant; human-in-the-loop for Indian tax filing.
- **Calibration** — alignment between predicted probabilities and realised frequencies;
  monitored monthly via Brier + ECE + reliability diagrams.
- **CPCV** — Combinatorial Purged Cross-Validation; the leakage-resistant cross-validation
  scheme used in M5 backtesting (Lopez de Prado).
- **Drawdown** — peak-to-trough decline of a portfolio's equity curve; PFIP halts new
  signal acceptance at `DRAWDOWN_HALT_PCT` (default 20%).
- **DTAA** — Double Taxation Avoidance Agreement; bilateral treaty that prevents being
  taxed on the same foreign income twice. Credit claimed via Form 67.
- **ECE** — Expected Calibration Error; a scalar calibration metric complementing Brier.
- **F&O** — Futures & Options segment (derivatives). Treated as non-speculative business
  income in India by default.
- **FMV** — Fair Market Value; used for airdrop / staking receipts and for carry-over cost
  basis.
- **Form 67** — Indian form filed *before* the ITR to claim DTAA credit for foreign taxes
  withheld.
- **Fundamental (PIT)** — fundamentals row stored with both `as_of_date` (when the market
  knew it) and `report_date` (period covered). Queries must respect `as_of_date <= t`.
- **GDELT** — Global Database of Events, Language, and Tone; news-events firehose ingested
  in M3 Stage 3.
- **Hypertable** — TimescaleDB's partitioned-by-time table; what `ohlcv` is created as.
- **Hystersis (regime)** — small buffer before flipping regime label to avoid whipsaws.
- **IBKR** — Interactive Brokers; common foreign broker for Indian residents holding US
  equities.
- **IST** — Indian Standard Time, UTC+05:30; the default display time zone.
- **ITR** — Income Tax Return. Individuals with capital gains file ITR-2 or ITR-3.
- **LangGraph** — stateful agent framework used in M7 to orchestrate LLM + tool calls.
- **LTCG** — Long-Term Capital Gains; tax bucket for assets held beyond the threshold
  (varies by asset class — see `docs/TAX_REFERENCE.md`).
- **LUKS** — Linux Unified Key Setup; full-disk encryption for Linux hosts (BitLocker's
  counterpart).
- **MLflow** — experiment + model registry; runs at http://localhost:5000.
- **Morning brief** — daily markdown summary generated at 07:30 IST combining overnight
  moves, signal changes, and KB pointers.
- **NAV** — Net Asset Value; per-unit value of a mutual fund, published daily by AMFI.
- **NFO** — New Fund Offer (MF) / NSE F&O depending on context.
- **NSE** — National Stock Exchange of India.
- **Ollama** — local LLM runtime; hosts `mistral:7b-instruct` and `nomic-embed-text`.
- **PIT** — Point-In-Time; the invariant that historical queries must not see data that
  wasn't publicly available at that instant. Enforced for fundamentals and news alike.
- **Post-mortem** — structured review attached to every closed position; template in
  `docs/checklists/post_mortem.md`.
- **Pre-trade checklist** — 10-item form required before any BUY or SELL journal entry;
  template in `docs/checklists/pre_trade.md`.
- **Prefect** — workflow orchestrator; all scheduled jobs live here.
- **Qdrant** — vector database; stores KB chunk embeddings and news embeddings.
- **Regime** — macro-micro state label from M3: `bull_trend | bear_trend | sideways |
  high_volatility | accumulation | distribution`.
- **RSI** — Relative Strength Index; momentum oscillator (0–100).
- **SBI TT** — State Bank of India Telegraphic Transfer rate; mandated by Rule 115 for
  converting foreign-asset transactions to INR for tax.
- **Schedule FA** — Foreign Assets schedule inside the ITR; required disclosure of any
  foreign asset held at any point in the reporting window.
- **SGB** — Sovereign Gold Bond; interest-bearing gold-linked G-Sec. Fully tax-exempt on
  capital gains if held to maturity (8 years).
- **Shadow portfolio** — paper-trading mirror of the real portfolio; enables signal
  performance tracking without capital risk.
- **Signal** — the typed contract returned by M4; includes direction, confidence, drivers,
  counter-arguments, regime, model identity. Immutable once emitted (see `CONTRACTS.md`
  §2).
- **STCG** — Short-Term Capital Gains; tax bucket for assets below the holding-period
  threshold.
- **Tailscale** — zero-config WireGuard tunnel; used for remote access without exposing
  ports publicly.
- **Telethon** — Python MTProto client for Telegram user accounts; used for channel
  ingest (separate from bot API).
- **TimescaleDB** — time-series extension on Postgres 16; the primary transactional store.
- **VDA** — Virtual Digital Asset; Indian tax-law umbrella for crypto, NFTs, and similar.
  Taxed at flat 30% under Sec 115BBH with no loss set-off.
- **Vectorbt** — backtesting library used in M5.
- **Walk-forward** — out-of-sample evaluation scheme rolling train / test windows forward
  in time; complements CPCV.
- **XIRR** — Extended Internal Rate of Return; annualised time-weighted return for
  irregular cash flows; the canonical portfolio-level return metric PFIP reports.
