# PFIP — Session log, 2026-05-29

This document is the **single canonical record** of what was implemented in
the session of 29 May 2026 (continuation through context-window
compaction). Anything claimed in conversation but not listed here did not
ship.

---

## 1. Backend modules shipped this session

### 1.1 `backend/pfip/api/setup.py` (new, prior to compaction)
First-run wizard endpoints:

- `GET /api/v1/setup/status` → returns onboarding checklist + row counts.
- `POST /api/v1/setup/bootstrap` → seeds default watchlist + runs
  AMFI/FX/macro/crypto ingests concurrently.
- `POST /api/v1/setup/demo` → synthetic data seed (calls
  `pfip.scripts.seed_demo`).
- `DELETE /api/v1/setup/demo` → removes everything tagged `DEMO-*`.

Wired under `/api/v1` in `pfip/api/main.py`.

### 1.2 `backend/pfip/api/health.py` — `/health/sources`
Returns per-adapter freshness (`status` in `healthy / stale / failing /
never_run`) plus a `summary` block (`total / healthy / stale / failing /
never_run`). Status thresholds are per-adapter expected cadence (1h / 6h
/ 24h / weekly).

### 1.3 `backend/pfip/ingest/_common/source_health.py`
Every ingest flow calls `record_run(source, rows, error=...)` after each
batch. Fix this session: SQL `CASE WHEN CAST(:err AS text) IS NULL …`
to resolve `psycopg3 AmbiguousParameter`.

### 1.4 `backend/pfip/scripts/seed_watchlist.py` (new)
Idempotent default watchlist seeder. Five tickers per market across
crypto / US / India / MF / FX.

### 1.5 `backend/pfip/scripts/seed_demo.py` (new)
Populates `ohlcv` (90d random walk per asset), `watchlist`, `news`,
`regime`, `signals`, `holdings` with `DEMO-*` sentinel prefix. Includes
`clear_demo()` for reversal.

### 1.6 `backend/pfip/alerts/dispatcher.py` (new)
Telegram alert dispatcher:

- `AlertKind` enum (`MORNING_BRIEF`, `REGIME_CHANGE`, `SIGNAL_FIRED`,
  `RISK_BREACH`, `DRAWDOWN_HALT`, `INGEST_FAILURE`,
  `CALIBRATION_BREACH`, `POST_MORTEM_REQUIRED`).
- `AlertSeverity` enum (`INFO / WARN / CRITICAL`).
- Quiet hours 23:00–07:00 IST suppress INFO + WARN; CRITICAL bypasses.
- Rate cap 10/hour via Redis sliding window.
- Digest mode for INFO.
- Kill-switch flag `alerts:silenced=1`.

Markdown templates under `backend/pfip/alerts/templates/`:

- `risk_breach.md`
- `drawdown_halt.md`
- `regime_change.md`
- `signal_fired.md`
- `ingest_failure.md`
- `calibration_breach.md`

### 1.7 `backend/pfip/portfolio/precommitment.py` (new) — Stage 7
- Markdown pre-commitment file generator.
- `LadderTier` enum: `PAPER / FIVE_PCT / TEN_PCT / TWENTYFIVE_PCT / FULL`.
- `enforce_ladder()` gate refuses orders above the cap of the current tier.
- `can_advance_tier()` runs the four progression checks: ≥4 weeks in tier,
  zero risk breaches, Sharpe floor, no consecutive losing months.

### 1.8 `backend/pfip/signals/auto_selector.py` (new) — Stage 4
Hand-coded regime → model mapping per plan §7.2:

- `bull_trend` → `lgbm_trend_specialist`
- `sideways` → `xgb_meanrev_specialist` + `ttm_short`
- `high_volatility` → `catboost_riskoff` at half size
- `accumulation` / `distribution` → full ensemble

Public API: `add_override()`, `record_selection()`,
`select_for_watchlist()`. Trained selector deferred to Stage 6+.

### 1.9 `backend/pfip/kb/eval_qa.json` (new)
50 hand-built Q&A pairs covering Wyckoff, Lefèvre, Graham, Taleb, Dalio,
Van Tharp, Ammous, López de Prado, Indian tax (STCG/LTCG/VDA/Schedule
FA/Form 67/80C/surcharge), regime detection, calibration, ops.

### 1.10 `backend/pfip/kb/ragas_eval.py` (new this turn)
- `load_eval_set(path)` — parses the JSON (tolerant of flat list or
  `{questions: [...]}`).
