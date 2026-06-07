"""Assets & market-data routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import OHLCV, NewsItem
from pfip.models.features import FeatureRow
from pfip.models.news import NewsRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow

router = APIRouter(prefix="/assets", tags=["assets"])

# Canonical typed feature columns (mirrors FeatureRow); extras live in JSONB.
_FEATURE_COLS: tuple[str, ...] = (
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "return_7d",
    "volatility_30d",
)


@router.get("/{symbol:path}/candles", response_model=list[OHLCV])
async def get_candles(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    timeframe: str = Query("1d"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
) -> list[OHLCV]:
    """Return OHLCV rows for ``symbol`` in ``timeframe``. Empty list if none.

    Bounded to the most recent ``limit`` rows (default 1000, max 5000) so the
    endpoint can never stream an entire multi-year history in one response.
    """
    stmt = select(OHLCVRow).where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == timeframe)
    if since is not None:
        stmt = stmt.where(OHLCVRow.time >= since)
    if until is not None:
        stmt = stmt.where(OHLCVRow.time <= until)
    # Take the most recent ``limit`` rows, then return them in ascending order.
    stmt = stmt.order_by(OHLCVRow.time.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    return [OHLCV.model_validate(row) for row in rows]


@router.get("/{symbol:path}/features")
async def get_features(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    as_of: datetime | None = Query(None),
    timeframe: str = Query("1d"),
) -> dict:
    """Return the latest feature row for ``symbol``.

    Returns the canonical 5+ typed features, the ``extras`` JSONB blob and the
    ``as_of`` time of the bar. If ``as_of`` is given we take the most-recent row
    at or before that instant. When no feature row exists we return a
    well-formed payload with null features rather than 501 (the Prefect compute
    flow may simply not have run for this symbol yet).
    """
    stmt = select(FeatureRow).where(FeatureRow.symbol == symbol, FeatureRow.timeframe == timeframe)
    if as_of is not None:
        stmt = stmt.where(FeatureRow.time <= as_of)
    stmt = stmt.order_by(FeatureRow.time.desc()).limit(1)
    row = (await db.execute(stmt)).scalars().first()

    if row is None:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "as_of": None,
            "source": None,
            "features": {col: None for col in _FEATURE_COLS},
            "extras": {},
        }

    return {
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "as_of": row.time.isoformat(),
        "source": row.source,
        "features": {col: getattr(row, col) for col in _FEATURE_COLS},
        "extras": row.extras or {},
    }


@router.get("/{symbol:path}/news", response_model=list[NewsItem])
async def get_news(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    since: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[NewsItem]:
    """Return recent news items for ``symbol``, newest first.

    Bounded to the most recent ``limit`` rows (default 50, max 200). Empty list
    if there's no news for the symbol.
    """
    stmt = select(NewsRow).where(NewsRow.symbol == symbol)
    if since is not None:
        stmt = stmt.where(NewsRow.time >= since)
    stmt = stmt.order_by(NewsRow.time.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [NewsItem.model_validate(row) for row in rows]


@router.get("/{symbol:path}/regime")
async def get_regime(symbol: str, db: DbSession, _user: CurrentUser) -> dict:
    """Return the latest regime label + confidence for ``symbol``.

    Returns a well-formed ``{regime: "unknown", confidence: 0.0}`` payload when
    the classifier hasn't labelled this symbol yet (rather than 501/404), so the
    UI can render a neutral state.
    """
    stmt = (
        select(RegimeRow)
        .where(RegimeRow.symbol == symbol)
        .order_by(RegimeRow.since.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()

    if row is None:
        return {
            "symbol": symbol,
            "regime": "unknown",
            "since": None,
            "confidence": 0.0,
        }

    return {
        "symbol": row.symbol,
        "regime": row.regime,
        "since": row.since.isoformat(),
        "confidence": row.confidence,
    }
