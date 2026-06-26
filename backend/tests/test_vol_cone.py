"""Tests for the optional Chronos vol-cone (pfip.vol.cone).

CI has no torch/chronos, so these exercise the **dormant** path: graceful
soft-import and the historical-vol fallback. The Chronos inference path only
runs when the optional deps are installed (not asserted here).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pfip.vol.cone import (
    VolCone,
    chronos_available,
    forecast_vol_cone,
    historical_annual_vol,
)


def _synthetic_prices(daily_sigma: float, n: int = 300, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, daily_sigma, n)
    return pd.Series(100.0 * np.exp(np.cumsum(rets)))


def test_chronos_available_is_bool_and_never_raises():
    # Soft-import must degrade gracefully whether or not torch/chronos exist.
    assert isinstance(chronos_available(), bool)


def test_historical_annual_vol_in_expected_range():
    # daily sigma 0.01 -> annual ~ 0.01 * sqrt(252) ~ 0.159
    v = historical_annual_vol(_synthetic_prices(0.01))
    assert v is not None
    assert 0.10 < v < 0.22


def test_historical_annual_vol_none_when_too_short():
    assert historical_annual_vol(pd.Series([100.0, 101.0, 102.0])) is None


def test_forecast_vol_cone_falls_back_to_historical():
    cone = forecast_vol_cone(_synthetic_prices(0.012, seed=1))
    assert isinstance(cone, VolCone)
    # Without torch/chronos this is "historical"; with it, "chronos" — both valid.
    assert cone.source in ("historical", "chronos")
    assert cone.annual_vol > 0
    assert cone.as_dict()["source"] == cone.source


def test_forecast_vol_cone_none_on_insufficient_data():
    assert forecast_vol_cone(pd.Series([100.0, 101.0])) is None
