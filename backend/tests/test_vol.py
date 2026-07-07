"""Volatility cone + cost gate — pure math + router smoke."""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from pfip.backtest.cost_gate import cost_gate
from pfip.vol.analytics import vol_cone


def _prices(n: int, daily_ret: float) -> list[float]:
    p = [100.0]
    for _ in range(n):
        p.append(p[-1] * (1 + daily_ret))
    return p


def test_vol_cone_flat_series_low_vol() -> None:
    # Constant up-drift → near-zero realized vol.
    cone = vol_cone(_prices(300, 0.001), windows=(21, 63))
    bucket = next(b for b in cone if b.window_days == 21)
    assert bucket.current is not None
    assert bucket.current < 0.01  # basically no dispersion


def test_vol_cone_reports_percentile_and_distribution() -> None:
    # Alternating returns → meaningful, stable vol; current sits within min/max.
    closes = [100.0]
    for i in range(300):
        closes.append(closes[-1] * (1.02 if i % 2 == 0 else 0.98))
    cone = vol_cone(closes, windows=(21, 63))
    b = next(x for x in cone if x.window_days == 21)
    assert b.current is not None and b.max is not None and b.min is not None
    assert b.min <= b.current <= b.max
    assert 0.0 <= (b.percentile or 0) <= 100.0


def test_vol_cone_insufficient_data_is_empty_bucket() -> None:
    cone = vol_cone([100.0, 101.0, 102.0], windows=(21,))
    assert cone[0].current is None


def test_cost_gate_penalizes_turnover() -> None:
    gross = [0.01, 0.01, 0.01]
    # High turnover + high cost erodes the gross edge.
    res = cost_gate(gross, [1.0, 1.0, 1.0], [0.0, 0.0, 0.0], cost_bps=100.0)
    assert res.net_total_return < res.gross_total_return
    assert res.cost_drag > 0


def test_cost_gate_pass_when_beats_baseline_net() -> None:
    gross = [0.02, 0.02]
    res = cost_gate(gross, [0.0, 0.0], [0.0, 0.0], cost_bps=10.0)
    assert res.beats_baseline is True
    assert res.passes is True


def test_cost_gate_fail_when_below_baseline() -> None:
    res = cost_gate([0.001, 0.001], [1.0, 1.0], [0.05, 0.05], cost_bps=50.0)
    assert res.beats_baseline is False
    assert res.passes is False


def test_vol_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/vol/AAPL").status_code == 401


def test_vol_returns_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/vol/AAPL", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "AAPL"
    assert isinstance(body["cone"], list)
    assert "disclaimer" in body
