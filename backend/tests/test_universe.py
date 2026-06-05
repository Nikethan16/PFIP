"""Tests for the survivorship-bias-aware universe selector.

The whole point of the selector is to *include* symbols that have since
delisted when looking at a historical date. These tests pin that
behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pfip.signals.universe import UniverseRow, as_of_universe


def _row(
    symbol: str,
    *,
    market: str = "us",
    delisted_at: datetime | None = None,
) -> UniverseRow:
    return UniverseRow(
        symbol=symbol,
        market=market,
        is_delisted=delisted_at is not None,
        delisted_at=delisted_at,
    )


def test_live_symbol_always_included():
    rows = [_row("AAPL"), _row("MSFT")]
    out = as_of_universe(rows, target_date=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert {r.symbol for r in out} == {"AAPL", "MSFT"}


def test_delisted_symbol_included_for_dates_before_delisting():
    """LEHM delisted 2008-09-15 — should be in a 2008-01-01 universe."""
    rows = [
        _row("LEHM", delisted_at=datetime(2008, 9, 15, tzinfo=timezone.utc)),
        _row("AAPL"),
    ]
    out = as_of_universe(rows, target_date=datetime(2008, 1, 1, tzinfo=timezone.utc))
    assert {r.symbol for r in out} == {"LEHM", "AAPL"}


def test_delisted_symbol_excluded_for_dates_after_delisting():
    """LEHM should NOT be in a 2020-01-01 universe."""
    rows = [
        _row("LEHM", delisted_at=datetime(2008, 9, 15, tzinfo=timezone.utc)),
        _row("AAPL"),
    ]
    out = as_of_universe(rows, target_date=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert {r.symbol for r in out} == {"AAPL"}


def test_market_filter_applied():
    rows = [
        _row("AAPL", market="us"),
        _row("RELIANCE.NS", market="india"),
        _row("BTC-USD", market="crypto"),
    ]
    out = as_of_universe(
        rows,
        target_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        markets={"us", "india"},
    )
    assert {r.symbol for r in out} == {"AAPL", "RELIANCE.NS"}


def test_naive_target_date_treated_as_utc():
    """Calling with a tz-naive datetime must not crash; it's interpreted as UTC."""
    rows = [_row("LEHM", delisted_at=datetime(2008, 9, 15, tzinfo=timezone.utc))]
    out = as_of_universe(rows, target_date=datetime(2008, 1, 1))
    assert len(out) == 1


def test_naive_delisting_treated_as_utc():
    """Delisted_at without tz must not crash; interpreted as UTC."""
    rows = [_row("X", delisted_at=datetime(2020, 6, 1))]
    # target after delisting → excluded.
    out = as_of_universe(rows, target_date=datetime(2021, 1, 1, tzinfo=timezone.utc))
    assert out == []
    # target before delisting → included.
    out = as_of_universe(rows, target_date=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert len(out) == 1


def test_order_preserved():
    rows = [
        _row("A"),
        _row("Z"),
        _row("M", delisted_at=datetime(2000, 1, 1, tzinfo=timezone.utc)),
    ]
    out = as_of_universe(rows, target_date=datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert [r.symbol for r in out] == ["A", "Z"]


def test_empty_input_returns_empty():
    assert as_of_universe([], target_date=datetime(2020, 1, 1, tzinfo=timezone.utc)) == []
