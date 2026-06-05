"""Tests for the pure-logic pieces of `train_lgbm_per_regime`.

The flow itself touches Prefect + DB so we don't exercise it end-to-end
here. We test:

- `slice_per_regime` correctly partitions a wide df by regime label.
- `make_label` produces the forward-looking up/down binary signal with
  correct NaN handling at the tail.
- `train_one` returns None for under-sized inputs (so the flow can skip
  cleanly without depending on lightgbm).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pfip.prefect.flows.train_lgbm_per_regime import slice_per_regime, train_one
from pfip.signals.lgbm_baseline import make_label


def test_slice_per_regime_returns_only_matching_rows():
    df = pd.DataFrame(
        {
            "close": [100, 101, 102, 103, 104],
            "regime": ["bull_trend", "sideways", "bull_trend", "bear_trend", "bull_trend"],
            "feat_a": [1, 2, 3, 4, 5],
        }
    )
    bulls = slice_per_regime(df, "bull_trend")
    assert len(bulls) == 3
    assert list(bulls["feat_a"]) == [1, 3, 5]


def test_slice_per_regime_empty_input():
    """Empty df → empty df without raising."""
    out = slice_per_regime(pd.DataFrame(), "bull_trend")
    assert out.empty


def test_slice_per_regime_missing_column():
    """No 'regime' column → empty slice, no exception."""
    df = pd.DataFrame({"close": [1, 2, 3]})
    assert slice_per_regime(df, "bull_trend").empty


def test_make_label_horizon_3_basic():
    """Rising series → label all 1 for indices that have a forward window."""
    close = pd.Series([100, 101, 102, 103, 104, 105], dtype=float)
    labels = make_label(close, horizon=3)
    # Indices 0..2 have a valid forward shift; should be 1 (up).
    assert labels.iloc[0] == 1
    assert labels.iloc[1] == 1
    assert labels.iloc[2] == 1
    # Last `horizon` rows are NaN.
    assert pd.isna(labels.iloc[-1])
    assert pd.isna(labels.iloc[-2])
    assert pd.isna(labels.iloc[-3])


def test_make_label_horizon_3_falling():
    """Strictly falling series → label all 0 (no future > current)."""
    close = pd.Series([110, 105, 100, 95, 90], dtype=float)
    labels = make_label(close, horizon=2)
    assert labels.iloc[0] == 0
    assert labels.iloc[1] == 0
    assert labels.iloc[2] == 0
    assert pd.isna(labels.iloc[-1])
    assert pd.isna(labels.iloc[-2])


def test_make_label_equal_treated_as_down():
    """Equal future == current → 0 (we use strict `>`)."""
    close = pd.Series([100, 100, 100, 100], dtype=float)
    labels = make_label(close, horizon=1)
    assert labels.iloc[0] == 0
    assert labels.iloc[1] == 0
    assert labels.iloc[2] == 0


def test_train_one_returns_none_on_undersized_input():
    """train_one bails on <100 rows; the flow logs and continues."""
    df = pd.DataFrame(
        {
            "close": np.arange(50.0),
            "regime": ["bull_trend"] * 50,
            "feat_a": np.arange(50.0),
        }
    )
    assert train_one(df, horizon=3) is None


def test_train_one_returns_none_when_no_close():
    df = pd.DataFrame({"feat_a": [1, 2, 3]})
    assert train_one(df, horizon=3) is None


def test_train_one_returns_none_on_empty():
    assert train_one(pd.DataFrame(), horizon=3) is None
