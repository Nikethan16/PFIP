"""Walk-forward backtest API.

Thin, spec-named wrapper around :func:`pfip.backtest.vectorbt_engine.run_walkforward`
that exposes the function signature required by the build plan:

    run_walk_forward(market, df, strategy_or_model, horizon=...)
        -> WalkForwardResult

It also tracks per-fold metrics (Sharpe, max DD, hit rate, average return) and
runs a CPCV pass alongside the rolling walk-forward, returning a
``pd.DataFrame`` of predictions + ground truth + period as the spec requires.

This keeps :mod:`vectorbt_engine` the single source of truth for the heavy
maths; this file just orchestrates and shapes the outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import (
    BacktestResult,
    BacktestStrategy,
    cpcv_folds,
    lookahead_test,
    run_monte_carlo,
    run_walkforward,
    transaction_cost_bps,
    _apply_strategy,
    _calmar,
    _hit_rate,
    _max_drawdown,
    _sharpe,
    _sortino,
)

log = logging.getLogger(__name__)


@dataclass
class FoldMetric:
    """One fold's summary."""

    fold: int
    start_idx: int
    end_idx: int
    sharpe: float
    max_drawdown: float
    hit_rate: float
    avg_return: float
    n_trades: int


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward output."""

    market: str
    horizon: int
    fold_metrics: list[FoldMetric] = field(default_factory=list)
    aggregate: BacktestResult | None = None
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    cpcv_metrics: dict[str, float] = field(default_factory=dict)
    lookahead_ok: bool = True

    def summary(self) -> dict[str, Any]:
        if self.aggregate is None:
            return {"market": self.market, "horizon": self.horizon, "status": "empty"}
        out = self.aggregate.to_dict()
        out.update(
            {
                "market": self.market,
                "horizon": self.horizon,
                "n_folds": len(self.fold_metrics),
                "cpcv_mean_sharpe": self.cpcv_metrics.get("mean_sharpe"),
            }
        )
        return out


def run_walk_forward(
    *,
    market: str,
    df: pd.DataFrame,
    strategy: BacktestStrategy,
    horizon: int = 3,
    train_window: int = 756,
    step: int = 21,
    test_window: int = 21,
    embargo: int = 5,
    market_kind: str = "crypto",
    n_cpcv_splits: int = 8,
) -> WalkForwardResult:
    """Run the full walk-forward + CPCV pass and return aggregated results.

    Parameters
    ----------
    market : str
        Label used for output metadata.
    df : pd.DataFrame
        OHLCV bars. Must contain a ``close`` column.
    strategy : Callable
        Plain strategy in :mod:`vectorbt_engine` form
        (``df -> pd.Series[int]`` returning ``{-1, 0, 1}``).
    horizon : int
        Forecast horizon in bars (used for metadata only — the
        ``strategy`` itself is responsible for honoring it).
    """
    if "close" not in df.columns:
        raise ValueError("walk_forward: df must have 'close' column")

    aggregate = run_walkforward(
        df,
        strategy,
        window=train_window,
        step=step,
        embargo=embargo,
        test_window=test_window,
        market_kind=market_kind,
        run_lookahead_check=True,
    )

    # Per-fold metrics — re-walk the index lightly to compute summary stats.
    cost_bps = transaction_cost_bps(market_kind)
    fold_metrics: list[FoldMetric] = []
    pred_pieces: list[pd.DataFrame] = []
    n = len(df)
    start = 0
    fold = 0
    while True:
        train_end = start + train_window
        test_start = train_end + embargo
        test_end = test_start + test_window
        if test_end > n:
            break
        slice_df = df.iloc[start:test_end]
        net_ret, trade_ret = _apply_strategy(slice_df, strategy, cost_bps)
        test_returns = net_ret.iloc[-test_window:]
        fold_metrics.append(
            FoldMetric(
                fold=fold,
                start_idx=int(start),
                end_idx=int(test_end),
                sharpe=_sharpe(test_returns),
                max_drawdown=_max_drawdown(test_returns),
                hit_rate=_hit_rate(trade_ret),
                avg_return=float(test_returns.mean()) if not test_returns.empty else 0.0,
                n_trades=int(len(trade_ret)),
            )
        )

        # Build per-bar predictions row (positions are the "prediction") and
        # collect alongside ground-truth forward returns.
        close = pd.to_numeric(slice_df["close"], errors="coerce").astype(float)
        fwd_ret = close.shift(-horizon) / close - 1.0
        pos = strategy(slice_df).reindex(slice_df.index).fillna(0)
        piece = pd.DataFrame(
            {
                "time": slice_df.index,
                "position": pos.values,
                "fwd_return": fwd_ret.values,
                "y_up": (fwd_ret > 0).astype(int).values,
                "fold": fold,
            }
        )
        # Only keep the test slice.
        piece = piece.iloc[-test_window:]
        pred_pieces.append(piece)

        start += step
        fold += 1

    predictions = pd.concat(pred_pieces, ignore_index=True) if pred_pieces else pd.DataFrame()

    # CPCV summary
    cpcv_metrics: dict[str, float] = {}
    if n >= 100:
        try:
            folds = cpcv_folds(n, n_splits=n_cpcv_splits, embargo=embargo)
            fold_sharpes: list[float] = []
            for _tr_idx, te_idx in folds:
                if len(te_idx) < 5:
                    continue
                test_df = df.iloc[te_idx]
                test_ret, _ = _apply_strategy(test_df, strategy, cost_bps)
                fold_sharpes.append(_sharpe(test_ret))
            if fold_sharpes:
                cpcv_metrics["mean_sharpe"] = float(np.mean(fold_sharpes))
                cpcv_metrics["std_sharpe"] = float(
                    np.std(fold_sharpes, ddof=1) if len(fold_sharpes) > 1 else 0.0
                )
                cpcv_metrics["min_sharpe"] = float(np.min(fold_sharpes))
                cpcv_metrics["max_sharpe"] = float(np.max(fold_sharpes))
        except Exception as exc:  # pragma: no cover
            log.warning("cpcv pass failed: %s", exc)

    return WalkForwardResult(
        market=market,
        horizon=horizon,
        fold_metrics=fold_metrics,
        aggregate=aggregate,
        predictions=predictions,
        cpcv_metrics=cpcv_metrics,
        lookahead_ok=aggregate.lookahead_ok,
    )
