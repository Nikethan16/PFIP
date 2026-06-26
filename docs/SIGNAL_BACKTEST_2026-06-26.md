# Signal Backtest — Walk-Forward Directional Edge (2026-06-26)

_Run: `python -m scripts.backtest_signals` against live Neon data. This measures
the **model's** out-of-sample skill over all history (no vectorbt, no matured
live signals required) — the honest "do the signals predict?" check._

## Method
For each watchlist symbol, replayed the production path (`compute_features` →
regime-routed `LGBMBaselineModel` → `walk_forward_train`) with a **252-bar (1y)
train window**, 21-day step, 21-day test, 5-day embargo, collecting every
out-of-sample `(proba_up, y@t+3)` holdout pair. No leakage: each prediction comes
from a model fit only on prior data.

- **hit_rate** — directional accuracy (proba>0.5 vs realised up/down at t+3).
- **base_rate** — naive majority-class accuracy (the bar to beat).
- **edge** — `hit_rate − base_rate` (honest out-of-sample skill).
- **brier** — probability calibration error (0.25 = coin-flip reference; lower better).

## Result — aggregate (16 symbols, 5,943 predictions)

| Metric | Value |
|---|---|
| Weighted hit-rate | **0.519** |
| Weighted base-rate | **0.549** |
| **Weighted edge** | **−0.030** |
| Weighted Brier | **0.335** |
| Symbols with positive edge | **6 / 16** |

## Per-symbol

| Symbol | n | hit | base | edge | brier | regime |
|---|---|---|---|---|---|---|
| BTC-USD | 84 | 0.559 | 0.536 | **+0.024** | 0.285 | bear |
| ETH-USD | 84 | 0.476 | 0.524 | −0.048 | 0.360 | sideways |
| SOL-USD | 378 | 0.537 | 0.503 | **+0.034** | 0.312 | bear |
| BNB-USD | 126 | 0.460 | 0.548 | −0.087 | 0.379 | sideways |
| XRP-USD | 420 | 0.543 | 0.552 | −0.009 | 0.334 | sideways |
| SPY | 441 | 0.521 | 0.610 | −0.088 | 0.324 | bull |
| QQQ | 441 | 0.556 | 0.617 | −0.061 | 0.314 | bull |
| AAPL | 441 | 0.510 | 0.569 | −0.059 | 0.337 | bull |
| NVDA | 441 | 0.515 | 0.565 | −0.050 | 0.320 | sideways |
| MSFT | 441 | 0.544 | 0.524 | **+0.020** | 0.339 | bear |
| RELIANCE.NS | 441 | 0.454 | 0.546 | −0.093 | 0.378 | sideways |
| TCS.NS | 441 | 0.497 | 0.590 | −0.093 | 0.339 | sideways |
| HDFCBANK.NS | 441 | 0.521 | 0.501 | **+0.020** | 0.312 | sideways |
| INFY.NS | 441 | 0.497 | 0.526 | −0.029 | 0.340 | bull |
| ICICIBANK.NS | 441 | 0.528 | 0.512 | **+0.016** | 0.361 | sideways |
| NIFTYBEES.NS | 441 | 0.540 | 0.524 | **+0.016** | 0.339 | sideways |

## Interpretation (honest)

1. **No demonstrated directional edge.** Aggregate edge is **−3.0%** — the model
   underperforms a naive "always predict the majority direction" baseline, and
   Brier (0.335) is worse than a coin flip (0.25). The 6 positive-edge symbols
   are small (+1.6% to +3.4%) and not clearly distinguishable from noise.
2. **This was expected.** `ML_SIGNAL_RESEARCH.md` §1 called it: *"daily-return
   direction is near-random; no model family reliably beats a calibrated GBM
   here. The honest edge is in volatility / scenario / regime, not
   point-direction."* The backtest confirms it on our own data.
3. **The pipeline is sound; the target is hard.** Feature engineering, regime
   routing, walk-forward, and calibration all work — daily *direction* is just
   not predictable enough to beat the base rate. The base rates themselves are
   high (e.g. SPY/QQQ 0.61) because trending assets have a dominant up-direction;
   "always up" is a strong, hard-to-beat baseline in a bull window.

## Recommendation

- **Treat the directional signals as experimental / advisory only** — they are
  clearly labelled advisory in the UI, which is appropriate; do **not** act on
  them as if they had proven edge. Consider whether to keep `FEATURE_ML_SIGNALS`
  on (advisory, with this caveat documented) or gate it off again until an edge
  is shown — an operator decision.
- **Redirect ML effort to where the edge is** (per the research doc): the
  **Chronos-Bolt vol-cone / scenario prior** for the Goals & stress pages, and
  the **FinBERT news-sentiment feature**, rather than chasing daily direction.
- **Re-run after more history / a regime change** — edge can be regime-dependent;
  the bear-regime crypto names (BTC/SOL) were the only consistently positive
  ones, which is worth watching.

_Reproduce: `cd ~/pfip/backend && PYTHONPATH=$PWD ./.venv/bin/python -m scripts.backtest_signals`._
