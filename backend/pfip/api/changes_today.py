"""`/api/v1/changes-today` — pre-empts the user's "anything worth looking at?"

Returns a compact list of deltas in the trailing N hours:

- New SIGNALs (typed BUY/SELL since cutoff).
- Regime flips (any symbol changed its regime since cutoff).
- Watchlist movers with |z-score| ≥ ``z_threshold`` (5σ by default).
- News clusters: top-N articles by ``impact_score`` since cutoff.

The endpoint is deliberately read-only and side-effect-free. The
frontend renders this as a single card on the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.news import NewsRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow
from pfip.models.signals import SignalRow

router = APIRouter(prefix="/changes-today", tags=["dashboard"])


class SignalDelta(BaseModel):
    symbol: str
    direction: str
    confidence: float
    generated_at: datetime


class RegimeFlip(BaseModel):
    symbol: str
    from_regime: str | None
    to_regime: str
    since: datetime
    confidence: float


class WatchlistMover(BaseModel):
    symbol: str
    last_close: float
    return_pct: float
    z_score: float


class NewsDelta(BaseModel):
    title: str
    source: str
    impact_score: int
    sentiment: float
    published_at: datetime
    url: str | None


class ChangesTodayResponse(BaseModel):
    window_hours: int
    cutoff: datetime
    signals: list[SignalDelta]
    regime_flips: list[RegimeFlip]
    movers: list[WatchlistMover]
    news: list[NewsDelta]


def _zscore(values: list[float], current: float) -> float:
    """Z-score of `current` vs the trailing series. NaN-safe."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 5:
        return 0.0
    mu, sd = float(arr.mean()), float(arr.std(ddof=1))
    if sd == 0 or np.isnan(sd):
        return 0.0
    return (current - mu) / sd


@router.get("", response_model=ChangesTodayResponse)
async def changes_today(
    db: DbSession,
    _user: CurrentUser,
    hours: int = 24,
    z_threshold: float = 5.0,
    news_top: int = 5,
) -> ChangesTodayResponse:
    """Aggregate the trailing-``hours`` deltas across signals/regime/movers/news."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    # --- New signals -------------------------------------------------------
    sig_rows = (
        (
            await db.execute(
                select(SignalRow)
                .where(SignalRow.generated_at >= cutoff)
                .order_by(SignalRow.generated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    signals = [
        SignalDelta(
            symbol=s.symbol,
            direction=str(s.direction),
            confidence=float(getattr(s, "confidence", 0.0) or 0.0),
            generated_at=s.generated_at,
        )
        for s in sig_rows
    ]

    # --- Regime flips -----------------------------------------------------
    regime_rows = (
        (
            await db.execute(
                select(RegimeRow).where(RegimeRow.since >= cutoff).order_by(RegimeRow.since.asc())
            )
        )
        .scalars()
        .all()
    )
    flips: list[RegimeFlip] = []
    by_sym: dict[str, list[RegimeRow]] = {}
    for r in regime_rows:
        by_sym.setdefault(r.symbol, []).append(r)
    for sym, items in by_sym.items():
        # Compare each consecutive pair; the first one shows the symbol's
        # arrival into the window so 'from' is None.
        prev_label: str | None = None
        for r in items:
            if prev_label is None or r.regime != prev_label:
                flips.append(
                    RegimeFlip(
                        symbol=sym,
                        from_regime=prev_label,
                        to_regime=r.regime,
                        since=r.since,
                        confidence=float(r.confidence),
                    )
                )
            prev_label = r.regime

    # --- Watchlist movers -------------------------------------------------
    # For each symbol with OHLCV in the window, compute the last return and
    # its z-score against the trailing 60 bars. Surface those above
    # |z| >= z_threshold.
    movers: list[WatchlistMover] = []
    ohlcv_rows = (
        (
            await db.execute(
                select(OHLCVRow)
                .where(OHLCVRow.ts >= cutoff - timedelta(days=90))
                .order_by(OHLCVRow.symbol.asc(), OHLCVRow.ts.asc())
            )
        )
        .scalars()
        .all()
    )
    by_symbol: dict[str, list[OHLCVRow]] = {}
    for r in ohlcv_rows:
        by_symbol.setdefault(r.symbol, []).append(r)
    for sym, rows in by_symbol.items():
        if len(rows) < 10:
            continue
        closes = [float(r.close) for r in rows]
        rets = [
            (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] else 0.0
            for i in range(1, len(closes))
        ]
        if not rets:
            continue
        current = rets[-1]
        z = _zscore(rets[:-1], current)
        if abs(z) >= z_threshold:
            movers.append(
                WatchlistMover(
                    symbol=sym,
                    last_close=closes[-1],
                    return_pct=current * 100,
                    z_score=z,
                )
            )

    # --- News -------------------------------------------------------------
    news_rows = (
        (
            await db.execute(
                select(NewsRow).where(NewsRow.time >= cutoff).order_by(NewsRow.time.desc())
            )
        )
        .scalars()
        .all()
    )

    # Sort by impact_score if the column is populated; else by recency.
    def _impact(n: NewsRow) -> int:
        v = getattr(n, "impact_score", None)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    news_sorted = sorted(news_rows, key=_impact, reverse=True)[:news_top]
    news = [
        NewsDelta(
            title=str(n.title),
            source=str(getattr(n, "source", "")),
            impact_score=_impact(n),
            sentiment=float(getattr(n, "sentiment_score", 0.0) or 0.0),
            published_at=n.time,
            url=getattr(n, "url", None),
        )
        for n in news_sorted
    ]

    return ChangesTodayResponse(
        window_hours=hours,
        cutoff=cutoff,
        signals=signals,
        regime_flips=flips,
        movers=movers,
        news=news,
    )
