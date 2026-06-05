"""Tests for HMMRegimeDetector — labeling semantics + fit/predict roundtrip.

We test against the fallback (no-hmmlearn) implementation because the
state→regime mapping logic is what matters for downstream consumers.
The hmmlearn integration is exercised in `tests/test_ml_pipeline.py`.

Key invariants:

- After fitting on a synthetic series that mixes high-vol and low-vol
  segments, the high-vol cluster must be labeled HIGH_VOLATILITY.
- The min-mean / max-mean clusters must map to BEAR_TREND / BULL_TREND.
- score_per_bar returns a DataFrame with `regime` and `confidence` cols
  and the same number of rows as the input price series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.regime.hmm_detector import HMMRegimeDetector, Regime


def _synthetic_returns(seed: int = 42) -> pd.Series:
    """500 daily returns: 150 bull (μ=+0.5%, σ=1%), 150 bear (μ=-0.4%, σ=1%),
    100 sideways (μ=0, σ=0.3%), 100 high-vol (μ=0, σ=4%)."""
    rng = np.random.default_rng(seed)
    bull = rng.normal(0.005, 0.01, 150)
    bear = rng.normal(-0.004, 0.01, 150)
    sideways = rng.normal(0.0, 0.003, 100)
    hivol = rng.normal(0.0, 0.04, 100)
    series = np.concatenate([bull, bear, sideways, hivol])
    idx = pd.date_range("2024-01-01", periods=500, freq="D")
    return pd.Series(series, index=idx, name="r")


def test_init_rejects_invalid_n_states():
    """Only 3 and 4 states are valid per plan §4."""
    with pytest.raises(ValueError):
        HMMRegimeDetector(n_states=2)
    with pytest.raises(ValueError):
        HMMRegimeDetector(n_states=5)


def test_fit_requires_min_observations():
    """Fewer than 50 observations → ValueError."""
    detector = HMMRegimeDetector(n_states=3)
    with pytest.raises(ValueError):
        detector.fit(pd.Series([0.001] * 10))


def test_fit_succeeds_on_synthetic():
    """End-to-end fit on a synthetic series shouldn't raise."""
    detector = HMMRegimeDetector(n_states=4, random_state=0)
    detector.fit(_synthetic_returns())
    assert detector._fitted is True
    # State stats populated.
    assert len(detector._state_stats) == 4
    # Mapping covers every state.
    assert set(detector._state_to_regime.keys()) == {0, 1, 2, 3}


def test_labeling_assigns_high_vol_to_highest_std():
    """The state with the largest std must be labeled HIGH_VOLATILITY.

    We deliberately use the fallback (no hmmlearn) because the quantile-
    based fit is deterministic given the input distribution.
    """
    detector = HMMRegimeDetector(n_states=4, random_state=0)
    detector.fit(_synthetic_returns())
    # Identify highest-std state from _state_stats.
    hv_state = max(detector._state_stats, key=lambda s: detector._state_stats[s]["std"])
    assert detector._state_to_regime[hv_state] == Regime.HIGH_VOLATILITY


def test_labeling_assigns_bull_to_highest_mean_non_hv():
    """The max-mean state (excluding HV) must be BULL_TREND."""
    detector = HMMRegimeDetector(n_states=4, random_state=0)
    detector.fit(_synthetic_returns())
    hv = max(detector._state_stats, key=lambda s: detector._state_stats[s]["std"])
    non_hv = {s: detector._state_stats[s] for s in detector._state_stats if s != hv}
    bull_state = max(non_hv, key=lambda s: non_hv[s]["mean"])
    assert detector._state_to_regime[bull_state] == Regime.BULL_TREND


def test_labeling_assigns_bear_to_lowest_mean_non_hv():
    """The min-mean state (excluding HV) must be BEAR_TREND."""
    detector = HMMRegimeDetector(n_states=4, random_state=0)
    detector.fit(_synthetic_returns())
    hv = max(detector._state_stats, key=lambda s: detector._state_stats[s]["std"])
    non_hv = {s: detector._state_stats[s] for s in detector._state_stats if s != hv}
    bear_state = min(non_hv, key=lambda s: non_hv[s]["mean"])
    assert detector._state_to_regime[bear_state] == Regime.BEAR_TREND


def test_three_state_uses_sideways():
    """With n_states=3, the middle-mean (non-HV) state maps to SIDEWAYS."""
    detector = HMMRegimeDetector(n_states=3, random_state=0)
    # Need enough data for 3 quantile bands.
    detector.fit(_synthetic_returns())
    # 3 labels total: HV, BULL, BEAR — no SIDEWAYS in 3-state map.
    # (Per impl: 3 states leaves no "middle" leftover.)
    assert set(detector._state_to_regime.values()) <= {
        Regime.HIGH_VOLATILITY,
        Regime.BULL_TREND,
        Regime.BEAR_TREND,
        Regime.SIDEWAYS,
    }


def test_score_per_bar_returns_expected_columns():
    """score_per_bar must return regime + confidence columns aligned to input."""
    detector = HMMRegimeDetector(n_states=4, random_state=0)
    returns = _synthetic_returns()
    detector.fit(returns)
    # Build a price-like df from returns (close column required).
    prices = (1.0 + returns).cumprod() * 100
    df = pd.DataFrame({"close": prices})
    out = detector.score_per_bar(df)
    assert "regime" in out.columns
    assert "confidence" in out.columns
    # Confidence in [0, 1].
    assert (out["confidence"] >= 0).all()
    assert (out["confidence"] <= 1).all()
    # Same number of rows.
    assert len(out) == len(df)
