"""Unit tests for ``pfip.features.technicals.compute_features``."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.features.technicals import compute_features


def _synthetic_ohlcv(n: int = 120, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """Synthetic OHLCV with a deterministic upward trend.

    Close rises by ``step`` each bar. High/low are +/- 0.5 of close. Volume is constant.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = start + np.arange(n) * step
    df = pd.DataFrame(
        {
            "open": close - step / 2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        },
        index=idx,
    )
    return df


def test_compute_features_columns() -> None:
    df = _synthetic_ohlcv(120)
    feats = compute_features(df)
    assert list(feats.columns) == [
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "atr_14",
        "return_7d",
        "volatility_30d",
    ]
    assert len(feats) == len(df)


def test_compute_features_values_on_trend() -> None:
    """On a pure uptrend, RSI should saturate near 100 and 7d return is positive."""
    df = _synthetic_ohlcv(120)
    feats = compute_features(df)

    # After enough bars, RSI-14 on a pure uptrend must be at the ceiling.
    rsi_tail = feats["rsi_14"].dropna().iloc[-1]
    assert rsi_tail == pytest.approx(100.0, abs=1e-6)

    # 7d return on a pure uptrend is strictly positive (log(close / close.shift(7)) > 0).
    ret = feats["return_7d"].dropna()
    assert (ret > 0).all()

    # Volatility of a linear series of returns is small but finite.
    vol = feats["volatility_30d"].dropna()
    assert (vol >= 0).all()


def test_compute_features_empty_input() -> None:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    feats = compute_features(df)
    assert feats.empty
    assert list(feats.columns) == [
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "atr_14",
        "return_7d",
        "volatility_30d",
    ]


def test_compute_features_missing_column_raises() -> None:
    df = pd.DataFrame({"open": [1.0], "close": [1.0]})
    with pytest.raises(ValueError, match="missing required column"):
        compute_features(df)
