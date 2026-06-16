"""Tests for MarkovSwitchingDetector.

Covers the fallback path (always available without statsmodels) and the
interface contract expected by the scoring harness and Phase-2 regime upgrade.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.core.contracts import Regime
from pfip.regime.markov_switching import MarkovSwitchingDetector, MSRegimeResult


def _synthetic_prices(n: int = 400, seed: int = 13) -> pd.Series:
    """Prices from two clearly-separated return regimes."""
    rng = np.random.default_rng(seed)
    bull = rng.normal(0.0008, 0.008, n // 2)
    bear = rng.normal(-0.0006, 0.015, n - n // 2)
    returns = np.concatenate([bull, bear])
    prices = 100 * np.exp(np.cumsum(returns))
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.Series(prices, index=idx)


class TestMarkovSwitchingDetector:
    def test_fit_returns_self(self):
        prices = _synthetic_prices()
        det = MarkovSwitchingDetector()
        assert det.fit(prices) is det

    def test_score_per_bar_type(self):
        prices = _synthetic_prices()
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        assert isinstance(result, MSRegimeResult)

    def test_regime_index_aligned(self):
        prices = _synthetic_prices()
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        # Regime series length may be one shorter (log-return drops first row).
        assert len(result.regime) >= len(prices) - 2

    def test_regime_values_are_valid(self):
        prices = _synthetic_prices()
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        valid = {r.value for r in Regime}
        unique = set(result.regime.unique())
        assert unique <= valid, f"unexpected regime labels: {unique - valid}"

    def test_confidence_bounded(self):
        prices = _synthetic_prices()
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        assert (result.confidence >= 0).all()
        assert (result.confidence <= 1).all()

    def test_filtered_probs_sum_to_one(self):
        prices = _synthetic_prices()
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        row_sums = result.filtered_probs.sum(axis=1)
        # Should be close to 1 for every bar (exact for rule-based, approximate
        # for statsmodels if numerical rounding occurs).
        assert (row_sums - 1.0).abs().max() < 0.01

    def test_filtered_prob_feature_columns(self):
        prices = _synthetic_prices()
        det = MarkovSwitchingDetector(k_regimes=3).fit(prices)
        feat = det.filtered_prob_feature()
        assert all(c.startswith("ms_prob_state") for c in feat.columns)
        assert len(feat.columns) == 3

    def test_latest_regime_returns_tuple(self):
        prices = _synthetic_prices()
        regime, conf = MarkovSwitchingDetector().fit(prices).latest_regime()
        assert isinstance(regime, Regime)
        assert 0.0 <= conf <= 1.0

    def test_score_before_fit_raises(self):
        det = MarkovSwitchingDetector()
        with pytest.raises(RuntimeError):
            det.score_per_bar()

    def test_too_few_obs_uses_fallback(self):
        prices = _synthetic_prices(n=30)
        result = MarkovSwitchingDetector().fit(prices).score_per_bar()
        assert result.method == "rule_based"

    def test_deterministic(self):
        prices = _synthetic_prices()
        r1 = MarkovSwitchingDetector().fit(prices).latest_regime()
        r2 = MarkovSwitchingDetector().fit(prices).latest_regime()
        assert r1[0] == r2[0]
