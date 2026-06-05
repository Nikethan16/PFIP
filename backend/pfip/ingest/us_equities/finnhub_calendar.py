"""Alias of :mod:`pfip.ingest.economic_calendar.finnhub_calendar`.

The historical implementation lives under ``economic_calendar``; this alias
matches the path called out in FEATURES.md / M1.
"""

from __future__ import annotations

from pfip.ingest.economic_calendar.finnhub_calendar import (  # noqa: F401
    fetch_economic_calendar,
    ingest_finnhub_calendar,
)

__all__ = ["fetch_economic_calendar", "ingest_finnhub_calendar"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_finnhub_calendar())
