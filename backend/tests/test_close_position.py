"""Unit tests for the close-position → post-mortem journal linkage (audit H4).

Closing a holding must create exactly one linked journal stub and surface its
id so the UI opens the post-mortem dialog against a JOURNAL entry, not the
holding. We exercise ``PortfolioService.close_holding`` directly with a small
in-memory fake session so the test stays focused and DB-free.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pfip.models.holdings import HoldingRow
from pfip.models.journal import JournalRow
from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.portfolio.service import PortfolioService


class _Scalars:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeSession:
    """In-memory session that routes ``select`` by target entity.

    Supports exactly the two query shapes ``close_holding`` issues:
      * ``select(HoldingRow).where(HoldingRow.id == ...)``
      * ``select(JournalRow).where(JournalRow.notes.is_not(None))``
    """

    def __init__(self) -> None:
        self.holdings: list[HoldingRow] = []
        self.journals: list[JournalRow] = []
        self.txs: list[PortfolioTxRow] = []

    def _entity(self, stmt):
        # The first column description's entity is the mapped class we selected.
        return stmt.column_descriptions[0]["entity"]

    async def execute(self, stmt):
        entity = self._entity(stmt)
        if entity is HoldingRow:
            return _Result(self.holdings)
        if entity is JournalRow:
            # _ensure_post_mortem_stub filters notes is_not None; mimic that.
            return _Result([j for j in self.journals if j.notes is not None])
        return _Result([])

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, HoldingRow):
            self.holdings.append(obj)
        elif isinstance(obj, JournalRow):
            self.journals.append(obj)
        elif isinstance(obj, PortfolioTxRow):
            self.txs.append(obj)

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None


def _make_holding() -> HoldingRow:
    return HoldingRow(
        id=uuid.uuid4(),
        category="equity",
        symbol="RELIANCE.NS",
        isin=None,
        broker="zerodha",
        account_id=None,
        acquired_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        qty=Decimal("10"),
        cost_basis_inr=Decimal("20000"),
        cost_basis_ccy="INR",
        fx_rate=None,
        is_self_custody=False,
        notes=None,
        closed_at=None,
        exit_price_inr=None,
    )


@pytest.mark.asyncio
async def test_close_creates_journal_entry_and_returns_id() -> None:
    session = _FakeSession()
    holding = _make_holding()
    session.holdings.append(holding)
    svc = PortfolioService(session)

    result = await svc.close_holding(holding.id, Decimal("25000"))

    assert result["post_mortem_required"] is True
    # A journal stub was created and its id returned.
    assert len(session.journals) == 1
    assert result["journal_entry_id"] == str(session.journals[0].id)


@pytest.mark.asyncio
async def test_journal_stub_is_linked_to_holding_and_symbol() -> None:
    session = _FakeSession()
    holding = _make_holding()
    session.holdings.append(holding)
    svc = PortfolioService(session)

    await svc.close_holding(holding.id, Decimal("25000"))

    stub = session.journals[0]
    # Linked to the holding via the marker, and carries the symbol.
    assert str(holding.id) in (stub.notes or "")
    assert stub.symbol == "RELIANCE.NS"
    assert stub.direction == "SELL"
    # Realised P&L (proceeds 25000 - cost 20000) is pre-filled in the note.
    assert "realized_pnl_inr=5000" in (stub.notes or "")


@pytest.mark.asyncio
async def test_close_is_idempotent_one_post_mortem_per_holding() -> None:
    session = _FakeSession()
    holding = _make_holding()
    session.holdings.append(holding)
    svc = PortfolioService(session)

    # Partial close, then close the remainder. Only one stub should exist and
    # both responses must reference the same journal entry id.
    first = await svc.close_holding(holding.id, Decimal("2500"), qty=Decimal("5"))
    second = await svc.close_holding(holding.id, Decimal("2500"), qty=Decimal("5"))

    assert len(session.journals) == 1
    assert first["journal_entry_id"] == second["journal_entry_id"]
