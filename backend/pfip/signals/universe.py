"""Survivorship-bias-aware universe selection.

A common backtest bug: query "every symbol on the watchlist as of *today*"
and then run that universe against historical data — silently excluding
symbols that have since delisted. The result looks better than reality.

The fix is mechanical: keep delisted rows in the watchlist with a
``delisted_at`` timestamp; when assembling a universe for a backtest
window, include rows where:

    delisted_at IS NULL  OR  delisted_at > target_date

This module exposes two helpers — a pure-Python set selector that takes
already-fetched rows (used by tests) and an async DB-backed selector
that runs the SQL directly.

We deliberately do *not* expose a "live universe" query that omits
delisted rows; if a caller wants only currently-tradable symbols, they
pass ``target_date=datetime.now()`` and the same logic still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class UniverseRow:
    """Minimum shape needed by the universe selector."""

    symbol: str
    market: str
    is_delisted: bool
    delisted_at: datetime | None


def as_of_universe(
    rows: Iterable[UniverseRow],
    *,
    target_date: datetime,
    markets: set[str] | None = None,
) -> list[UniverseRow]:
    """Filter ``rows`` to those investable on ``target_date``.

    A row is included when:
        - ``delisted_at`` is None, OR
        - ``delisted_at > target_date`` (delisting hadn't happened yet).

    If ``markets`` is supplied, rows outside those markets are dropped.
    Order is stable: input order is preserved among the kept rows.
    """
    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)
    out: list[UniverseRow] = []
    for r in rows:
        if markets and r.market not in markets:
            continue
        if r.delisted_at is None:
            out.append(r)
            continue
        d = r.delisted_at
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        if d > target_date:
            out.append(r)
    return out


async def as_of_universe_db(
    db: Any,
    *,
    target_date: datetime,
    markets: set[str] | None = None,
) -> list[str]:
    """DB-backed: return the list of symbols investable on ``target_date``."""
    from sqlalchemy import or_, select  # local import — keeps tests light

    from pfip.models.watchlist import WatchlistRow

    if target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)

    stmt = select(WatchlistRow).where(
        or_(
            WatchlistRow.delisted_at.is_(None),
            WatchlistRow.delisted_at > target_date,
        )
    )
    if markets:
        stmt = stmt.where(WatchlistRow.market.in_(markets))
    rows = (await db.execute(stmt)).scalars().all()
    return [r.symbol for r in rows]


__all__ = ["UniverseRow", "as_of_universe", "as_of_universe_db"]
