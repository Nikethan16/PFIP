"""Assets & market-data routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from pfip.api.deps import DbSession
from pfip.core.contracts import OHLCV, NewsItem, RegimeLabel
from pfip.models.ohlcv import OHLCVRow

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{symbol}/candles", response_model=list[OHLCV])
async def get_candles(
    symbol: str,
    db: DbSession,
    timeframe: str = Query("1d"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
) -> list[OHLCV]:
    """Return OHLCV rows for ``symbol`` in ``timeframe``. Empty list if none."""
    stmt = select(OHLCVRow).where(
        OHLCVRow.symbol == symbol, OHLCVRow.timeframe == timeframe
    )
    if since is not None:
        stmt = stmt.where(OHLCVRow.time >= since)
    if until is not None:
        stmt = stmt.where(OHLCVRow.time <= until)
    stmt = stmt.order_by(OHLCVRow.time.asc())
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [OHLCV.model_validate(row) for row in rows]


@router.get("/{symbol}/features")
async def get_features(
    symbol: str,
    as_of: datetime | None = Query(None),
) -> dict:
    """Return feature dict for ``symbol`` at a point in time. Stubbed to ``{}``."""
    # TODO(stage 2): read from features table once Prefect compute flow runs.
    _ = (symbol, as_of)
    return {}


@router.get("/{symbol}/news", response_model=list[NewsItem])
async def get_news(
    symbol: str,
    since: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[NewsItem]:
    """Return news items. Stubbed to empty until Stage 2 ingest lands."""
    _ = (symbol, since, limit)
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet; tracked in PLACEHOLDERS.md",
    )


@router.get("/{symbol}/regime", response_model=RegimeLabel)
async def get_regime(symbol: str) -> RegimeLabel:
    """Return current regime label. Stubbed until Stage 4."""
    _ = symbol
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented yet; tracked in PLACEHOLDERS.md",
    )
