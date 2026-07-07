"""Corporate calendar — pure grouping of corporate events by date.

The events themselves come from the ``news`` table (rows classified as
``corp_announcement`` or ``sec_filing`` — board meetings, results, dividends,
8-Ks, etc.). This module just groups a flat list into date buckets, newest
first, so it's trivially unit-testable. Forward-dated earnings *estimates* need
an external provider we don't have; this surfaces the real announcements/filings
we already ingest.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    symbol: Optional[str] = None
    title: str
    category: str  # "corp_announcement" | "sec_filing"
    url: Optional[str] = None
    at: datetime


class CalendarDay(BaseModel):
    date: date
    events: list[CalendarEvent]


def group_by_date(events: list[CalendarEvent]) -> list[CalendarDay]:
    """Bucket events by calendar date (of ``at``), newest day first."""
    buckets: dict[date, list[CalendarEvent]] = {}
    for e in events:
        buckets.setdefault(e.at.date(), []).append(e)
    days = [
        CalendarDay(date=d, events=sorted(evs, key=lambda x: x.at, reverse=True))
        for d, evs in buckets.items()
    ]
    days.sort(key=lambda d: d.date, reverse=True)
    return days
