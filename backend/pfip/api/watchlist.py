"""Watchlist CRUD routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import WatchlistCreate, WatchlistItem
from pfip.models.watchlist import WatchlistRow

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItem])
async def list_watchlist(db: DbSession, _user: CurrentUser) -> list[WatchlistItem]:
    """Return all watchlist rows."""
    result = await db.execute(select(WatchlistRow).order_by(WatchlistRow.added_at.desc()))
    rows = result.scalars().all()
    return [WatchlistItem.model_validate(r) for r in rows]


@router.post("", response_model=WatchlistItem, status_code=status.HTTP_201_CREATED)
async def add_watchlist(
    body: WatchlistCreate, db: DbSession, _user: CurrentUser
) -> WatchlistItem:
    """Add a symbol to the watchlist."""
    row = WatchlistRow(symbol=body.symbol, market=body.market, note=body.note)
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


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    item_id: UUID, db: DbSession, _user: CurrentUser
) -> None:
    """Remove a symbol from the watchlist."""
    row = await db.get(WatchlistRow, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await db.delete(row)
    await db.commit()