- `run_eval()` — async driver that retrieves top-k chunks, asks the
  configured LLM to answer grounded, scores `faithfulness +
  answer_relevancy + context_precision` via RAGAS, logs to MLflow.
- `save_results(result, out_path)` — CSV of per-question rows for
  cross-run diffing.
- `RagasMissingError` — clean failure when `ragas / datasets` are absent
  (CLI exits 2; Prefect flow logs warning and returns None).

### 1.11 `backend/pfip/prefect/flows/ragas_eval_monthly.py` (new this turn)
- Prefect flow `ragas-eval-monthly`.
- Saves a CSV under `data/.telemetry/ragas/<run_id>.csv` on every run.
- Fires Telegram WARN via the dispatcher if `faithfulness < 0.70` or
  drops > 0.10 vs the previous CSV.
- Registered in `pfip/prefect/deploy.py` on cron `30 4 1-7 * 6`
  (first Saturday of every month, 10:00 IST).

### 1.12 `backend/pfip/scripts/run_ragas_eval.py` (new this turn)
CLI wrapper. Usage:

    python -m pfip.scripts.run_ragas_eval --sample 5    # smoke
    python -m pfip.scripts.run_ragas_eval               # full
    python -m pfip.scripts.run_ragas_eval --no-mlflow   # CSV only

### 1.13a `backend/pfip/prefect/flows/weekly_review.py` (new — Phase G)
Sunday 19:00 IST flow that writes `data/weekly_reviews/weekly-review-<date>.md`
with sections for closed trades, top failure patterns, regime changes,
and a "things to do before next week" checklist. Posts a Telegram INFO
digest with the path. New `AlertKind.WEEKLY_REVIEW` + template.

### 1.13b `backend/pfip/api/journal.py` — auto-draft (Phase H)
`POST /journal/entries/{id}/auto_draft_post_mortem` → markdown draft
keyed on the journal entry id. Routes via `LLMRouter.generate()` with a
static fallback template if the router is unavailable. Coexists with
the existing `POST /agent/post-mortem` (which is keyed on holding_id
and returns the contract-shaped PostMortem object).

### 1.13c `backend/pfip/tax/harvest.py` + `POST /tax/harvest` (Phase I)
Tax-loss harvesting suggestions module. Honors Indian rules:

- VDA / crypto excluded (no loss set-off per Section 115BBH).
- STCG equity losses match STCG pool first, then spill to LTCG.
- LTCG equity savings count only above the ₹1L exemption.
- US stocks / gold are scored against an estimated future-year offset
  (8-year carry-forward window, 0.5× discount).
- Surcharge-adjusted rates.
- FY-end re-buy warning when within 30 days of close.

### 1.13d `backend/pfip/ingest/_common/anomaly.py` + flow (Phase J)
Per-symbol IsolationForest over engineered features
(`log_return / range_pct / gap_pct / volume_z`). Writes JSONL to
`data/anomaly_log/<date>.jsonl`. Daily flow registered at 18:30 UTC
(00:00 IST). Fires a Telegram WARN when the anomaly ratio of a batch
exceeds 1%.

### 1.14a `backend/pfip/api/journal.py` (extended this turn)
- `_REQUIRED_CHECKLIST_KEYS` expanded from 4 to **all 10** Appendix-B
  items: `regime_check, risk_size_ok, thesis_written, exit_plan_defined,
  invalidation_set, correlation_check, liquidity_check,
  tax_impact_considered, news_check, regime_alignment`.
- `GET /journal/patterns?days=30&top=5` → aggregates closed entries'
  post-mortems into top-N failure patterns (first-clause heuristic;
  clustering upgrade at ≥50 closed entries).

### 1.14 Dependency additions
`backend/requirements.txt`:

    ragas>=0.1.10
    datasets>=2.18.0

(Large transitive deps — kept loose so resolver can pick coherent
versions with `langchain`/`transformers`.)

---

## 2. Frontend modules shipped this session

### 2.1 `frontend/lib/api.ts` (extended)
- `useSetupStatus`, `useBootstrap`, `useSeedDemo`, `useClearDemo`,
  `useSourceHealth` with TypeScript interfaces.
- `useJournalPatterns({days, top})` (this turn) for the new
  `/journal/patterns` endpoint.

