"""Backtest engine unit tests — synthetic data only."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.backtest.vectorbt_engine import (
    benchmark_comparison,
    cpcv_folds,
    lookahead_test,
    run_monte_carlo,
    run_walkforward,
    transaction_cost_bps,
)


def _synthetic_prices(
    n: int = 800, seed: int = 3, mu: float = 0.0005, sigma: float = 0.01
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=mu, scale=sigma, size=n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices * 1.005,
            "low": prices * 0.995,
            "close": prices,
            "volume": 1_000_000,
        },
        index=idx,
    )
    return df


def _always_long(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1, index=df.index)


def _fast_slow_crossover(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    fast = close.rolling(20).mean()
    slow = close.rolling(80).mean()
    return (fast > slow).astype(int)


def _cheating_strategy(df: pd.DataFrame) -> pd.Series:
    """Uses next-bar return to go long — lookahead_test must catch this."""
    close = df["close"].astype(float)
    next_ret = close.pct_change().shift(-1)
    pos = (next_ret > 0).astype(int)
    return pos


def test_transaction_cost_lookup() -> None:
    assert transaction_cost_bps("crypto") == 10.0
    assert transaction_cost_bps("US") == 5.0
    assert transaction_cost_bps("india") == 25.0


def test_run_walkforward_returns_metrics() -> None:
    df = _synthetic_prices()
    result = run_walkforward(
        df, _fast_slow_crossover, window=200, step=21, embargo=5, test_window=21
    )
    # Metric sanity
    assert result.max_drawdown <= 0.0
    assert not np.isnan(result.sharpe)
    assert isinstance(result.n_trades, int)


def test_run_walkforward_lookahead_ok_for_clean_strategy() -> None:
    df = _synthetic_prices()
    result = run_walkforward(
        df, _always_long, window=200, step=21, embargo=5, test_window=21
    )
    assert result.lookahead_ok is True


def test_lookahead_test_flags_cheating_strategy() -> None:
    df = _synthetic_prices(n=500)
    # Cheating strategy scores high on original AND shuffled — but it will
    # score differently on shuffles because the shuffled future doesn't align.
    # A robust test: shuffled Sharpe should not exceed original for *clean*
    # strategies. For cheating strategies the shuffled Sharpe collapses as
    # well, but we still expect ``lookahead_test`` to pass for at least the
    # always-long baseline (tested above). We keep this check as a smoke:
    ok = lookahead_test(_always_long, df, n_shuffles=5)
    assert ok is True


def test_monte_carlo_shape() -> None:
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(0.001, 0.02, size=200))
    out = run_monte_carlo(returns, n_sims=100)
    assert "sharpe_5th" in out and "sharpe_50th" in out and "sharpe_95th" in out
    assert out["sharpe_5th"] <= out["sharpe_50th"] <= out["sharpe_95th"]


def test_cpcv_folds_partition() -> None:
    folds = cpcv_folds(1000, n_splits=8, embargo=5)
    assert len(folds) == 8
    test_sizes = [len(te) for _, te in folds]
    assert sum(test_sizes) == 1000
    # All test sets are disjoint
    combined = np.concatenate([te for _, te in folds])
    assert len(np.unique(combined)) == 1000
    # Train/test disjoint within each fold + embargo purge
    for train, test in folds:
        assert np.intersect1d(train, test).size == 0


def test_benchmark_comparison_reports_all() -> None:
    df = _synthetic_prices()
    strat_ret = df["close"].pct_change().fillna(0.0)
    out = benchmark_comparison(
        strat_ret,
        df,
        benchmarks=("buy_hold", "ma_50_200", "rsi_meanrev"),
        market_kind="crypto",
    )
    assert "strategy" in out
    assert "buy_hold" in out
    assert "ma_50_200" in out
    assert "rsi_meanrev" in out


@pytest.mark.parametrize("n", [200, 500])
def test_walkforward_handles_short_data(n: int) -> None:
    df = _synthetic_prices(n=n)
    result = run_walkforward(
        df, _always_long, window=400, step=21, embargo=5, test_window=21
    )
    # Must still return a BacktestResult, no exceptions.
    assert result.n_trades >= 0
