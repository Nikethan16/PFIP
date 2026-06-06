"""Unit tests for ``to_canonical_symbol`` symbol normalization.

Canonical symbols are dash-style (``BTC-USD``) per ``docs/CONTRACTS.md``. The
crypto OHLCV ingest must convert ccxt slash form (``BTC/USD``) to canonical
before writing, while leaving FX (``USDINR``) and MF (``MF_xxx``) symbols alone.
"""

from __future__ import annotations

import pytest

from pfip.core.contracts import to_canonical_symbol


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BTC/USD", "BTC-USD"),
        ("ETH/USDT", "ETH-USDT"),
        ("BTC-USD", "BTC-USD"),  # already canonical
        ("USDINR", "USDINR"),  # FX, no separator
        ("MF_141272", "MF_141272"),  # mutual fund, underscore preserved
        ("btc/usd", "BTC-USD"),  # lowercase ccxt -> uppercased canonical
        ("SOL/USDT", "SOL-USDT"),
    ],
)
def test_to_canonical_symbol(raw: str, expected: str) -> None:
    assert to_canonical_symbol(raw) == expected


def test_to_canonical_symbol_is_idempotent() -> None:
    once = to_canonical_symbol("BTC/USD")
    assert to_canonical_symbol(once) == once == "BTC-USD"
