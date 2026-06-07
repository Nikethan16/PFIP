"""Thin CRUD layer around ``shadow_portfolio_ledger``.

The ledger is the same shape as ``portfolio_tx`` but lives in a separate table
so the shadow numbers can't ever pollute the real one. This module gives the
rest of the shadow code a small typed surface for reading / writing rows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import desc, select

from pfip.core.contracts import PortfolioTxKind
from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow

log = logging.getLogger(__name__)


@dataclass
class LedgerEntry:
    """A typed view of one ``shadow_portfolio_tx`` row."""

    id: uuid.UUID | None
    holding_id: uuid.UUID | None
    time: datetime
    kind: PortfolioTxKind
    qty: Decimal | None
    price: Decimal | None
    amount_inr: Decimal
    fx_rate: Decimal | None = None
    tax_withheld: Decimal = Decimal("0")
    note: str | None = None

    def as_orm(self) -> ShadowPortfolioTxRow:
        return ShadowPortfolioTxRow(
            holding_id=self.holding_id,
            time=self.time,
            kind=self.kind.value,
            qty=self.qty,
            price=self.price,
            amount_inr=self.amount_inr,
            fx_rate=self.fx_rate,
            tax_withheld=self.tax_withheld,
            note=self.note,
        )


async def write_entry(session, entry: LedgerEntry) -> ShadowPortfolioTxRow:
    """Insert a single ledger entry. Caller commits."""
    row = entry.as_orm()
    session.add(row)
    await session.flush()
    return row


async def list_entries(
    session, *, since: datetime | None = None, limit: int = 200
) -> list[ShadowPortfolioTxRow]:
    stmt = select(ShadowPortfolioTxRow).order_by(desc(ShadowPortfolioTxRow.time))
    if since is not None:
        stmt = stmt.where(ShadowPortfolioTxRow.time >= since)
    stmt = stmt.limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def open_holdings(session) -> list[ShadowHoldingRow]:
    """All shadow holdings that aren't closed yet."""
    stmt = select(ShadowHoldingRow).where(ShadowHoldingRow.closed_at.is_(None))
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def find_open_by_symbol(session, symbol: str) -> ShadowHoldingRow | None:
    """First open holding matching ``symbol``, or ``None``."""
    stmt = (
        select(ShadowHoldingRow)
        .where(
            ShadowHoldingRow.symbol == symbol,
            ShadowHoldingRow.closed_at.is_(None),
        )
        .limit(1)
    )
    res = await session.execute(stmt)
    return res.scalars().first()


async def close_holding(
    session,
    holding: ShadowHoldingRow,
    *,
    price: Decimal,
    when: datetime | None = None,
    reason: str = "",
) -> ShadowPortfolioTxRow:
    """Mark ``holding`` closed and write a SELL tx entry."""
    when = when or datetime.now(tz=timezone.utc)
    holding.closed_at = when
    holding.exit_price_inr = price
    tx = ShadowPortfolioTxRow(
        holding_id=holding.id,
        time=when,
        kind=PortfolioTxKind.SELL.value,
        qty=holding.qty,
        price=price,
        amount_inr=holding.qty * price,
        note=f"shadow SELL: {reason}" if reason else "shadow SELL",
    )
    session.add(tx)
    return tx


async def total_open_value(session, *, mark_to_market: dict[str, Decimal] | None = None) -> Decimal:
    """Sum of (qty * mark) across open holdings.

    When a symbol isn't in ``mark_to_market``, fall back to cost basis.
    """
    rows = await open_holdings(session)
    mark_to_market = mark_to_market or {}
    total = Decimal(0)
    for h in rows:
        m = mark_to_market.get(h.symbol or "")
        if m is None:
            total += h.cost_basis_inr or Decimal(0)
        else:
            total += h.qty * m
    return total
