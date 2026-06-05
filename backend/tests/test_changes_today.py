"""Tests for the z-score helper used by /api/v1/changes-today.

The DB-backed endpoint is exercised in integration tests; here we pin
the pure-math piece that decides whether a mover is significant."""

from __future__ import annotations

import numpy as np
import pytest

from pfip.api.changes_today import _zscore


def test_zero_when_series_too_short():
    """Fewer than 5 prior obs → 0.0, regardless of current value."""
    assert _zscore([0.01, 0.02, 0.01], 0.10) == 0.0


def test_zero_when_constant_history():
    """std == 0 → 0.0 (avoids div-by-zero)."""
    assert _zscore([0.01, 0.01, 0.01, 0.01, 0.01, 0.01], 0.05) == 0.0


def test_positive_z_for_above_mean():
    rets = [0.0, 0.005, -0.005, 0.0, 0.001, -0.001]
    current = 0.05  # ~big positive
    z = _zscore(rets, current)
    assert z > 0


def test_negative_z_for_below_mean():
    rets = [0.0, 0.005, -0.005, 0.0, 0.001, -0.001]
    current = -0.05
    z = _zscore(rets, current)
    assert z < 0


def test_5_sigma_event_returns_large_z():
    """Inject a return ~5 stdevs from the mean — must return |z| >= 4."""
    rng = np.random.default_rng(0)
    rets = rng.normal(0, 0.01, 200).tolist()
    current = 0.05  # 5σ event since sigma=0.01
    z = _zscore(rets, current)
    assert abs(z) >= 4.0


def test_nans_in_history_are_ignored():
    rets = [0.01, float("nan"), 0.02, float("nan"), 0.01, 0.015, 0.005]
    z = _zscore(rets, 0.5)
    # Should not crash; should produce a non-zero value.
    assert isinstance(z, float)
    assert z != 0.0
