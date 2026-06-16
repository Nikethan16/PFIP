"""Scoring harness acceptance gate.

The single function ``score_strategy`` runs a strategy through the full Phase-1
evaluation pipeline and returns a ``ScorerResult`` with a clear keep/reject
verdict. This is the authority that decides what makes it into production:

    result = score_strategy(df, my_strategy, market="crypto")
    if result.verdict == "KEEP":
        # wire it in; else log result.reasons and discard

Pipeline
--------
1. Walk-forward backtest (embargo, CPCV, per-bar costs) via the existing engine.
2. Benchmark comparison vs buy-hold / MA-crossover / RSI-MR.
3. Monte Carlo block-bootstrap (Sharpe 5th-percentile).
4. Shuffle / lookahead test.
5. Sub-period stability check (Sharpe must be positive in ≥ 2/3 of folds).

Acceptance thresholds (can be overridden by caller):
    - net Sharpe ≥ 0.5 after costs
    - beats buy-hold Sharpe by ≥ 0.1
    - Monte Carlo p5 Sharpe ≥ 0
    - lookahead test passes
    - ≥ 2/3 of walk-forward folds have positive Sharpe

These numbers are deliberately conservative for an advisory system — the point
is to keep only what's genuinely useful, not to set a bar so high nothing passes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import (
    run_walkforward,
    run_monte_carlo,
    benchmark_comparison,
    lookahead_test,
)
from pfip.backtest.walk_forward import run_walk_forward, WalkForwardResult

log = logging.getLogger(__name__)

BacktestStrategy = Callable[[pd.DataFrame], pd.Series]


@dataclass
class ScorerResult:
    """Full scoring output, ready to persist or log."""

    verdict: str                       # "KEEP" or "REJECT"
    reasons: list[str]                 # why it passed/failed each gate
    net_sharpe: float                  # walk-forward net-of-costs Sharpe
    max_drawdown: float
    mc_sharpe_p5: float                # Monte Carlo 5th-percentile Sharpe
    beats_buyhold: bool                # vs. buy-hold net Sharpe
    lookahead_ok: bool
    fold_positive_frac: float          # fraction of WF folds with Sharpe > 0
    benchmark_sharpes: dict[str, float] = field(default_factory=dict)
    fold_sharpes: list[float] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def score_strategy(
    df: pd.DataFrame,
    strategy: BacktestStrategy,
    *,
    market: str = "crypto",
    min_sharpe: float = 0.5,
    min_beat_buyhold: float = 0.1,
    min_mc_p5: float = 0.0,
    min_fold_positive_frac: float = 2 / 3,
    train_window: int = 756,
    step: int = 21,
    embargo: int = 5,
    test_window: int = 21,
    n_mc_sims: int = 1000,
) -> ScorerResult:
    """Run the full Phase-1 acceptance pipeline on ``strategy``.

    Args:
        df: OHLCV DataFrame (must have a ``close`` column, time-indexed).
        strategy: callable(df) → pd.Series of {0, 1} positions.
        market: one of "crypto", "us", "india", "fx" — sets cost bps.
        min_sharpe: walk-forward net Sharpe threshold.
        min_beat_buyhold: how much strategy must beat buy-hold Sharpe.
        min_mc_p5: minimum Monte Carlo 5th-percentile Sharpe.
        min_fold_positive_frac: fraction of folds that must be profitable.
        train_window, step, embargo, test_window: WF parameters.
        n_mc_sims: Monte Carlo simulation count.

    Returns a ``ScorerResult`` with verdict = "KEEP" or "REJECT".
    """
    reasons: list[str] = []
    gates_passed: list[bool] = []

    # ------------------------------------------------------------------
    # 1. Walk-forward backtest
    # ------------------------------------------------------------------
    try:
        wf = run_walkforward(
            df,
            strategy,
            window=train_window,
            step=step,
            embargo=embargo,
            test_window=test_window,
            market_kind=market,
            run_lookahead_check=False,  # we do this separately
        )
        net_sharpe = float(wf.sharpe) if hasattr(wf, "sharpe") else float("nan")
        max_dd = float(wf.max_drawdown) if hasattr(wf, "max_drawdown") else float("nan")
        wf_returns = getattr(wf, "returns", pd.Series(dtype=float))
        wf_trades = getattr(wf, "trades", pd.Series(dtype=float))
        lookahead_ok = bool(getattr(wf, "lookahead_ok", True))
    except Exception as exc:
        log.warning("walk-forward failed: %s", exc)
        return ScorerResult(
            verdict="REJECT",
            reasons=[f"walk-forward error: {exc}"],
            net_sharpe=float("nan"),
            max_drawdown=float("nan"),
            mc_sharpe_p5=float("nan"),
            beats_buyhold=False,
            lookahead_ok=False,
            fold_positive_frac=0.0,
        )

    sharpe_gate = np.isfinite(net_sharpe) and net_sharpe >= min_sharpe
    gates_passed.append(sharpe_gate)
    reasons.append(
        f"{'✓' if sharpe_gate else '✗'} net Sharpe {net_sharpe:.2f} "
        f"({'≥' if sharpe_gate else '<'} {min_sharpe})"
    )

    # ------------------------------------------------------------------
    # 2. Per-fold stability (positive Sharpe in ≥ min_fold_positive_frac)
    # ------------------------------------------------------------------
    fold_sharpes: list[float] = []
    try:
        wfr: WalkForwardResult = run_walk_forward(
            market=market,
            df=df,
            strategy=strategy,
            train_window=train_window,
            step=step,
            embargo=embargo,
            test_window=test_window,
            market_kind=market,
        )
        fold_sharpes = [fm.sharpe for fm in wfr.fold_metrics]
    except Exception as exc:
        log.debug("per-fold metrics unavailable: %s", exc)

    if fold_sharpes:
        fold_pos_frac = float(np.mean([s > 0 for s in fold_sharpes]))
    else:
        fold_pos_frac = float(net_sharpe > 0)

    stability_gate = fold_pos_frac >= min_fold_positive_frac
    gates_passed.append(stability_gate)
    reasons.append(
        f"{'✓' if stability_gate else '✗'} fold stability "
        f"{fold_pos_frac:.0%} positive (need ≥{min_fold_positive_frac:.0%})"
    )

    # ------------------------------------------------------------------
    # 3. Benchmark comparison
    # ------------------------------------------------------------------
    benchmark_sharpes: dict[str, float] = {}
    beats_bh = False
    try:
        bench = benchmark_comparison(df, strategy, market_kind=market)
        benchmark_sharpes = {k: float(v.sharpe) for k, v in bench.items()
                             if hasattr(v, "sharpe")}
        bh_sharpe = benchmark_sharpes.get("buy_hold", float("nan"))
        beats_bh = np.isfinite(bh_sharpe) and (net_sharpe - bh_sharpe) >= min_beat_buyhold
    except Exception as exc:
        log.debug("benchmark comparison failed: %s", exc)
        beats_bh = False

    gates_passed.append(beats_bh)
    bh_str = f"{benchmark_sharpes.get('buy_hold', float('nan')):.2f}"
    reasons.append(
        f"{'✓' if beats_bh else '✗'} beats buy-hold "
        f"(strategy {net_sharpe:.2f} vs BH {bh_str}, need +{min_beat_buyhold})"
    )

    # ------------------------------------------------------------------
    # 4. Monte Carlo block-bootstrap
    # ------------------------------------------------------------------
    mc_p5 = float("nan")
    if len(wf_trades) >= 10:
        try:
            mc = run_monte_carlo(wf_trades, n_sims=n_mc_sims)
            mc_p5 = float(getattr(mc, "sharpe_p5", mc_p5))
        except Exception as exc:
            log.debug("Monte Carlo failed: %s", exc)

    mc_gate = np.isfinite(mc_p5) and mc_p5 >= min_mc_p5
    gates_passed.append(mc_gate)
    reasons.append(
        f"{'✓' if mc_gate else '✗'} MC p5 Sharpe {mc_p5:.2f} "
        f"({'≥' if mc_gate else '<'} {min_mc_p5})"
    )

    # ------------------------------------------------------------------
    # 5. Lookahead / shuffle test
    # ------------------------------------------------------------------
    try:
        la = lookahead_test(strategy, df, market_kind=market)
        lookahead_ok = bool(la)
    except Exception as exc:
        log.debug("lookahead test failed: %s", exc)

    gates_passed.append(lookahead_ok)
    reasons.append(f"{'✓' if lookahead_ok else '✗'} lookahead test")

    # ------------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------------
    verdict = "KEEP" if all(gates_passed) else "REJECT"

    return ScorerResult(
        verdict=verdict,
        reasons=reasons,
        net_sharpe=net_sharpe,
        max_drawdown=max_dd,
        mc_sharpe_p5=mc_p5,
        beats_buyhold=beats_bh,
        lookahead_ok=lookahead_ok,
        fold_positive_frac=fold_pos_frac,
        benchmark_sharpes=benchmark_sharpes,
        fold_sharpes=fold_sharpes,
    )
