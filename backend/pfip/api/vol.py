"""Volatility API (F2) — realized-vol cone + forward forecast per asset.

``GET /vol/{symbol}`` returns the realized-volatility cone (current vs the
historical distribution across horizons) plus the best-available forward
forecast (Chronos → historical, from :mod:`pfip.vol.cone`). This is the
volatility-focused replacement for the no-edge direction signals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.ohlcv import OHLCVRow
from pfip.vol.analytics import ConeBucket, vol_cone

router = APIRouter(prefix="/vol", tags=["vol"])


class VolForecast(BaseModel):
    annual_vol: float
    horizon_days: int
    source: str


class VolResponse(BaseModel):
    symbol: str
    n_points: int
    cone: list[ConeBucket]
    forecast: VolForecast | None = None
    disclaimer: str = (
        "Realized volatility (annualized) vs its own history, plus a forward "
        "estimate. Volatility clusters and is more forecastable than direction — "
        "informational, not a trade instruction."
    )


@router.get("/{symbol}", response_model=VolResponse)
async def vol(symbol: str, db: DbSession, _user: CurrentUser, days: int = 500) -> VolResponse:
    symbol = symbol.strip()
    closes = await _closes(db, symbol, days)
    cone = vol_cone(closes)

    forecast: VolForecast | None = None
    if len(closes) >= 30:
        try:
            import pandas as pd

            from pfip.vol.cone import forecast_vol_cone

            vc = forecast_vol_cone(pd.Series(closes), horizon_days=63)
            if vc is not None:
                forecast = VolForecast(**vc.as_dict())
        except Exception:  # noqa: BLE001 — forecast is best-effort
            forecast = None

    return VolResponse(symbol=symbol, n_points=len(closes), cone=cone, forecast=forecast)


async def _closes(db: DbSession, symbol: str, days: int) -> list[float]:
    try:
        freshest = (
            select(OHLCVRow.source)
            .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
            .order_by(OHLCVRow.time.desc())
            .limit(1)
            .scalar_subquery()
        )
        since = datetime.now(tz=UTC) - timedelta(days=days)
        rows = (
            await db.execute(
                select(OHLCVRow.close)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.timeframe == "1d",
                    OHLCVRow.source == freshest,
                    OHLCVRow.time >= since,
                )
                .order_by(OHLCVRow.time.asc())
            )
        ).all()
    except Exception:  # noqa: BLE001
        return []
    return [float(c) for (c,) in rows if c is not None]
