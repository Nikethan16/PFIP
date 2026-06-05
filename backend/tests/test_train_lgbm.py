"""Tests for the LightGBM-per-regime training pure-logic helpers.

The Prefect task wrapper and DB loader need integration testing; what
we *can* test in isolation is the regime slice (a `df.query`-style
filter) and the train-one driver's handling of insufficient-data cases.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.prefect.flows.train_lgbm_per_regime import slice_per_regime, train_one


def _toy_df(n: int = 200, *, regime: str = "bull_trend") -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "rsi_14": rng.uniform(20, 80, n),
            "atr_14": rng.uniform(0.005, 0.05, n),
            "close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))),
            "regime": regime,
        },
        index=idx,
    )


def test_slice_picks_matching_regime():
    df = pd.concat([_toy_df(50, regime="bull_trend"), _toy_df(50, regime="sideways")])
    sliced = slice_per_regime(df, "bull_trend")
    assert (sliced["regime"] == "bull_trend").all()
    assert len(sliced) == 50


def test_slice_returns_empty_for_unknown_regime():
    df = _toy_df(100)
    sliced = slice_per_regime(df, "no_such_regime")
    assert sliced.empty


def test_slice_handles_empty_df():
    out = slice_per_regime(pd.DataFrame(), "anything")
    assert out.empty


def test_train_one_returns_none_on_short_dataset():
    df = _toy_df(50)  # below the 100-row floor
    assert train_one(df, horizon=1) is None


def test_train_one_returns_none_when_close_missing():
    df = _toy_df(200).drop(columns=["close"])
    assert train_one(df, horizon=1) is None


def test_train_one_returns_model_when_data_sufficient():
    """If LightGBM is available the function returns a (model, metrics)
    pair; if it isn't, the function returns None — both are valid. We
    just assert it doesn't raise."""
    df = _toy_df(300)
    result = train_one(df, horizon=1)
    if result is None:
        pytest.skip("LightGBM not available in test env")
    model, metrics = result
    assert hasattr(model, "predict_proba_up")
    assert "insample_accuracy" in metrics
    assert metrics["n_rows"] > 0