### 2.2 `frontend/components/shared/welcome-modal.tsx` (new)
First-run modal — auto-shows when `setup/status.needs_setup === true`.
Three tracks: bootstrap real data, seed demo, dismiss with
`localStorage["pfip:welcome-dismissed"]`.

Wired into `frontend/app/page.tsx`.

### 2.3 `frontend/components/settings/source-health-panel.tsx` (new this turn)
Settings → Source health panel:

- Four KPI cards (total / healthy / stale / failing).
- Full table with status badge, last-run age, last-success age, rows,
  consecutive-failure count.
- Collapsible "last errors" drawer.
- 60-second auto-refresh via `useSourceHealth`.

Wired into `frontend/app/settings/page.tsx`.

### 2.4 `frontend/components/shared/freshness-badge.tsx` (new this turn)
Tiny coloured-dot + tooltip component. Drop next to any title:

    <FreshnessBadge sources={["coinbase_ohlcv", "ccxt_BTC_USD"]} />

Aggregates the worst status across all listed adapters. Already wired
into five dashboard cards (BTC chart, Markets at a glance, Watchlist
movers, Risk snapshot, Top news).

### 2.5 `frontend/app/journal/page.tsx` (extended this turn)
`FailurePatternsCard` now prefers `GET /journal/patterns` and falls
back to the client-side compute when the endpoint is empty / unavailable.

---

## 3. Runbooks added this session
- `docs/runbooks/welcome_modal_stuck.md` (this turn)
- `docs/runbooks/alerts_telegram_not_firing.md` (this turn)
- `docs/runbooks/capital_ladder_blocked.md` (this turn)
- `docs/runbooks/source_health_ambiguous_param.md`
- `docs/runbooks/prefect_signature_mismatch.md`
- `docs/runbooks/compose_env_file_flag.md`
- `docs/runbooks/postgres_password_mismatch.md`

Total runbook count: **14**.

---

## 4. Docs updated this session
- `docs/FEATURES.md` — flipped all newly-shipped items to ✅, added new
  rows for welcome modal / source health UI / freshness badges /
  failure-pattern endpoint / monthly RAGAS / Appendix-B enforcement.
- `docs/LLM_ROUTING.md` — unchanged (already comprehensive).
- `docs/CONTRACTS.md` — unchanged.

---

## 5. Placeholder dependencies — needs Suresh's input before further progress

