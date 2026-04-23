# Stage Gate 1 — First Market Live Sign-Off

Plan **Section 12** Stage 1: one chosen market ingests cleanly end-to-end, features build,
the frontend shows live data for that market, and the shadow portfolio can record a paper
trade. Default market: BTC. Alternative starts: Indian equities (NIFTY50 constituents via
jugaad-data) or US equities (SPY + 10 megacaps via yfinance).

Stage 0 gate (`stage_gate_0.md`) must already be signed off.

---

## 1. Scope frozen

- [ ] Starting market chosen and recorded (`PLACEHOLDERS.md` section 1 decision 1).
      Value: __________________________________________________________________
- [ ] Instrument universe listed in `/backend/pfip/universe/stage1.yml`.
- [ ] Timeframes agreed: at minimum `1d`; `1h` if the data source supports it for free.

## 2. Ingest

- [ ] Adapter implemented under `/backend/pfip/ingest/<market>/`.
- [ ] Prefect deployment created from `/schedules/stage1_ingest.py` and visible in the
      Prefect UI.
- [ ] Scheduled cadence documented in `docs/SCHEDULED_TASKS.md` (and the live cron in
      Prefect matches exactly).
- [ ] Backfill to T-2y completed:
      `SELECT min(time), max(time), count(*) FROM ohlcv WHERE symbol IN (...);`
- [ ] Daily flow has run successfully 3 consecutive days (no red in Prefect).

## 3. Features

- [ ] PIT-safe feature builders implemented for at least: 7d return, 30d return, 30d vol,
      RSI(14), MACD(12,26,9), ATR(14).
- [ ] `GET /api/v1/assets/{symbol}/features?as_of=<ISO>` returns the expected dict for
      historical dates (PIT check: no value uses future data).
- [ ] Feature unit tests green (`pytest -k features`).

## 4. Regime (M3 minimum viable)

- [ ] At least a rules-based regime classifier active (bull / bear / sideways based on
      200d SMA and 30d realized vol).
- [ ] `GET /api/v1/assets/{symbol}/regime` returns `{ regime, since, confidence }` for
      every asset in the Stage 1 universe.

## 5. Frontend

- [ ] Home dashboard lists the Stage 1 universe with latest close, 1d/7d/30d change,
      regime badge.
- [ ] Clicking a symbol opens a detail page with candle chart, feature panel, regime
      history.
- [ ] Watchlist add/remove works; persists to backend.
- [ ] All pages still responsive on 375x812.

## 6. Shadow portfolio (paper trading)

- [ ] Can record a paper BUY from the symbol detail page — pre-trade checklist enforced.
- [ ] Shadow holdings endpoint (`GET /shadow/holdings`) returns the new position.
- [ ] P&L mark-to-market updates when new candle arrives.
- [ ] Closing the paper position enforces the post-mortem checklist.

## 7. Journal

- [ ] Pre-trade checklist (`docs/checklists/pre_trade.md`) enforced server-side — request
      fails 422 if any required item missing.
- [ ] Post-mortem checklist (`docs/checklists/post_mortem.md`) enforced on close.
- [ ] At least 3 journal entries exist (one open, one closed-winner, one closed-loser —
      paper money only).

## 8. Alerts & morning brief

- [ ] Morning-brief Prefect flow runs 07:30 IST and produces markdown output.
- [ ] `GET /agent/morning-brief?date=YYYY-MM-DD` returns the rendered content.
- [ ] If Telegram is configured: alert delivered to the dedicated chat ID.

## 9. Observability

- [ ] Sentry has captured at least one real error in the past week and it was triaged.
- [ ] Uptime Kuma SLA 99% for the Stage 1 ingest flow over the last 7 days.
- [ ] MLflow contains the first dummy experiment (placeholder until Stage 4 models).

## 10. Backups still green

- [ ] 7 consecutive nightly backups completed.
- [ ] First quarterly restore drill completed and signed off in `ONBOARDING.md`.

## 11. Docs & tracker

- [ ] `docs/ONBOARDING.md` section 1 updated to "Stage 1 — <market> live".
- [ ] Tracker updated for Stage 1 completion.
- [ ] Any new `TODO(user)` tags added to `PLACEHOLDERS.md` with owner + date.

---

**Sign-off:**

```
Stage 1 signed off by: ______________________   Date: ____________
Starting market:       ______________________
Next milestone:        Stage 2 — additional markets or regime classifier upgrade
```
