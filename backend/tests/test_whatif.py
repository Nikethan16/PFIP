"""Tests for the what-if pre-trade simulator (pfip.portfolio.whatif)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from pfip.core.contracts import Holding, HoldingCategory
from pfip.portfolio.whatif import simulate


def _holding(symbol, category, qty, cost, acquired=None):
    return Holding(
        category=category,
        symbol=symbol,
        acquired_at=acquired or datetime(2024, 1, 1, tzinfo=timezone.utc),
        qty=Decimal(qty),
        cost_basis_inr=Decimal(cost),
    )


def _book():
    return [
        _holding("RELIANCE.NS", HoldingCategory.EQUITY, "10", "10000"),
        _holding("BTC/USD", HoldingCategory.CRYPTO_EXCHANGE, "1", "2000000"),
    ]


# ---------------------------------------------------------------------------
# BUY
# ---------------------------------------------------------------------------


def test_buy_new_symbol_adds_position():
    res = simulate(_book(), action="BUY", symbol="TCS.NS", qty="5", price="4000")
    assert res.after["n_positions"] == res.before["n_positions"] + 1
    assert res.deltas["total_value_inr"] == pytest.approx(20000, abs=1)
    assert res.tax_impact["tax_inr"] == 0.0  # BUY realises nothing


def test_buy_existing_symbol_increases_value_not_count():
    res = simulate(
        _book(),
        action="BUY",
        symbol="RELIANCE.NS",
        qty="10",
        price="1500",
        mark_prices={"RELIANCE.NS": Decimal("1500")},
    )
    assert res.after["n_positions"] == res.before["n_positions"]  # same names
    assert res.after["total_value_inr"] > res.before["total_value_inr"]


def test_buy_changes_concentration():
    # Buying a lot of one name should raise HHI (more concentrated).
    res = simulate(
        _book(),
        action="BUY",
        symbol="BTC/USD",
        qty="5",
        price="2000000",
        mark_prices={"BTC/USD": Decimal("2000000"), "RELIANCE.NS": Decimal("1000")},
    )
    assert res.deltas["hhi"] > 0


# ---------------------------------------------------------------------------
# SELL
# ---------------------------------------------------------------------------


def test_sell_partial_reduces_value():
    res = simulate(
        _book(),
        action="SELL",
        symbol="RELIANCE.NS",
        qty="5",
        price="1500",
        mark_prices={"RELIANCE.NS": Decimal("1500"), "BTC/USD": Decimal("2000000")},
    )
    assert res.after["total_value_inr"] < res.before["total_value_inr"]
    assert res.after["n_positions"] == res.before["n_positions"]  # still holds 5


def test_sell_full_closes_position():
    res = simulate(
        _book(),
        action="SELL",
        symbol="RELIANCE.NS",
        qty="10",
        price="1500",
    )
    assert res.after["n_positions"] == res.before["n_positions"] - 1


def test_sell_realises_gain_tax_on_equity():
    # Bought 10 @ 1000 (cost 10000), sell 10 @ 2000 ⇒ a real gain ⇒ some tax.
    res = simulate(
        _book(),
        action="SELL",
        symbol="RELIANCE.NS",
        qty="10",
        price="2000",
    )
    assert res.tax_impact["asset_class"] == "equity"
    assert res.tax_impact["realised_gain_inr"] == pytest.approx(10000, abs=1)
    assert res.tax_impact["tax_inr"] >= 0


def test_sell_more_than_held_is_clamped():
    # Selling 999 of a 10-share position only realises the 10 held.
    res = simulate(_book(), action="SELL", symbol="RELIANCE.NS", qty="999", price="2000")
    assert res.after["n_positions"] == res.before["n_positions"] - 1


def test_sell_unknown_symbol_no_change():
    res = simulate(_book(), action="SELL", symbol="NOPE", qty="1", price="100")
    assert res.tax_impact["tax_inr"] == 0.0
    assert res.after["n_positions"] == res.before["n_positions"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_zero_qty_raises():
    with pytest.raises(ValueError):
        simulate(_book(), action="BUY", symbol="X", qty="0", price="100")


def test_bad_action_raises():
    with pytest.raises(ValueError):
        simulate(_book(), action="HODL", symbol="X", qty="1", price="100")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_what_if_requires_auth(client: TestClient):
    resp = client.post(
        "/api/v1/portfolio/what-if",
        json={
            "action": "BUY",
            "symbol": "X",
            "qty": 1,
            "price": 100,
        },
    )
    assert resp.status_code == 401


def test_what_if_endpoint_runs(client: TestClient, auth_headers: dict[str, str]):
    # Fake DB ⇒ empty holdings; a BUY of a new name should still return a shape.
    resp = client.post(
        "/api/v1/portfolio/what-if",
        headers=auth_headers,
        json={"action": "BUY", "symbol": "TCS.NS", "qty": 5, "price": 4000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "before" in body and "after" in body and "deltas" in body
    assert "tax_impact" in body and "disclaimer" in body


def test_what_if_rejects_bad_action(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post(
        "/api/v1/portfolio/what-if",
        headers=auth_headers,
        json={"action": "HODL", "symbol": "X", "qty": 1, "price": 100},
    )
    assert resp.status_code == 422
