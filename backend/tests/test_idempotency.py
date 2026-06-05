"""Tests for the deterministic batch-key generator.

We test the pure-Python ``make_batch_key`` — the DB-backed helpers are
exercised in the integration suite (they need an actual session).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pfip.ingest._common.idempotency import make_batch_key


def test_same_inputs_same_key():
    k1 = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        timeframe="1d",
        start=date(2026, 1, 1),
        end=date(2026, 5, 29),
    )
    k2 = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        timeframe="1d",
        start=date(2026, 1, 1),
        end=date(2026, 5, 29),
    )
    assert k1 == k2
    assert len(k1) == 64  # SHA-256 hex


def test_different_source_different_key():
    a = make_batch_key(source="yfinance", symbol="AAPL", timeframe="1d")
    b = make_batch_key(source="stooq", symbol="AAPL", timeframe="1d")
    assert a != b


def test_different_timeframe_different_key():
    a = make_batch_key(source="yfinance", symbol="AAPL", timeframe="1d")
    b = make_batch_key(source="yfinance", symbol="AAPL", timeframe="1h")
    assert a != b


def test_different_range_different_key():
    a = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        timeframe="1d",
        start=date(2026, 1, 1),
        end=date(2026, 5, 29),
    )
    b = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        timeframe="1d",
        start=date(2026, 1, 1),
        end=date(2026, 5, 30),  # one day later
    )
    assert a != b


def test_extra_order_does_not_change_key():
    """Dict ordering in `extra` must not affect the key."""
    a = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        extra={"adjust": True, "interval": "1d"},
    )
    b = make_batch_key(
        source="yfinance",
        symbol="AAPL",
        extra={"interval": "1d", "adjust": True},
    )
    assert a == b


def test_datetime_and_date_distinguished():
    """A date(2026,1,1) and datetime(2026,1,1,0,0) are different ISO strings."""
    a = make_batch_key(source="yfinance", symbol="X", start=date(2026, 1, 1))
    b = make_batch_key(
        source="yfinance",
        symbol="X",
        start=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
    )
    # Different ISO format → different key. We don't assert which is which;
    # just that they're distinct.
    assert a != b


def test_none_values_are_handled():
    """Missing fields don't crash; they hash as empty."""
    k = make_batch_key(source="x", symbol="y")
    assert isinstance(k, str)
    assert len(k) == 64
