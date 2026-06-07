"""Kalshi — US CFTC-regulated event markets.

Public read API: https://api.elections.kalshi.com/trade-api/v2/markets
Kalshi rebranded; the primary free read path is at ``api.elections.kalshi.com``.
An API key is required for trading but the markets list is public.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.prediction_markets.kalshi")

BASE = "https://api.elections.kalshi.com/trade-api/v2"


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def fetch_kalshi(limit: int = 100) -> list[dict[str, Any]]:
    try:
        resp = await _get("/markets", {"limit": str(limit), "status": "open"})
    except Exception as e:  # noqa: BLE001
        log.warning(f"kalshi: failed: {type(e).__name__}: {e}")
        return []
    today = date.today()
    rows: list[dict[str, Any]] = []
    for m in resp.get("markets") or []:
        ticker = m.get("ticker") or m.get("market_ticker")
        if not ticker:
            continue
        # Kalshi uses cents (0-100); normalize to 0-1 probability.
        yes_bid = m.get("yes_bid")
        yes_ask = m.get("yes_ask")
        if yes_bid is None or yes_ask is None:
            continue
        try:
            mid = (float(yes_bid) + float(yes_ask)) / 200.0
        except Exception:
            continue
        rows.append(
            {
                "as_of_date": today,
                "report_date": today,
                "symbol": f"KALSHI_{ticker}"[:80],
                "field": "yes_mid",
                "value": mid,
                "source": "kalshi",
            }
        )
    return rows


async def ingest_kalshi(session: AsyncSession | None = None) -> int:
    log.info("ingest.kalshi starting")
    rows = await fetch_kalshi()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.kalshi done: {n} rows")
    return n
