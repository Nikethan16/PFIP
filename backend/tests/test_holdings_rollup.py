"""Unit tests for the holdings rollup (pfip.portfolio.rollup).

The rollup materializes ``holdings`` from import-originated ``portfolio_tx``
rows. These tests drive ``rebuild_holdings_from_tx`` against an in-memory fake
session and assert the position math (net qty + weighted-average cost basis),
the note parsing, closed-position handling, and the asset_class filter — without
touching a real database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pfip.core.contracts import HoldingCategory
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.portfolio.rollup import (
    asset_class_for,
    category_for,
    encode_tx_note,
    parse_tx_note,
    rebuild_holdings_from_tx,
)


def _tx(*, kind, qty, amount, note, when, fx=None) -> PortfolioTxRow:  # noqa: ANN001
    r = PortfolioTxRow()
    r.holding_id = None
    r.time = when
    r.kind = kind
    r.qty = Decimal(str(qty)) if qty is not None else None
    r.price = None
    r.amount_inr = Decimal(str(amount))
    r.fx_rate = Decimal(str(fx)) if fx is not None else None
    r.tax_withheld = Decimal("0")
    r.note = note
    return r


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _RollupSession:
    """Serves portfolio_tx rows, captures added/deleted HoldingRows."""

    def __init__(self, txs: list[PortfolioTxRow], existing: list[HoldingRow] | None = None) -> None:
        self._txs = txs
        self.holdings: list[HoldingRow] = list(existing or [])
        self.added: list[HoldingRow] = []

    async def execute(self, stmt, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        text = str(stmt).lower()
        if "from portfolio_tx" in text:
            return _Result(list(self._txs))
        if "from holdings" in text:
            # The rollup selects existing rollup-owned holdings to replace.
            return _Result(list(self.holdings))
        return _Result([])

    def add(self, obj) -> None:  # noqa: ANN001
        if isinstance(obj, HoldingRow):
            self.holdings.append(obj)
            self.added.append(obj)

    async def delete(self, obj) -> None:  # noqa: ANN001
        self.holdings = [h for h in self.holdings if h is not obj]

    async def commit(self) -> None:
        return None

    async def refresh(self, obj) -> None:  # noqa: ANN001
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Note encode/decode round-trip
# ---------------------------------------------------------------------------


def test_note_roundtrip() -> None:
    note = encode_tx_note(
        broker="zerodha", symbol="TCS.NS", asset_class="equity", free="NSE trade 42"
    )
    parsed = parse_tx_note(note)
    assert parsed.broker == "zerodha"
    assert parsed.symbol == "TCS.NS"
    assert parsed.asset_class == "equity"


def test_asset_class_and_category_mapping() -> None:
    # Broker hint when no explicit tag.
    assert asset_class_for("binance", None) == "vda"
    assert asset_class_for("vested", None) == "us_stock"
    assert asset_class_for("zerodha", None) == "equity"
    # Explicit tag wins.
    assert asset_class_for("zerodha", "vda") == "vda"
    assert category_for("vda") == HoldingCategory.CRYPTO_EXCHANGE
    assert category_for("equity") == HoldingCategory.EQUITY
    assert category_for("us_stock") == HoldingCategory.EQUITY


# ---------------------------------------------------------------------------
# Core math: 2 buys + 1 sell
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_buys_one_sell_weighted_avg() -> None:
    """100 @ 100 + 50 @ 130 = 150 units, ₹16,500 cost; sell 60 → 90 left.

    Weighted-avg cost/unit = 16500 / 150 = 110. Remaining basis = 90 * 110 = 9900.
    """
    sym_note = lambda free: encode_tx_note(  # noqa: E731
        broker="zerodha", symbol="INFY.NS", asset_class="equity", free=free
    )
    txs = [
        _tx(kind="BUY", qty=100, amount=10_000, note=sym_note("b1"), when=NOW),
        _tx(kind="BUY", qty=50, amount=6_500, note=sym_note("b2"), when=NOW),
        _tx(kind="SELL", qty=60, amount=8_400, note=sym_note("s1"), when=NOW),
    ]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session)

    assert len(out) == 1
    h = out[0]
    assert h.symbol == "INFY.NS"
    assert h.category == HoldingCategory.EQUITY
    assert Decimal(str(h.qty)) == Decimal("90")
    # Remaining cost basis at weighted-avg = 90 * 110 = 9900.
    assert Decimal(str(h.cost_basis_inr)) == Decimal("9900.00")
    # Materialized rows carry the rollup marker.
    assert session.added[0].notes.startswith("[rollup]")


@pytest.mark.asyncio
async def test_fully_closed_position_not_materialized() -> None:
    """Buy 10, sell 10 → net 0 → no open holding."""
    note = encode_tx_note(broker="zerodha", symbol="WIPRO.NS", asset_class="equity")
    txs = [
        _tx(kind="BUY", qty=10, amount=5_000, note=note, when=NOW),
        _tx(kind="SELL", qty=10, amount=6_000, note=note, when=NOW),
    ]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session)
    assert out == []


@pytest.mark.asyncio
async def test_oversold_position_not_materialized() -> None:
    """Net negative (data error / partial history) is treated as closed, not negative."""
    note = encode_tx_note(broker="zerodha", symbol="HDFC.NS", asset_class="equity")
    txs = [
        _tx(kind="BUY", qty=5, amount=2_500, note=note, when=NOW),
        _tx(kind="SELL", qty=8, amount=4_800, note=note, when=NOW),
    ]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session)
    assert out == []


@pytest.mark.asyncio
async def test_multiple_symbols_and_dividends_ignored() -> None:
    """Two symbols roll up independently; DIVIDEND/FEE rows don't move qty."""
    infy = lambda free: encode_tx_note(
        broker="zerodha", symbol="INFY.NS", asset_class="equity", free=free
    )  # noqa: E731
    btc = lambda free: encode_tx_note(
        broker="binance", symbol="BTC-USDT", asset_class="vda", free=free
    )  # noqa: E731
    txs = [
        _tx(kind="BUY", qty=10, amount=1_000, note=infy("b"), when=NOW),
        _tx(kind="DIVIDEND", qty=None, amount=50, note=infy("div"), when=NOW),
        _tx(kind="FEE", qty=None, amount=5, note=infy("fee"), when=NOW),
        _tx(kind="BUY", qty=2, amount=120_000, note=btc("b"), when=NOW, fx=83),
    ]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session)
    by_symbol = {h.symbol: h for h in out}
    assert set(by_symbol) == {"INFY.NS", "BTC-USDT"}
    assert Decimal(str(by_symbol["INFY.NS"].qty)) == Decimal("10")
    assert Decimal(str(by_symbol["INFY.NS"].cost_basis_inr)) == Decimal("1000.00")
    assert by_symbol["BTC-USDT"].category == HoldingCategory.CRYPTO_EXCHANGE
    assert Decimal(str(by_symbol["BTC-USDT"].qty)) == Decimal("2")


