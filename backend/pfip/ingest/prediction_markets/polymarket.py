"""Polymarket gamma-api prediction market prices — no key.

Endpoint: https://gamma-api.polymarket.com/events?limit=50&active=true

Each event has one or more binary outcomes with last-price in [0, 1].
We store the YES-leg last price in fundamentals as field=``pm_yes_price``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.prediction_markets.polymarket")

BASE = "https://gamma-api.polymarket.com"


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def fetch_polymarket(limit: int = 100) -> list[dict[str, Any]]:
    try:
        events = await _get("/events", {"limit": str(limit), "active": "true"})
    except Exception as e:  # noqa: BLE001
        log.warning(f"polymarket: failed: {type(e).__name__}: {e}")
        return []
    today = date.today()
    rows: list[dict[str, Any]] = []
    for ev in events if isinstance(events, list) else []:
        slug = ev.get("slug") or ev.get("id")
        if not slug:
            continue
        markets = ev.get("markets") or []
        for m in markets:
            q = m.get("question") or ev.get("title") or ""
            price = m.get("lastTradePrice") or m.get("last_price")
            if price is None:
                continue
            try:
                p = float(price)
            except Exception:
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": f"POLY_{slug}"[:80],
                    "field": "pm_yes_price",
                    "value": p,
                    "source": "polymarket",
                }
            )
            # Also store a descriptor under symbol-meta so downstream can correlate.
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": f"POLY_{slug}"[:80],
                    "field": f"label:{q[:200]}",
                    "value": None,
                    "source": "polymarket",
                }
            )
    return rows


async def ingest_polymarket(session: AsyncSession | None = None) -> int:
    log.info("ingest.polymarket starting")
    rows = await fetch_polymarket()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.polymarket done: {n} rows")
    return n
