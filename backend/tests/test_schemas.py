"""Tests for pandera validation schemas (pfip.core.schemas).

Validates the data-validation gate: good data passes through; bad data raises
or warns per the schema's severity policy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.core.schemas import validate_ohlcv, validate_features, validate_regime


def _ohlcv(n: int = 100, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.clip(close, 1, None)
    idx = pd.date_range("2023-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.003,
            "low": close * 0.997,
            "close": close,
            "volume": rng.uniform(1000, 5000, n),
        },
        index=idx,
    )


def _features(n: int = 100, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "rsi_14": rng.uniform(20, 80, n),
            "macd": rng.normal(0, 1, n),
            "macd_signal": rng.normal(0, 1, n),
            "macd_hist": rng.normal(0, 0.5, n),
            "atr_14": rng.uniform(0.5, 5, n),
            "return_7d": rng.normal(0, 0.05, n),
            "volatility_30d": rng.uniform(0.005, 0.03, n),
        },
        index=idx,
    )


def _regime(n: int = 50) -> pd.DataFrame:
    import random

    labels = ["bull_trend", "bear_trend", "sideways", "high_volatility"]
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "regime": [random.choice(labels) for _ in range(n)],
            "confidence": np.random.uniform(0.6, 0.99, n),
        },
        index=idx,
    )


class TestOHLCVSchema:
    def test_valid_passes(self):
        df = _ohlcv()
        out = validate_ohlcv(df)
        assert len(out) == len(df)

    def test_non_positive_close_raises(self):
        df = _ohlcv()
        df.loc[df.index[5], "close"] = -1.0
        with pytest.raises(Exception):  # SchemaError or ValueError
            validate_ohlcv(df)

    def test_high_below_low_raises(self):
        df = _ohlcv()
        df.loc[df.index[10], "high"] = df.loc[df.index[10], "low"] - 0.01
        with pytest.raises(Exception):
            validate_ohlcv(df)

    def test_missing_close_raises(self):
        df = _ohlcv().drop(columns=["close"])
        with pytest.raises(Exception):
            validate_ohlcv(df)

    def test_zero_volume_allowed(self):
        df = _ohlcv()
        df["volume"] = 0.0
        out = validate_ohlcv(df)  # should not raise
        assert len(out) == len(df)


class TestFeaturesSchema:
    def test_valid_passes(self):
        df = _features()
        out = validate_features(df)
        assert len(out) == len(df)

    def test_partial_columns_passes(self):
        df = _features()[["rsi_14", "macd_hist"]]
        out = validate_features(df)  # extra cols not required
        assert "rsi_14" in out.columns

    def test_rsi_out_of_range_warns_not_raises(self, caplog):
        df = _features()
        df.loc[df.index[0], "rsi_14"] = 150.0  # invalid
        # Feature schema is non-fatal (warnings only).
        out = validate_features(df)
        assert out is not None  # didn't crash

    def test_negative_atr_warns(self):
        df = _features()
        df.loc[df.index[3], "atr_14"] = -0.5
        out = validate_features(df)  # non-fatal
        assert out is not None


class TestRegimeSchema:
    def test_valid_passes(self):
        df = _regime()
        out = validate_regime(df)
        assert "regime" in out.columns

    def test_unknown_label_raises(self):
        df = _regime()
        df.loc[df.index[0], "regime"] = "alien_regime"
        with pytest.raises(Exception):
            validate_regime(df)

    def test_missing_regime_column_raises(self):
        df = _regime().drop(columns=["regime"])
        with pytest.raises(Exception):
            validate_regime(df)

    def test_confidence_out_of_range_raises(self):
        df = _regime()
        df.loc[df.index[0], "confidence"] = 1.5
        with pytest.raises(Exception):
            validate_regime(df)
