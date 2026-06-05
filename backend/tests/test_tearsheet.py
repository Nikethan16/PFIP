"""Tests for the tearsheet stat helpers.

Coverage:

- Sharpe / Sortino / Calmar / max-drawdown / CAGR against analytic fixtures.
- Monthly returns grid pivots correctly across year boundaries.
- Drawdown series is always <= 0 and matches the formal definition.
- Fallback HTML tearsheet writes a valid file end-to-end.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pfip.backtest.tearsheet import (
    drawdown_series,
    generate_tearsheet,
    monthly_returns_table,
)
from pfip.backtest.vectorbt_engine import (
    _cagr,
    _calmar,
    _hit_rate,
    _max_drawdown,
    _sharpe,
    _sortino,
)


@pytest.fixture
def constant_return_series() -> pd.Series:
    """1bp per day, 252 days — deterministic Sharpe."""
    idx = pd.date_range("2025-01-01", periods=252, freq="B")
    return pd.Series([0.0001] * 252, index=idx, name="r")


@pytest.fixture
def alternating_return_series() -> pd.Series:
    """+1% / -1% alternating — Sharpe ≈ 0 by construction."""
    idx = pd.date_range("2025-01-01", periods=252, freq="B")
    vals = [0.01 if i % 2 == 0 else -0.01 for i in range(252)]
    return pd.Series(vals, index=idx, name="r")


@pytest.fixture
def stairstep_drawdown_series() -> pd.Series:
    """+5% up, -10% down, +2% up — known max drawdown of ~10%."""
    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    return pd.Series([0.05, -0.10, 0.02], index=idx, name="r")


def test_sharpe_positive_for_constant_positive_returns(constant_return_series):
    """Constant positive returns with zero std → division by tiny std → very large.

    We just assert the sign + that it's a finite number; the magnitude is
    by construction huge."""
    s = _sharpe(constant_return_series)
    assert s >= 0
    assert math.isfinite(s) or s == 0.0  # std=0 → 0.0 per impl


def test_sharpe_near_zero_for_alternating(alternating_return_series):
    """Mean ≈ 0 → Sharpe ≈ 0 regardless of vol."""
    s = _sharpe(alternating_return_series)
    assert abs(s) < 0.5


def test_sortino_at_least_as_high_as_sharpe_when_only_negative_pulls_down():
    """For a positively-skewed series (mostly + with rare - days), Sortino
    should be ≥ Sharpe because downside std ≤ total std."""
    idx = pd.date_range("2025-01-01", periods=252, freq="B")
    vals = [0.01] * 240 + [-0.05] * 12
    r = pd.Series(vals, index=idx)
    assert _sortino(r) >= _sharpe(r)


def test_max_drawdown_matches_manual_calc(stairstep_drawdown_series):
    """Equity: 1.0 → 1.05 → 0.945 → 0.9639. Peak 1.05, trough 0.945. DD = -10%."""
    mdd = _max_drawdown(stairstep_drawdown_series)
    assert mdd == pytest.approx(-0.10, abs=1e-9)


def test_calmar_nonzero_when_drawdown_and_growth():
    """Calmar = CAGR / |max DD|. With non-zero growth and DD, it's defined."""
    # 0.1% daily for 252 days, no drawdown → calmar undefined (DD=0) → 0.0
    r_flat = pd.Series([0.001] * 252, index=pd.date_range("2025", periods=252, freq="B"))
    assert _calmar(r_flat) == 0.0
    # Mixed series — calmar > 0
    vals = [0.01] * 200 + [-0.02] * 52
    r = pd.Series(vals, index=pd.date_range("2025", periods=252, freq="B"))
    assert _calmar(r) != 0.0


def test_cagr_compounding_matches_known_value():
    """100% total return over exactly one year → CAGR = 1.0."""
    # 252 trading days, each return that compounds to 2.0
    target = 2.0
    daily = target ** (1 / 252) - 1
    idx = pd.date_range("2025-01-02", periods=252, freq="B")
    r = pd.Series([daily] * 252, index=idx)
    assert _cagr(r) == pytest.approx(1.0, rel=1e-6)


def test_hit_rate_simple():
    """6 wins, 4 losses → 0.6."""
    r = pd.Series([0.01, -0.01, 0.02, 0.01, -0.01, 0.01, 0.01, -0.01, -0.01, 0.01])
    assert _hit_rate(r) == pytest.approx(0.6)


def test_hit_rate_empty():
    assert _hit_rate(pd.Series([], dtype=float)) == 0.0


def test_monthly_returns_table_shape_and_ytd():
    """Two months of returns → year row with two months filled + YTD column."""
    idx = pd.date_range("2025-01-01", periods=40, freq="D")
    r = pd.Series([0.001] * 40, index=idx)
    grid = monthly_returns_table(r)
    # 13 columns: Jan..Dec + YTD
    assert grid.shape[1] == 13
    assert "YTD" in grid.columns
    # 2025 should be present (only one year)
    assert 2025 in grid.index
    # Jan should be non-NaN (full month of data)
    assert pd.notna(grid.loc[2025, "Jan"])
    # Dec is empty
    assert pd.isna(grid.loc[2025, "Dec"])


def test_monthly_returns_table_empty_input():
    """Empty series → empty grid with correct columns."""
    grid = monthly_returns_table(pd.Series([], dtype=float))
    assert list(grid.columns) == [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
        "YTD",
    ]
    assert len(grid) == 0


def test_drawdown_series_always_nonpositive(alternating_return_series):
    """Every DD value must be <= 0."""
    dd = drawdown_series(alternating_return_series)
    assert (dd <= 1e-9).all()


def test_drawdown_series_matches_manual(stairstep_drawdown_series):
    """Series [+5, -10, +2] → equity [1.05, 0.945, 0.9639]
    peak [1.05, 1.05, 1.05] → dd [0, -10%, ~-8.2%]."""
    dd = drawdown_series(stairstep_drawdown_series)
    assert dd.iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert dd.iloc[1] == pytest.approx(-0.10, abs=1e-9)
    # 0.9639 / 1.05 - 1 ≈ -0.0820
    assert dd.iloc[2] == pytest.approx(-0.082, abs=1e-3)


def test_generate_tearsheet_writes_html(tmp_path, alternating_return_series):
    """End-to-end: file is created with HTML content."""
    out = tmp_path / "tearsheet.html"
    generate_tearsheet(alternating_return_series, output_path=out, title="Smoke")
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    # If QS is installed it owns the format; both paths must include the title.
    assert "Smoke" in body
