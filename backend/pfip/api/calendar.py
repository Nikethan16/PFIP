"""Corporate calendar API (D6).

``GET /calendar`` returns corporate announcements + regulatory filings for the
symbols you hold or watch, grouped by date. Data is the ``news`` table filtered
to ``corp_announcement`` / ``sec_filing`` categories (NSE announcements, SEC
8-Ks, etc.) — the real events we ingest, not forward earnings estimates.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy import text as sql_text

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.news import NewsRow
from pfip.research.calendar import CalendarDay, CalendarEvent, group_by_date

router = APIRouter(prefix="/calendar", tags=["calendar"])

_CAL_CATEGORIES = ("corp_announcement", "sec_filing")


class CalendarResponse(BaseModel):
    days: list[CalendarDay]
    n_events: int
    scoped_to_holdings: bool  # False ⇒ we fell back to the whole feed
    disclaimer: str = (
        "Corporate announcements and filings we've ingested for your names — "
        "not forward earnings estimates. Informational, not advice."
    )


@router.get("", response_model=CalendarResponse)
async def calendar(
    db: DbSession, _user: CurrentUser, days: int = 45, limit: int = 200
) -> CalendarResponse:
    """Corporate announcements + filings for held/watchlisted names, by date."""
    symbols = await _my_symbols(db)
    since = datetime.now(tz=UTC) - timedelta(days=max(1, days))

    stmt = select(NewsRow).where(
        NewsRow.category.in_(_CAL_CATEGORIES),
        NewsRow.time >= since,
    )
    # corp_announcement / sec_filing rows carry `symbol` directly (set by the
    # NSE / SEC ingests), so a plain symbol filter captures the user's names.
    scoped = bool(symbols)
    if scoped:
        stmt = stmt.where(NewsRow.symbol.in_(symbols))
    stmt = stmt.order_by(NewsRow.time.desc()).limit(limit)

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:  # noqa: BLE001 — array overlap unsupported / empty schema
        rows = []

    events = [
        CalendarEvent(
            symbol=r.symbol,
            title=r.title,
            category=r.category,
            url=r.url,
            at=r.time,
        )
        for r in rows
    ]
    grouped = group_by_date(events)
    return CalendarResponse(days=grouped, n_events=len(events), scoped_to_holdings=scoped)


async def _my_symbols(db: DbSession) -> list[str]:
    """Union of holdings + watchlist symbols. Best-effort."""
    out: set[str] = set()
    for table in ("holdings", "watchlist"):
        try:
            rows = (await db.execute(sql_text(f"SELECT DISTINCT symbol FROM {table}"))).all()
            out.update(r[0] for r in rows if r[0])
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)
