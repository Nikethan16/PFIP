"""Watchlist CRUD routes."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import WatchlistCreate, WatchlistItem
from pfip.models.ohlcv import OHLCVRow
from pfip.models.watchlist import WatchlistRow

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


async def _latest_prices(db, symbols: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """symbol -> (last_price, change_pct_24h) from the two most recent daily bars."""
    syms = [s for s in symbols if s]
    if not syms:
        return {}
    since = datetime.now(tz=timezone.utc) - timedelta(days=10)
    rows = (
        await db.execute(
            select(OHLCVRow.symbol, OHLCVRow.close)
            .where(OHLCVRow.symbol.in_(syms), OHLCVRow.timeframe == "1d", OHLCVRow.time >= since)
            .order_by(OHLCVRow.symbol, OHLCVRow.time.desc())
        )
    ).all()
    closes: dict[str, list[float]] = defaultdict(list)
    for sym, close in rows:
        if len(closes[sym]) < 2:
            closes[sym].append(float(close))
    out: dict[str, tuple[float | None, float | None]] = {}
    for sym, cs in closes.items():
        last = cs[0] if cs else None
        prev = cs[1] if len(cs) > 1 else None
        chg = ((last - prev) / prev * 100.0) if (last and prev) else None
        out[sym] = (last, chg)
    return out


@router.get("", response_model=list[WatchlistItem])
async def list_watchlist(db: DbSession, _user: CurrentUser) -> list[WatchlistItem]:
    """Return all watchlist rows, enriched with last price + 24h change."""
    result = await db.execute(select(WatchlistRow).order_by(WatchlistRow.added_at.desc()))
    rows = list(result.scalars().all())
    prices = await _latest_prices(db, [r.symbol for r in rows if r.symbol])
    items: list[WatchlistItem] = []
    for r in rows:
        item = WatchlistItem.model_validate(r)
        last, chg = prices.get(r.symbol or "", (None, None))
        items.append(item.model_copy(update={"last_price": last, "change_pct_24h": chg}))
    return items


@router.post("", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
async def add_watchlist(
    body: WatchlistCreate, db: DbSession, _user: CurrentUser
) -> WatchlistItem:
    """Add a symbol to the watchlist."""
    row = WatchlistRow(symbol=body.symbol, market=body.market or body.symbol, note=body.note)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Symbol already on watchlist",
        ) from exc
    await db.refresh(row)
    return WatchlistItem.model_validate(row)


@router.delete("/{item_id}", response_class=Response, status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    item_id: UUID, db: DbSession, _user: CurrentUser
) -> Response:
    """Remove a symbol from the watchlist."""
    row = await db.get(WatchlistRow, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
