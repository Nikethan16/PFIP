"""Catalyst/event feed (Phase 3). Read-only over the ``events`` table."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from pfip.api.deps import CurrentUser, DbSession
from pfip.events.extractor import recent_events

router = APIRouter(prefix="/events", tags=["events"])


def _to_dict(e: Any) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "ticker": e.ticker,
        "kind": e.kind,
        "materiality": round(float(e.materiality), 3),
        "title": e.title,
        "summary": e.summary,
        "source_url": e.source_url,
        "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
    }


@router.get("")
async def list_events(
    db: DbSession,
    _user: CurrentUser,
    ticker: str | None = Query(None, description="Filter to one ticker."),
    days: int = Query(30, ge=1, le=180),
    min_materiality: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Recent catalysts, newest first. Filter by ticker / lookback / materiality."""
    rows = await recent_events(db, ticker=ticker, days=days, limit=limit)
    items = [_to_dict(e) for e in rows if float(e.materiality) >= min_materiality]
    return {"count": len(items), "events": items}
