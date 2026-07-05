"""Tests for the consolidated net-worth timeline (pfip.portfolio.networth)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from pfip.core.contracts import Holding, HoldingCategory
from pfip.portfolio.networth import build_networth


def _h(symbol, category, qty, cost):
    return Holding(
        category=category,
        symbol=symbol,
        acquired_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        qty=Decimal(qty),
        cost_basis_inr=Decimal(cost),
    )


def test_priced_holding_marks_to_close():
    holdings = [_h("BTC/USD", HoldingCategory.CRYPTO_EXCHANGE, "2", "100000")]
    closes = {"BTC/USD": [(date(2025, 1, 1), 60000.0), (date(2025, 1, 2), 70000.0)]}
    out = build_networth(holdings, closes)
    # Latest close 70000 * 2 = 140000.
    assert out["current_inr"] == 140000.0
    assert out["timeline"][-1]["net_worth_inr"] == 140000.0


def test_lot_not_counted_before_acquisition():
    # A position acquired part-way through the price history must not contribute
    # to net worth on dates before it was held. The timeline now STARTS at the
    # first acquisition (no leading zero-run for dates before any holding
    # existed), so the pre-acquisition bar is omitted rather than shown as 0.
    h = Holding(
        category=HoldingCategory.CRYPTO_EXCHANGE,
        symbol="BTC/USD",
        acquired_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        qty=Decimal("1"),
        cost_basis_inr=Decimal("100000"),
    )
    closes = {"BTC/USD": [(date(2025, 1, 1), 60000.0), (date(2025, 1, 2), 70000.0)]}
    out = build_networth([h], closes)
    tl = {row["date"]: row["net_worth_inr"] for row in out["timeline"]}
    assert "2025-01-01" not in tl  # before acquisition → not in the series at all
    assert tl["2025-01-02"] == 70000.0  # held now, marked to close


def test_flat_lot_not_counted_before_acquisition():
    # Illiquid (cost-basis) lots are likewise gated on their acquisition date.
    priced = Holding(
        category=HoldingCategory.EQUITY,
        symbol="X",
        acquired_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        qty=Decimal("1"),
        cost_basis_inr=Decimal("100"),
    )
    fd = Holding(
        category=HoldingCategory.FD,
        symbol=None,
        acquired_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        qty=Decimal("1"),
        cost_basis_inr=Decimal("500000"),
    )
    closes = {"X": [(date(2025, 1, 1), 100.0), (date(2025, 1, 2), 100.0)]}
    out = build_networth([priced, fd], closes)
    tl = {row["date"]: row["net_worth_inr"] for row in out["timeline"]}
    assert tl["2025-01-01"] == 100.0  # FD not opened yet
    assert tl["2025-01-02"] == 500100.0  # FD now included


def test_illiquid_held_at_cost_basis():
    holdings = [
        _h(None, HoldingCategory.PPF, "1", "500000"),
        _h("FDX", HoldingCategory.FD, "1", "200000"),
    ]
    out = build_networth(holdings, {})
    assert out["current_inr"] == 700000.0
    assert out["breakdown_inr"]["ppf"] == 500000.0
    assert out["breakdown_inr"]["fd"] == 200000.0


def test_mixed_book_combines_priced_and_flat():
    holdings = [
        _h("BTC/USD", HoldingCategory.CRYPTO_EXCHANGE, "1", "100000"),
        _h(None, HoldingCategory.PPF, "1", "500000"),
    ]
    closes = {"BTC/USD": [(date(2025, 1, 1), 120000.0)]}
    out = build_networth(holdings, closes)
    # 120000 (priced) + 500000 (flat) = 620000.
    assert out["current_inr"] == 620000.0
    assert out["breakdown_inr"]["crypto_exchange"] == 120000.0
    assert out["breakdown_inr"]["ppf"] == 500000.0


def test_timeline_is_ordered_and_dated():
    holdings = [_h("X", HoldingCategory.EQUITY, "1", "100")]
    closes = {"X": [(date(2025, 1, 1), 100.0), (date(2025, 1, 3), 110.0)]}
    out = build_networth(holdings, closes)
    dates = [row["date"] for row in out["timeline"]]
    assert dates == sorted(dates)


def test_empty_book_is_zero():
    out = build_networth([], {})
    assert out["current_inr"] == 0.0
    assert out["timeline"] == []


def test_networth_endpoint(client: TestClient, auth_headers: dict[str, str]):
    resp = client.get("/api/v1/portfolio/net-worth", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "timeline" in body and "current_inr" in body and "breakdown_inr" in body


def test_networth_requires_auth(client: TestClient):
    assert client.get("/api/v1/portfolio/net-worth").status_code == 401
