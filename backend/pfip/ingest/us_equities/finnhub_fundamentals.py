"""Finnhub fundamentals + earnings calendar.

Endpoints used (free tier):
- ``/stock/metric?symbol={sym}&metric=all``  — company metrics
- ``/calendar/earnings?from=&to=&symbol=``    — earnings calendar

Company metrics are stored in fundamentals. Earnings calendar is stored as news
with category=``earnings_calendar`` (URL is a synthetic, stable identifier).

If FINNHUB_API_KEY not set, adapter logs warning and no-ops.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_news

log = get_logger("pfip.ingest.us_equities.finnhub_fundamentals")

BASE = "https://finnhub.io/api/v1"


@retry_http(max_attempts=3)
async def _get(endpoint: str, token: str, params: dict[str, Any]) -> Any:
    p = dict(params)
    p["token"] = token
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{endpoint}", params=p)
        r.raise_for_status()
        return r.json()


async def fetch_finnhub_metrics(symbols: Iterable[str]) -> list[dict[str, Any]]:
    """Fetch /stock/metric for each symbol and flatten to fundamentals rows."""
    token = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not token:
        log.warning("FINNHUB_API_KEY not set, finnhub metrics no-op")
        return []
    today = date.today()
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            resp = await _get("/stock/metric", token, {"symbol": sym, "metric": "all"})
        except Exception as e:  # noqa: BLE001
            log.warning(f"finnhub: {sym} metric failed: {type(e).__name__}: {e}")
            continue
        metric = resp.get("metric") or {}
        for k, v in metric.items():
            if not isinstance(v, (int, float)):
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": sym.upper(),
                    "field": f"finnhub_{k}",
                    "value": float(v),
                    "source": "finnhub",
                }
            )
    return rows


async def fetch_earnings_calendar(days_ahead: int = 30) -> list[dict[str, Any]]:
    """Return earnings events as news-shaped rows."""
    token = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not token:
        log.warning("FINNHUB_API_KEY not set, finnhub earnings calendar no-op")
        return []
    now = datetime.now(tz=timezone.utc)
    params = {
        "from": now.date().isoformat(),
        "to": (now + timedelta(days=days_ahead)).date().isoformat(),
    }
    try:
        resp = await _get("/calendar/earnings", token, params)
    except Exception as e:  # noqa: BLE001
        log.warning(f"finnhub: earnings calendar failed: {type(e).__name__}: {e}")
        return []
    earnings = resp.get("earningsCalendar") or []
    items: list[dict[str, Any]] = []
    for e in earnings:
        sym = e.get("symbol")
        d = e.get("date")
        if not sym or not d:
            continue
        url = f"pfip://finnhub/earnings/{sym}/{d}"
        items.append(
            {
                "time": datetime.fromisoformat(d).replace(tzinfo=timezone.utc),
                "title": f"Earnings: {sym} on {d}",
                "url": url,
                "source": "finnhub",
                "symbol": sym,
                "summary": f"EPS est {e.get('epsEstimate')} / revenue est {e.get('revenueEstimate')}",
                "category": "earnings_calendar",
            }
        )
    return items


async def ingest_finnhub(
    symbols: Iterable[str] = ("SPY", "AAPL", "MSFT", "GOOGL"),
    session: AsyncSession | None = None,
) -> int:
    """Ingest finnhub metrics + earnings. Returns total rows written."""
    log.info("ingest.finnhub_fundamentals starting")
    metrics = await fetch_finnhub_metrics(symbols)
    earnings = await fetch_earnings_calendar()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n1 = await upsert_fundamentals(s, metrics)
            n2 = await upsert_news(s, earnings)
    else:
        n1 = await upsert_fundamentals(session, metrics)
        n2 = await upsert_news(session, earnings)
    total = n1 + n2
    log.info(f"ingest.finnhub_fundamentals done: {total} rows")
    return total
