"""Tests for the change-point regime detector.

These run against the pure-numpy fallback (always available) and the public
interface contract. When ``ruptures`` is installed the same assertions hold —
the detector just uses PELT internally.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pfip.regime.change_point import (
    ChangePointDetector,
    ChangePointResult,
    _binseg_l2,
    detect_change_points,
)


def _two_regime_prices(n: int = 300, seed: int = 7) -> pd.Series:
    """Steady up-drift then a steady down-drift — one clear mean break at n/2.

    The two halves share the same volatility but have opposite-sign means, so
    the break is a *mean* shift — which the pure-numpy L2 fallback detects
    (and ``ruptures`` detects too). A variance-only break would need the
    ``ruptures`` rbf cost, which isn't guaranteed to be installed.
    """
    rng = np.random.default_rng(seed)
    # Strong, low-noise separation so the mean break is unambiguous for the
    # pure-numpy L2 fallback (which can otherwise wander tens of points at high
    # return-noise levels).
    up = rng.normal(0.005, 0.004, n // 2)
    down = rng.normal(-0.005, 0.004, n - n // 2)
    returns = np.concatenate([up, down])
    prices = 100 * np.exp(np.cumsum(returns))
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return pd.Series(prices, index=idx)


def test_returns_result_type():
    res = detect_change_points(_two_regime_prices())
    assert isinstance(res, ChangePointResult)


def test_detects_a_break_on_regime_shift():
    res = detect_change_points(_two_regime_prices())
    assert res.n_changepoints >= 1
    assert res.last_change_index is not None


def test_break_located_near_the_true_join():
    # The synthetic mean break is at the midpoint of the *returns* series (~150).
    # The high-noise series can produce several breaks; require that at least
    # one of them lands near the true join (generous window for the fallback).
    res = detect_change_points(_two_regime_prices(n=300))
    assert res.breakpoints
    assert any(120 <= b <= 180 for b in res.breakpoints), res.breakpoints


def test_days_since_change_is_populated_with_datetime_index():
    res = detect_change_points(_two_regime_prices())
    assert res.days_since_change is not None
    assert res.days_since_change >= 0
    assert res.last_change_at is not None


def test_too_few_observations_returns_empty():
    prices = pd.Series(
        100 + np.arange(10, dtype=float),
        index=pd.date_range("2022-01-01", periods=10, freq="D"),
    )
    res = detect_change_points(prices)
    assert res.n_changepoints == 0
    assert res.last_change_index is None


def test_flat_series_has_no_breaks():
    prices = pd.Series(
        np.full(200, 100.0),
        index=pd.date_range("2022-01-01", periods=200, freq="D"),
    )
    res = detect_change_points(prices)
    assert res.n_changepoints == 0


def test_higher_penalty_yields_no_more_breaks():
    prices = _two_regime_prices()
    few = detect_change_points(prices, penalty=10.0).n_changepoints
    many = detect_change_points(prices, penalty=1e-6).n_changepoints
    assert few <= many


def test_result_before_fit_raises():
    det = ChangePointDetector()
    try:
        det.result()
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError before fit()")


def test_binseg_fallback_finds_mean_shift():
    # Deterministic step in the mean: 0s then 5s. The split should sit at 50.
    x = np.concatenate([np.zeros(50), np.full(50, 5.0)])
    breaks = _binseg_l2(x, penalty=1.0, min_size=10)
    assert breaks
    assert abs(breaks[0] - 50) <= 2


def test_deterministic():
    prices = _two_regime_prices()
    a = detect_change_points(prices)
    b = detect_change_points(prices)
    assert a.breakpoints == b.breakpoints