@pytest.mark.asyncio
async def test_asset_class_filter() -> None:
    """asset_class='vda' rolls up only the crypto book."""
    infy = encode_tx_note(broker="zerodha", symbol="INFY.NS", asset_class="equity")
    btc = encode_tx_note(broker="binance", symbol="BTC-USDT", asset_class="vda")
    txs = [
        _tx(kind="BUY", qty=10, amount=1_000, note=infy, when=NOW),
        _tx(kind="BUY", qty=1, amount=60_000, note=btc, when=NOW),
    ]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session, asset_class="vda")
    assert len(out) == 1
    assert out[0].symbol == "BTC-USDT"


@pytest.mark.asyncio
async def test_holding_id_set_rows_skipped() -> None:
    """Rows already pinned to a holding (manual) are not re-materialized."""
    note = encode_tx_note(broker="zerodha", symbol="TCS.NS", asset_class="equity")
    pinned = _tx(kind="BUY", qty=10, amount=1_000, note=note, when=NOW)
    import uuid as _uuid

    pinned.holding_id = _uuid.uuid4()
    session = _RollupSession([pinned])
    out = await rebuild_holdings_from_tx(session)
    assert out == []


@pytest.mark.asyncio
async def test_cash_rows_skipped() -> None:
    """Ledger 'CASH' pseudo-symbol rows are skipped."""
    note = encode_tx_note(broker="zerodha", symbol="CASH", asset_class="equity")
    txs = [_tx(kind="TRANSFER", qty=None, amount=10_000, note=note, when=NOW)]
    session = _RollupSession(txs)
    out = await rebuild_holdings_from_tx(session)
    assert out == []
