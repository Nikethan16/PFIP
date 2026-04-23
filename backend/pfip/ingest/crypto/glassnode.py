"""Glassnode free-tier BTC on-chain metrics.

Free-tier endpoints used:
- ``/v1/metrics/market/mvrv``  — MVRV ratio (tier 1)
- ``/v1/metrics/transactions/transfers_volume_exchanges_net`` — exchange netflow
- ``/v1/metrics/addresses/active_count`` — active addresses
- ``/v1/metrics/mining/hash_rate_mean`` — hash rate

All rows are stored in ``fundamentals`` with symbol=``BTC``, source=``glassnode``,
``as_of_date = report_date = t`` where t is the metric date. Values are numeric.

If ``GLASSNODE_API_KEY`` is not set the adapter logs a warning and no-ops.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.crypto.glassnode")

BASE = "https://api.glassnode.com"

_METRICS: dict[str, str] = {
    "mvrv": "/v1/metrics/market/mvrv",
    "exchange_netflow": "/v1/metrics/transactions/transfers_volume_exchanges_net",
    "active_addresses": "/v1/metrics/addresses/active_count",
    "hash_rate": "/v1/metrics/mining/hash_rate_mean",
}


@retry_http(max_attempts=3)
async def _fetch(endpoint: str, api_key: str, asset: str = "BTC", interval: str = "24h") -> list[dict[str, Any]]:
    async with get_async_client() as client:
        r = await client.get(
            f"{BASE}{endpoint}",
            params={"a": asset, "api_key": api_key, "i": interval},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return data


async def fetch_glassnode_metrics(asset: str = "BTC") -> list[dict[str, Any]]:
    """Return fundamentals-shaped rows for all registered metrics."""
    api_key = os.environ.get("GLASSNODE_API_KEY", "").strip()
    if not api_key:
        log.warning("GLASSNODE_API_KEY not set, glassnode ingest no-op")
        return []
    today = date.today()
    out: list[dict[str, Any]] = []
    for field, endpoint in _METRICS.items():
        try:
            raw = await _fetch(endpoint, api_key, asset=asset)
        except Exception as e:  # noqa: BLE001
            log.warning(f"glassnode: {field} failed: {type(e).__name__}: {e}")
            continue
        for point in raw:
            ts = point.get("t")
            val = point.get("v")
            if ts is None or val is None:
                continue
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            out.append(
                {
                    "as_of_date": today,
                    "report_date": d,
                    "symbol": asset,
                    "field": f"glassnode_{field}",
                    "value": val,
                    "source": "glassnode",
                }
            )
    return out


async def ingest_glassnode(
    asset: str = "BTC", session: AsyncSession | None = None
) -> int:
    """Fetch Glassnode metrics and upsert into fundamentals."""
    log.info("ingest.glassnode starting")
    rows = await fetch_glassnode_metrics(asset=asset)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.glassnode done: {n} rows")
    return n