| Placeholder | Where it matters | What you do |
|---|---|---|
| `NVIDIA_NIM_API_KEY` | LLM router cloud route | Get key from build.nvidia.com, paste in `.env` |
| `GEMINI_API_KEY` | LLM router fallback | Get key from aistudio.google.com, paste in `.env` |
| `DEEPSEEK_API_KEY` | LLM router code-reasoning route | Get key from platform.deepseek.com |
| `OPENROUTER_API_KEY` | LLM router meta-router | Get key from openrouter.ai |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Telethon public-channel ingest | Get from my.telegram.org/apps using a **dedicated** account |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_CHAT_ID` | Alert dispatcher | @BotFather → token; `/start` to bot then `getUpdates` for chat_id |
| Self-custody crypto addresses | BTC mempool.space + ETH Etherscan watchers | Paste BTC + ETH addresses in `.env` |
| Broker CSV exports | Stage 5 tax adapter testing | Download Zerodha / ICICI / Groww / WazirX / etc. CSVs into `data/imports/` |
| 20 books PDF/EPUB | KB ingest | Place under `data/kb_sources/` (any plain folder structure) |
| Signed pre-commitment file | Stage 7 capital ladder activation | Generate via `precommitment.generate()`, sign offline, place hash at `data/precommitment/signed.md.sha256` |

---

## 6. Tasks list state at session end

Completed:

- #1–#17 — prior session work.
- #18 — Phase B: Frontend integrations (welcome modal + source health UI).
- #19 — Phase C: Final docs + Notion update.
- #20 — Phase D: RAGAS harness + monthly flow + CLI + regression guard.
- #21 — Phase E: Stale-data freshness badges (component + 5 wiring points).
- #22 — Phase F: 10/10 checklist enforcement + `/journal/patterns` aggregation.
- #23 — Phase G: Weekly review auto-generator (Sun 19:00 IST).
- #24 — Phase H: Post-mortem LLM auto-draft on close (two entrypoints).
- #25 — Phase I: Tax-loss harvesting suggestions (`POST /tax/harvest`).
- #26 — Phase J: Anomaly detection on ingested data (IsolationForest daily flow).

Outstanding (no user input needed; can ship in a future session):

- Failure-pattern clustering once ≥50 closed entries exist (currently
  first-clause heuristic).
- Trained regime→model selector (Stage 6+, needs ≥12 months of labels).
- Embedding/reranking upgrade to NVIDIA NIM + Cohere (needs API keys).

---

## Phase K–W extension (same session, after "what else is left" review)

### 1.15 `pfip.signals.explain` (Phase O)
Per-prediction explanations. Tries real `shap` (lazy import), falls back
to permutation importance against a background dataset. JSONB-ready
serialization for the `signals.drivers` column. 7 tests in
`tests/test_signals_explain.py`.

### 1.16 `pfip.backtest.tearsheet.{monthly_returns_table, drawdown_series}` (Phase Q)
Added year×month×YTD pivot + underwater drawdown series alongside the
existing `generate_tearsheet`. Fixed a pre-existing `out_path`/`output_path`
typo that made the fallback HTML path crash. 13 tests in
`tests/test_tearsheet.py`.

### 1.17 `tests/test_fx_cost_basis.py` (Phase R)
8 tests covering INR pass-through, static-fallback exact match,
business-day step-back, paise quantization, and Schedule-FA peak-balance.

### 1.18 `tests/test_regime_hmm.py` (Phase K)
8 tests for `HMMRegimeDetector` against the fallback (no-hmmlearn) path:
state→regime labeling, n_states validation, score_per_bar contract.
Wired daily Prefect deployment `regime-detect-btc-daily` (01:00 UTC).

### 1.19 `tests/test_train_lgbm_per_regime.py` (Phase L)
9 tests for the per-regime training flow's pure-logic pieces:
`slice_per_regime`, `make_label`, `train_one` edge cases. Wired weekly
Prefect deployment.

### 1.20 `tests/test_reconcile.py` (Phase V, prior session)
7 tests for cross-source reconciliation: threshold gating, sort order,
zero-midpoint safety, multi-source fan-out.

### 1.21 `tests/test_model_registry.py` (Phase P, prior session)
11 tests already passed — upload + SHA-256 dedupe + list filter + pin
roundtrip + load_pickle.

### 1.22 `tests/test_universe_idempotency_news_pure.py` (Phases S, U, N)
16 tests covering survivorship-aware universe selection,
deterministic batch-key hashing (idempotent ingest, Phase U), and
URL normalization for news dedup.

### 1.23 Pre-existing test fixes
- `pfip/api/assets.py` routes changed from `/{symbol}/...` to
  `/{symbol:path}/...` so symbols containing `/` (e.g. `BTC/USD`) match.
  Fixed 4 failing tests in `tests/test_assets.py`.
- `pfip/features/technicals.py` RSI patched to saturate at 100/0 on
  pure trends — `ta` returns NaN on zero-loss bars, contradicting the
  textbook definition. Fixed `tests/test_features.py::test_compute_features_values_on_trend`.

### Tally
- FEATURES.md: **175 shipped ✅ · 16 partial 🟡 · 44 pending ⏳ · 5 non-goal 🚫**.
- Test suite: **358 pass · 1 skip · 0 fail** (full `pytest` run, 15s).
- Remaining ⏳ rows all need one of: (a) docker run + ingest, (b) user
  API key, or (c) accumulated runtime data.

---

## 7. How to verify everything came up clean

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app

# Backend syntax sanity
docker compose --env-file .env exec backend python -c "
import importlib
for m in [
    'pfip.api.main',
    'pfip.api.setup',
    'pfip.api.journal',
    'pfip.api.health',
    'pfip.alerts.dispatcher',
    'pfip.portfolio.precommitment',
    'pfip.signals.auto_selector',
    'pfip.kb.ragas_eval',
    'pfip.prefect.flows.ragas_eval_monthly',
    'pfip.scripts.seed_demo',
]:
    importlib.import_module(m); print('OK', m)
"

# Endpoint smoke
curl -sS http://localhost:8000/api/v1/setup/status | jq
curl -sS http://localhost:8000/api/v1/health/sources | jq '.summary'

# Frontend pages
# - http://localhost:3000/                  (dashboard with freshness dots)
# - http://localhost:3000/settings          (Source health panel near bottom)
# - http://localhost:3000/journal           (FailurePatternsCard)

# RAGAS smoke (only after `docker compose build backend` with new deps)
docker compose --env-file .env exec backend python -m pfip.scripts.run_ragas_eval --sample 3
```
