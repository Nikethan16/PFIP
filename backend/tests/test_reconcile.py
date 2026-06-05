"""Tests for the cross-source reconciliation finder.

We feed synthetic PriceObservation rows and assert the divergence list
matches the expected pairs.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pfip.ingest._common.reconcile import (
    PriceObservation,
    reconcile_latest_closes,
)


def _obs(symbol: str, source: str, close: float) -> PriceObservation:
    return PriceObservation(
        symbol=symbol,
        source=source,
        ts=datetime(2026, 5, 29, 0, 0, tzinfo=timezone.utc),
        close=close,
    )


def test_no_divergence_when_sources_agree():
    obs = [
        _obs("BTC-USD", "coinbase", 70000.0),
        _obs("BTC-USD", "kraken", 70030.0),  # 0.04% diff
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.005)
    assert out == []


def test_divergence_flagged_above_threshold():
    """5% diff well above the 0.5% threshold → must surface."""
    obs = [
        _obs("BTC-USD", "coinbase", 70000.0),
        _obs("BTC-USD", "kraken", 73500.0),
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.005)
    assert len(out) == 1
    d = out[0]
    assert d.symbol == "BTC-USD"
    # Higher close listed first.
    assert d.source_a == "kraken"
    assert d.source_b == "coinbase"
    assert d.diff_pct > 0


def test_threshold_respected():
    """A 0.3% diff is under the 0.5% threshold → not flagged."""
    obs = [
        _obs("BTC-USD", "coinbase", 70000.0),
        _obs("BTC-USD", "kraken", 70210.0),  # ~0.3%
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.005)
    assert out == []


def test_single_source_symbol_skipped():
    """A symbol with only one source has nothing to compare."""
    obs = [_obs("RARE", "yfinance", 10.0)]
    out = reconcile_latest_closes(obs, threshold_pct=0.005)
    assert out == []


def test_multi_source_combinatorial_pairs():
    """Three sources → up to 3 pairwise comparisons."""
    obs = [
        _obs("X", "a", 100.0),
        _obs("X", "b", 110.0),  # +10% vs a
        _obs("X", "c", 90.0),  # -10% vs a, -18% vs b
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.005)
    # Three pairs: (a,b), (a,c), (b,c) — all above 0.5%.
    assert len(out) == 3


def test_sorted_by_abs_diff_descending():
    """Largest divergence first."""
    obs = [
        _obs("X", "a", 100.0),
        _obs("X", "b", 100.5),  # 0.5%
        _obs("X", "c", 150.0),  # 50%
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.001)
    assert len(out) >= 2
    assert abs(out[0].diff_pct) >= abs(out[-1].diff_pct)


def test_zero_price_does_not_explode():
    """Both sources reporting 0 → diff_pct=0, no crash."""
    obs = [
        _obs("X", "a", 0.0),
        _obs("X", "b", 0.0),
    ]
    out = reconcile_latest_closes(obs, threshold_pct=0.001)
    assert out == []
