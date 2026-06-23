"""Tests for live portfolio vs benchmark (pfip.portfolio.benchmark)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from pfip.portfolio.benchmark import compare_series


def _series(start_val: float, daily_growth: float, n: int = 400):
    """A (date, value) series compounding at ``daily_growth`` per day."""
    out = []
    v = start_val
    d = date(2025, 1, 1)
    for i in range(n):
        out.append((d + timedelta(days=i), v))
        v *= 1 + daily_growth
    return out


# ---------------------------------------------------------------------------
# compare_series
# ---------------------------------------------------------------------------


def test_excess_positive_when_portfolio_outperforms():
    port = _series(100, 0.001)  # faster growth
    bench = _series(100, 0.0005)  # slower
    res = compare_series(port, bench, windows=("1Y",))
    assert res["1Y"]["portfolio_return"] > res["1Y"]["benchmark_return"]
    assert res["1Y"]["excess_return"] > 0


def test_excess_negative_when_underperforming():
    port = _series(100, 0.0002)
    bench = _series(100, 0.001)
    res = compare_series(port, bench, windows=("1Y",))
    assert res["1Y"]["excess_return"] < 0


def test_all_windows_present():
    port = _series(100, 0.0008)
    bench = _series(100, 0.0008)
    res = compare_series(port, bench)
    for w in ("1M", "3M", "YTD", "1Y", "Max"):
        assert w in res


def test_identical_series_zero_excess():
    s = _series(100, 0.0008)
    res = compare_series(s, list(s), windows=("1M",))
    assert res["1M"]["excess_return"] == pytest.approx(0.0, abs=1e-9)


def test_insufficient_history_is_none():
    res = compare_series([(date(2025, 1, 1), 100.0)], [(date(2025, 1, 1), 100.0)])
    assert res["1M"]["portfolio_return"] is None
    assert res["1M"]["excess_return"] is None


def test_one_month_return_uses_recent_window():
    # 0.1%/day for ~30 days ≈ 3% over 1M.
    port = _series(100, 0.001)
    bench = _series(100, 0.0)
    res = compare_series(port, bench, windows=("1M",))
    assert res["1M"]["portfolio_return"] == pytest.approx(0.03, abs=0.01)


def test_zero_start_value_is_none():
    port = [(date(2025, 1, 1), 0.0), (date(2025, 6, 1), 100.0)]
    bench = _series(100, 0.0005)
    res = compare_series(port, bench, windows=("Max",))
    assert res["Max"]["portfolio_return"] is None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_benchmark_requires_auth(client: TestClient):
    assert client.get("/api/v1/portfolio/benchmark").status_code == 401


def test_benchmark_endpoint_graceful_without_data(client: TestClient, auth_headers: dict[str, str]):
    # Fake DB ⇒ no OHLCV; endpoint should still 200 with a note, not crash.
    resp = client.get("/api/v1/portfolio/benchmark?symbol=NIFTY%2050", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["benchmark"] == "NIFTY 50"
    assert "windows" in body
    assert body["note"] is not None  # no data ⇒ explanatory note
