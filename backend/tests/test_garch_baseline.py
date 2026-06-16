"""Tests for GarchVolForecaster and evaluate_vol_forecast.

Tests run against both the GARCH path (if arch is installed) and the EWMA
fallback. The invariants that matter to the scoring harness:
  - VolForecast.sigma_forecast is positive and finite
  - sigma_path has the same index as the input returns
  - evaluate_vol_forecast returns RMSE and n_folds when given enough data
  - the result is stable across repeated calls (deterministic)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.vol.garch import GarchVolForecaster, VolForecast, evaluate_vol_forecast


def _daily_returns(n: int = 600, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    # Two-vol-regime synthetic: first half quiet, second half noisy.
    quiet = rng.normal(0.0002, 0.008, n // 2)
    noisy = rng.normal(-0.0001, 0.025, n - n // 2)
    r = np.concatenate([quiet, noisy])
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.Series(r, index=idx)


class TestGarchFit:
    def test_returns_self(self):
        r = _daily_returns()
        gf = GarchVolForecaster()
        assert gf.fit(r) is gf

    def test_method_set(self):
        r = _daily_returns()
        gf = GarchVolForecaster().fit(r)
        assert gf._method in ("garch", "ewma")

    def test_forecast_positive_finite(self):
        r = _daily_returns()
        fc: VolForecast = GarchVolForecaster().fit(r).forecast(horizon=5)
        assert isinstance(fc, VolForecast)
        assert fc.sigma_forecast > 0
        assert np.isfinite(fc.sigma_forecast)

    def test_sigma_path_length(self):
        r = _daily_returns()
        fc = GarchVolForecaster().fit(r).forecast()
        assert len(fc.sigma_path) == len(r)

    def test_sigma_path_positive(self):
        r = _daily_returns()
        fc = GarchVolForecaster().fit(r).forecast()
        assert (fc.sigma_path > 0).all()

    def test_deterministic(self):
        r = _daily_returns()
        fc1 = GarchVolForecaster().fit(r).forecast(horizon=3)
        fc2 = GarchVolForecaster().fit(r).forecast(horizon=3)
        assert fc1.sigma_forecast == pytest.approx(fc2.sigma_forecast, rel=1e-6)

    def test_ewma_fallback_few_obs(self):
        r = _daily_returns(n=50)
        gf = GarchVolForecaster().fit(r)
        assert gf._method == "ewma"
        fc = gf.forecast()
        assert fc.method == "ewma"
        assert fc.sigma_forecast > 0

    def test_forecast_before_fit_raises(self):
        with pytest.raises(RuntimeError):
            GarchVolForecaster().forecast()

    def test_handles_nan_returns(self):
        r = _daily_returns()
        r.iloc[10:15] = np.nan
        fc = GarchVolForecaster().fit(r).forecast()
        assert np.isfinite(fc.sigma_forecast)

    def test_sigma_daily_units(self):
        r = _daily_returns()
        fc = GarchVolForecaster().fit(r).forecast()
        # Daily sigma should be << 1; annualised would be sigma * sqrt(252).
        assert fc.sigma_forecast < 0.5


class TestEvaluateVolForecast:
    def test_returns_dict(self):
        r = _daily_returns()
        result = evaluate_vol_forecast(r, train_window=252, step=63)
        assert isinstance(result, dict)

    def test_n_folds_positive(self):
        r = _daily_returns()
        result = evaluate_vol_forecast(r, train_window=252, step=63)
        assert result.get("n_folds", 0) > 0

    def test_rmse_finite_positive(self):
        r = _daily_returns()
        result = evaluate_vol_forecast(r, train_window=252, step=63)
        assert "rmse" in result
        assert np.isfinite(result["rmse"]) and result["rmse"] >= 0

    def test_beats_naive_key_present(self):
        r = _daily_returns()
        result = evaluate_vol_forecast(r, train_window=252, step=63)
        assert "beats_naive" in result

    def test_too_short_returns_empty(self):
        r = _daily_returns(n=20)
        result = evaluate_vol_forecast(r, train_window=252, step=21)
        assert result.get("n_folds", 0) == 0
