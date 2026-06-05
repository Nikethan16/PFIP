"""Benchmark strategies for backtest comparisons.

Three canonical benchmarks per the spec (M5):
    * buy-and-hold
    * 50/200 moving-average crossover
    * RSI mean-reversion (period 14, thresholds 30 / 70)

Each is exposed as a strategy callable (``df -> pd.Series[int]`` in {-1, 0, 1})
that can be passed to ``run_walkforward`` or ``run_walk_forward``.
"""

from __future__ import annotations

from typing import Callable, Iterable

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import (
    BacktestStrategy,
    _apply_strategy,
    _max_drawdown,
    _sharpe,
    benchmark_comparison as _engine_benchmark_comparison,
    transaction_cost_bps,
)


def buy_hold(df: pd.DataFrame) -> pd.Series:
    """Always long."""
    return pd.Series(1, index=df.index)


def ma_50_200_crossover(df: pd.DataFrame) -> pd.Series:
    """Long when 50-day MA crosses above 200-day MA, flat otherwise."""
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    fast = close.rolling(50).mean()
    slow = close.rolling(200).mean()
    return (fast > slow).astype(int)


def rsi_mean_reversion(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Long < 30 / short > 70 / flat otherwise."""
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    diff = close.diff()
    up = diff.clip(lower=0).rolling(period).mean()
    down = (-diff.clip(upper=0)).rolling(period).mean()
    rs = up / (down + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    pos = pd.Series(0, index=df.index)
    pos[rsi < 30] = 1
    pos[rsi > 70] = -1
    return pos


BENCHMARKS: dict[str, BacktestStrategy] = {
    "buy_hold": buy_hold,
    "ma_50_200": ma_50_200_crossover,
    "rsi_meanrev": rsi_mean_reversion,
}


def compare_to_benchmarks(
    strategy_returns: pd.Series,
    df: pd.DataFrame,
    *,
    market_kind: str = "crypto",
    benchmarks: Iterable[str] = ("buy_hold", "ma_50_200", "rsi_meanrev"),
) -> dict[str, dict[str, float]]:
    """Compute the strategy's headline stats alongside the named benchmarks."""
    return _engine_benchmark_comparison(
        strategy_returns,
        df,
        benchmarks=benchmarks,
        market_kind=market_kind,
    )
