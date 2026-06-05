"""Pure-logic tests for survivorship universes, ingest idempotency keys,
and news-pipeline URL normalization.

These three modules are the building blocks under several Prefect flows
and a couple of API endpoints; testing them in isolation keeps the
guarantees crisp without touching the DB.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pfip.ingest._common.idempotency import make_batch_key
from pfip.ingest.news._pipeline import _normalize_url, is_crypto_text
from pfip.signals.universe import UniverseRow, as_of_universe


# ---------------------------------------------------------------------------
# Survivorship-aware universe
# ---------------------------------------------------------------------------


def _row(symbol: str, market: str = "us", delisted_at: datetime | None = None) -> UniverseRow:
    return UniverseRow(
        symbol=symbol,
        market=market,
        is_delisted=delisted_at is not None,
        delisted_at=delisted_at,
    )


def test_as_of_universe_includes_active_symbols():
    rows = [_row("AAPL"), _row("MSFT"), _row("GOOG")]
    out = as_of_universe(rows, target_date=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert {r.symbol for r in out} == {"AAPL", "MSFT", "GOOG"}


def test_as_of_universe_excludes_already_delisted():
    """Symbol delisted before target_date → excluded."""
    rows = [
        _row("ALIVE"),
        _row("DEADCO", delisted_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
    ]
    out = as_of_universe(rows, target_date=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert [r.symbol for r in out] == ["ALIVE"]


def test_as_of_universe_includes_symbols_delisted_after_target():
    """Critical for backtests: symbol delisted AFTER target_date must be present."""
    rows = [
        _row("ALIVE"),
        _row("LATERDEAD", delisted_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    # Backtest as of 2025 — LATERDEAD was still tradeable then.
    out = as_of_universe(rows, target_date=datetime(2025, 6, 1, tzinfo=timezone.utc))
    assert {r.symbol for r in out} == {"ALIVE", "LATERDEAD"}


def test_as_of_universe_market_filter():
    """The markets= filter drops out-of-scope rows even if active."""
    rows = [_row("AAPL", market="us"), _row("RELIANCE.NS", market="in")]
    out = as_of_universe(
        rows,
        target_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        markets={"us"},
    )
    assert [r.symbol for r in out] == ["AAPL"]


def test_as_of_universe_naive_datetime_handled():
    """Naive target_date is coerced to UTC (avoids tz-aware comparison error)."""
    rows = [_row("X", delisted_at=datetime(2030, 1, 1))]
    # Should not raise.
    out = as_of_universe(rows, target_date=datetime(2025, 1, 1))
    assert [r.symbol for r in out] == ["X"]


# ---------------------------------------------------------------------------
# Idempotent batch keys
# ---------------------------------------------------------------------------


def test_make_batch_key_is_deterministic():
    """Same args → same key."""
    k1 = make_batch_key(
        source="coinbase",
        symbol="BTC/USD",
        timeframe="1h",
        start=datetime(2026, 5, 28, tzinfo=timezone.utc),
        end=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    k2 = make_batch_key(
        source="coinbase",
        symbol="BTC/USD",
        timeframe="1h",
        start=datetime(2026, 5, 28, tzinfo=timezone.utc),
        end=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    assert k1 == k2
    # SHA-256 hex length.
    assert len(k1) == 64


def test_make_batch_key_changes_when_symbol_changes():
    k_btc = make_batch_key(source="coinbase", symbol="BTC/USD")
    k_eth = make_batch_key(source="coinbase", symbol="ETH/USD")
    assert k_btc != k_eth


def test_make_batch_key_changes_when_window_changes():
    k1 = make_batch_key(
        source="x", symbol="y", start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)
    )
    k2 = make_batch_key(
        source="x", symbol="y", start=datetime(2026, 1, 1), end=datetime(2026, 1, 3)
    )
    assert k1 != k2


def test_make_batch_key_extra_dict_order_invariant():
    """The `extra` dict should hash the same regardless of key order."""
    k1 = make_batch_key(source="s", symbol="y", extra={"a": 1, "b": 2})
    k2 = make_batch_key(source="s", symbol="y", extra={"b": 2, "a": 1})
    assert k1 == k2


# ---------------------------------------------------------------------------
# News pipeline URL normalization + crypto detection
# ---------------------------------------------------------------------------


def test_normalize_url_strips_utm_and_fragment():
    raw = "https://example.com/article?utm_source=twitter&id=42#share"
    assert _normalize_url(raw) == "https://example.com/article?id=42"


def test_normalize_url_strips_all_tracking_only_query():
    """If only tracking params are present, the question mark is dropped."""
    raw = "https://example.com/article?utm_source=x&fbclid=abc&gclid=def"
    assert _normalize_url(raw) == "https://example.com/article"


def test_normalize_url_trailing_slash_removed():
    assert _normalize_url("https://example.com/a/") == "https://example.com/a"


def test_normalize_url_empty_stays_empty():
    assert _normalize_url("") == ""


def test_is_crypto_text_positive():
    assert is_crypto_text("Bitcoin surges past $100k")


def test_is_crypto_text_negative():
    assert is_crypto_text("Reliance Industries reports Q3 results") is False


def test_is_crypto_text_handles_none_safely():
    """Defensive: never raises on None / empty."""
    assert is_crypto_text("") is False
    assert is_crypto_text(None) is False  # type: ignore[arg-type]
