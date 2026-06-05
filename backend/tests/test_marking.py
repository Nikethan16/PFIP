"""Unit tests for portfolio mark-to-market + return-series pure logic.

The DB fetchers need Postgres (DISTINCT ON), so they're exercised only in
integration; here we lock down the currency-resolution and valuation math that
would silently corrupt rupee figures if wrong.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pfip.portfolio.marking import (
    compute_log_returns,
    compute_mark_prices,
    resolve_price_ccy,
)


@pytest.mark.parametrize(
    "market,symbol,expected",
    [
        # Unambiguous INR markets.
        ("india_equity", "DEMO-RELIANCE", "INR"),
        ("NSE", "RELIANCE", "INR"),
        ("BSE", "TCS", "INR"),
        ("in", "INFY", "INR"),
        # Unambiguous USD markets.
        ("us_equity", "DEMO-SPY", "USD"),
        ("US", "AAPL", "USD"),
        ("NASDAQ", "NVDA", "USD"),
        # ccxt-style market labels: quote currency is the trailing token.
        ("BTC_USD", "BTC/USD", "USD"),
        ("ETH_USDT", "ETH/USDT", "USD"),
        ("BTC_INR", "BTC/INR", "INR"),
        # Bare 'crypto' market (seed_demo): infer from symbol suffix.
        ("crypto", "DEMO-BTC-USD", "USD"),
        ("crypto", "DEMO-SOL-USD", "USD"),
        ("crypto", "WRX-INR", "INR"),
        # Genuinely ambiguous → abstain (None), never guess.
        ("", "MYSTERY", None),
        ("weird_market", "FOO", None),
        ("crypto", "JUSTASYMBOL", None),
    ],
)
def test_resolve_price_ccy(market, symbol, expected):
    assert resolve_price_ccy(market, symbol) == expected


def test_compute_log_returns_basic():
    closes = [100.0, 110.0, 99.0]
    rets = compute_log_returns(closes)
    assert len(rets) == 2
    assert rets[0] == pytest.approx(math.log(110 / 100))
    assert rets[1] == pytest.approx(math.log(99 / 110))


def test_compute_log_returns_skips_nonpositive_and_short():
    assert compute_log_returns([]) == []
    assert compute_log_returns([100.0]) == []
    # A zero/negative price breaks that pair but not the rest.
    rets = compute_log_returns([100.0, 0.0, 50.0])
    assert rets == []  # neither (100,0) nor (0,50) is a valid positive pair


def test_mark_prices_inr_direct_and_usd_converted():
    now = datetime.now(tz=timezone.utc)
    latest = {
        "DEMO-RELIANCE": (Decimal("2900"), "india_equity", now),
        "DEMO-SPY": (Decimal("550"), "us_equity", now),
    }
    res = compute_mark_prices(latest, ["DEMO-RELIANCE", "DEMO-SPY"], usdinr=Decimal("84"))
    assert res.mark_prices["DEMO-RELIANCE"] == Decimal("2900")
    assert res.mark_prices["DEMO-SPY"] == Decimal("46200.0000")  # 550 * 84
    assert set(res.marked) == {"DEMO-RELIANCE", "DEMO-SPY"}
    assert res.unmarked == []
    assert res.usdinr == Decimal("84")
    assert res.as_of == now


def test_mark_prices_abstains_without_fx():
    """A USD holding with no FX rate must NOT be marked (no stale guess)."""
    now = datetime.now(tz=timezone.utc)
    latest = {"DEMO-BTC-USD": (Decimal("68000"), "crypto", now)}
    res = compute_mark_prices(latest, ["DEMO-BTC-USD"], usdinr=None)
    assert res.mark_prices == {}
    assert res.marked == []
    assert res.unmarked == [{"symbol": "DEMO-BTC-USD", "reason": "no_fx_rate"}]


def test_mark_prices_abstains_on_unknown_currency_and_missing_price():
    now = datetime.now(tz=timezone.utc)
    latest = {"FOO": (Decimal("10"), "weird_market", now)}  # unknown ccy
    res = compute_mark_prices(latest, ["FOO", "BAR"], usdinr=Decimal("84"))
    assert res.mark_prices == {}
    reasons = {u["symbol"]: u["reason"] for u in res.unmarked}
    assert reasons["FOO"] == "unknown_currency"
    assert reasons["BAR"] == "no_price"  # BAR had no latest row at all
