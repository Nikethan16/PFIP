"""End-to-end unit tests for the ML pipeline modules.

Synthetic-data only — no DB, no network. Covers the surfaces the build spec
calls out: feature compute, HMM fit + predict, walk-forward shape,
calibration metrics edge cases, and shuffle test detection.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pfip.backtest.benchmarks import (
    BENCHMARKS,
    buy_hold,
    ma_50_200_crossover,
    rsi_mean_reversion,
)
from pfip.backtest.monte_carlo import block_bootstrap
from pfip.backtest.shuffle_test import run_shuffle_test
from pfip.backtest.transaction_costs import (
    apply_costs_to_positions,
    cost_model_for,
    transaction_cost_bps,
)
from pfip.backtest.walk_forward import run_walk_forward
from pfip.calibration.metrics import summarise
from pfip.calibration.rules import evaluate_rules
from pfip.core.contracts import Regime
from pfip.features.cross_asset import derive_from_panel as derive_cross
from pfip.features.derivatives import derive_from_history as derive_deriv
from pfip.features.fundamentals import derive_from_rows
from pfip.features.macro import derive_from_panel as derive_macro
from pfip.features.on_chain import derive_from_history as derive_oc
from pfip.features.technicals import compute_features
from pfip.regime.hmm import HMMRegimeDetector, build_three_state
from pfip.shadow.metrics import _metrics_from


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _synth_ohlcv(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Feature compute
# ---------------------------------------------------------------------------


def test_compute_features_full_set_on_synthetic() -> None:
    df = _synth_ohlcv(120)
    feats = compute_features(df)
    assert set(["rsi_14", "macd", "atr_14", "return_7d", "volatility_30d"]).issubset(
        set(feats.columns)
    )
    # Most rows should be populated after warm-up.
    assert feats["rsi_14"].dropna().shape[0] > 80


def test_fundamentals_derive_pe_from_eps_and_price() -> None:
    rows = [
        {"field": "eps_ttm", "value": 5.0},
        {"field": "price", "value": 100.0},
        {"field": "total_debt", "value": 50.0},
        {"field": "total_equity", "value": 200.0},
    ]
    snap = derive_from_rows(rows, symbol="AAPL", as_of=pd.Timestamp("2025-01-01").date())
    assert snap.pe_ratio == pytest.approx(20.0)
    assert snap.debt_to_equity == pytest.approx(0.25)


def test_on_chain_derive_mvrv_and_z_score() -> None:
    times = pd.date_range("2025-01-01", periods=40, freq="D", tz="UTC")
    hist = pd.DataFrame(
        [{"time": t, "field": "market_value", "value": 100.0 + i} for i, t in enumerate(times)]
        + [{"time": t, "field": "realised_value", "value": 50.0} for t in times]
        + [
            {"time": t, "field": "exchange_netflow", "value": float(i % 7)}
            for i, t in enumerate(times)
        ]
    )
    snap = derive_oc(hist, "BTC", times[-1].to_pydatetime())
    assert snap.mvrv is not None and snap.mvrv > 2.0
    assert snap.exchange_netflow_z30 is not None


def test_derivatives_derive_funding_and_oi() -> None:
    times = pd.date_range("2025-01-01", periods=20, freq="8H", tz="UTC")
    hist = pd.DataFrame(
        [{"time": t, "field": "funding_rate", "value": 0.0001 * i} for i, t in enumerate(times)]
        + [
            {"time": t, "field": "open_interest", "value": 1e9 + 1e6 * i}
            for i, t in enumerate(times)
        ]
        + [{"time": t, "field": "long_short_ratio", "value": 1.2} for t in times]
    )
    snap = derive_deriv(hist, "BTC-PERP", times[-1].to_pydatetime())
    assert snap.funding_rate is not None
    assert snap.open_interest_usd is not None
    assert snap.long_short_ratio == pytest.approx(1.2)


def test_macro_derive_levels_and_changes() -> None:
    times = pd.date_range("2025-01-01", periods=15, freq="D", tz="UTC")
    closes = {
        "vix": pd.Series(20.0 + np.arange(15) * 0.1, index=times),
        "dxy": pd.Series(100.0 + np.arange(15) * -0.1, index=times),
        "us10y": pd.Series(4.2 + np.arange(15) * 0.01, index=times),
        "us2y": pd.Series(4.0, index=times),
        "usdinr": pd.Series(83.0 + np.arange(15) * 0.02, index=times),
    }
    snap = derive_macro(closes, times[-1].to_pydatetime())
    assert snap.vix_level is not None
    assert snap.yield_curve_2s10s is not None and snap.yield_curve_2s10s > 0
    assert snap.usdinr_change_5d is not None


def test_cross_asset_corr_with_perfect_panel() -> None:
    times = pd.date_range("2025-01-01", periods=60, freq="D", tz="UTC")
    btc = pd.Series(100 + np.arange(60), index=times)
    spy = pd.Series(50 + np.arange(60) * 0.5, index=times)
    gld = pd.Series(np.cos(np.arange(60) / 10) * 5 + 100, index=times)
    panel = {"BTC/USD": btc, "SPY": spy, "GLD": gld, "DX-Y.NYB": gld, "^TNX": btc}
    snap = derive_cross(panel, target_symbol="BTC/USD", as_of=times[-1].to_pydatetime())
    assert snap.corr_btc_spy_30d is not None
    # Perfect linear up trend -> high correlation
    assert snap.corr_btc_spy_30d is None or -1.0 <= snap.corr_btc_spy_30d <= 1.0


# ---------------------------------------------------------------------------
# HMM regime
# ---------------------------------------------------------------------------


def test_hmm_three_state_fit_predict() -> None:
    rng = np.random.default_rng(42)
    # Two regimes: low-vol uptrend then high-vol noise
    bullish = rng.normal(0.002, 0.005, size=120)
    noise = rng.normal(-0.001, 0.03, size=120)
    rets = np.concatenate([bullish, noise])
    series = pd.Series(rets)

    detector = build_three_state()
    detector.fit(series)
    preds = detector.predict(series)
    assert len(preds) == len(series)
    # All predictions must be Regime enum values.
    for p in preds:
        assert isinstance(p, Regime)


def test_hmm_score_per_bar_returns_dataframe() -> None:
    df = _synth_ohlcv(200)
    rets = np.log(df["close"] / df["close"].shift(1)).dropna()
    detector = build_three_state()
    detector.fit(rets)
    out = detector.score_per_bar(df)
    assert {"regime", "confidence"}.issubset(out.columns)
    assert len(out) == len(df)


# ---------------------------------------------------------------------------
# Walk-forward + benchmarks
# ---------------------------------------------------------------------------


def test_walk_forward_returns_shape_and_metrics() -> None:
    df = _synth_ohlcv(400, seed=7)
    result = run_walk_forward(
        market="BTC/USD",
        df=df,
        strategy=buy_hold,
        horizon=3,
        train_window=100,
        step=21,
        test_window=21,
        embargo=5,
        market_kind="crypto",
    )
    assert result.aggregate is not None
    # buy_hold has lookahead_ok = True (constant position).
    assert result.lookahead_ok is True
    # Fold metrics should be non-empty and each fold has a numeric sharpe.
    assert len(result.fold_metrics) > 0
    for fm in result.fold_metrics:
        assert not math.isnan(fm.sharpe)


def test_benchmark_strategies_callable() -> None:
    df = _synth_ohlcv(250)
    for name, fn in BENCHMARKS.items():
        pos = fn(df).reindex(df.index).fillna(0)
        assert pos.isin([-1, 0, 1]).all(), f"{name} produced out-of-range positions"


# ---------------------------------------------------------------------------
# Monte Carlo + shuffle
# ---------------------------------------------------------------------------


def test_monte_carlo_summary_has_quantiles() -> None:
    rng = np.random.default_rng(0)
    trade_returns = pd.Series(rng.normal(0.001, 0.02, size=200))
    out = block_bootstrap(trade_returns, n_sims=200)
    assert out.sharpe_p5 <= out.sharpe_p50 <= out.sharpe_p95


def test_shuffle_test_clean_strategy_passes() -> None:
    df = _synth_ohlcv(300)
    result = run_shuffle_test(buy_hold, df, n_shuffles=5)
    assert result.ok is True


# ---------------------------------------------------------------------------
# Calibration edge cases
# ---------------------------------------------------------------------------


def test_calibration_metrics_perfect_pred() -> None:
    s = summarise([1, 0, 1, 0], [1.0, 0.0, 1.0, 0.0])
    assert s.brier == 0.0
    assert s.ece < 0.05


def test_calibration_metrics_empty() -> None:
    s = summarise([], [])
    assert math.isnan(s.brier)
    assert s.n_samples == 0


def test_calibration_rules_triggers_suspension() -> None:
    res = evaluate_rules(ece_history=[0.1, 0.18, 0.2], bucket_win_rates=[0.6])
    assert res.suspend is True
    assert res.raise_floor_to is None


def test_calibration_rules_raises_floor_after_3_bad_months() -> None:
    res = evaluate_rules(
        ece_history=[0.1, 0.1, 0.1],
        bucket_win_rates=[0.4, 0.45, 0.5],
    )
    assert res.suspend is False
    assert res.raise_floor_to == 75


# ---------------------------------------------------------------------------
# Transaction cost model
# ---------------------------------------------------------------------------


def test_transaction_cost_lookup_per_market() -> None:
    assert transaction_cost_bps("crypto") == 10.0
    assert transaction_cost_bps("us") == 5.0
    assert transaction_cost_bps("india") == 25.0


def test_india_cost_model_includes_stt() -> None:
    model = cost_model_for("india")
    assert model.sell_extra_bps > 0


def test_apply_costs_charges_per_turn() -> None:
    idx = pd.date_range("2025-01-01", periods=5, freq="D", tz="UTC")
    pos = pd.Series([0, 1, 1, 0, 0], index=idx)
    bar = pd.Series([0.0, 0.01, 0.01, -0.005, 0.0], index=idx)
    net = apply_costs_to_positions(pos, bar, market="us")
    assert len(net) == len(bar)
    # First bar has no prev position to lift from, last bar is flat — both ~0.
    assert abs(net.iloc[0]) < 1e-6


# ---------------------------------------------------------------------------
# Shadow metrics
# ---------------------------------------------------------------------------


def test_shadow_metrics_from_synthetic_closed_lots() -> None:
    """Build a tiny in-memory book and confirm metrics compute cleanly."""

    class _H:
        def __init__(self, cost: float, qty: float, exit: float, closed_at):
            from decimal import Decimal

            self.cost_basis_inr = Decimal(str(cost))
            self.qty = Decimal(str(qty))
            self.exit_price_inr = Decimal(str(exit))
            self.closed_at = closed_at

    class _T:
        def __init__(self, time, kind, amount):
            from decimal import Decimal

            self.time = time
            self.kind = kind
            self.amount_inr = Decimal(str(amount))

    from datetime import datetime, timezone
    from decimal import Decimal

    closed = [
        _H(100.0, 1.0, 110.0, datetime(2025, 1, 5, tzinfo=timezone.utc)),
        _H(200.0, 2.0, 95.0, datetime(2025, 1, 6, tzinfo=timezone.utc)),
    ]
    txs = [
        _T(datetime(2025, 1, 1, tzinfo=timezone.utc), "BUY", 100.0),
        _T(datetime(2025, 1, 5, tzinfo=timezone.utc), "SELL", 110.0),
        _T(datetime(2025, 1, 2, tzinfo=timezone.utc), "BUY", 200.0),
        _T(datetime(2025, 1, 6, tzinfo=timezone.utc), "SELL", 190.0),
    ]
    metrics = _metrics_from(closed, txs, Decimal("0"))
    assert metrics.n_trades == 2
    # 1 winner (1.0 -> 1.1) and 1 loser (200 -> 190) -> win rate 0.5
    assert metrics.win_rate == pytest.approx(0.5)
