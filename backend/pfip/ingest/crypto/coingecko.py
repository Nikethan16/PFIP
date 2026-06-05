"""CoinGecko daily market-cap aggregator.

Uses the free demo key (``COINGECKO_API_KEY``). Endpoints:
- ``/api/v3/coins/markets``   — paginated market caps + volumes
- ``/api/v3/global``           — total crypto market cap + dominance

Stored as fundamentals rows (one per coin, plus DEFI_TOTAL aggregate).

Free demo key allows 10k calls/month; we only do ~3 calls per run.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.crypto.coingecko")

BASE = "https://api.coingecko.com/api/v3"


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    key = os.environ.get("COINGECKO_API_KEY", "").strip()
    if key:
        h["x-cg-demo-api-key"] = key
    return h


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client(headers=_headers()) as client:
        r = await client.get(f"{BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def fetch_coingecko_snapshot(
    *, top_n: int = 50, vs_currency: str = "usd"
) -> list[dict[str, Any]]:
    """Return per-coin market cap rows + a global aggregate row."""
    today = date.today()
    out: list[dict[str, Any]] = []

    # Per-coin market caps
    try:
        coins = await _get(
            "/coins/markets",
            params={
                "vs_currency": vs_currency,
                "order": "market_cap_desc",
                "per_page": top_n,
                "page": 1,
                "sparkline": "false",
            },
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"coingecko: /coins/markets failed: {type(e).__name__}: {e}")
        coins = []

    if isinstance(coins, list):
        for c in coins:
            sym = str(c.get("symbol") or "").upper()
            if not sym:
                continue
            mcap = c.get("market_cap")
            vol = c.get("total_volume")
            price = c.get("current_price")
            if mcap is not None:
                out.append(
                    {
                        "as_of_date": today,
                        "report_date": today,
                        "symbol": sym,
                        "field": "market_cap_usd",
                        "value": mcap,
                        "source": "coingecko",
                    }
                )
            if vol is not None:
                out.append(
                    {
                        "as_of_date": today,
                        "report_date": today,
                        "symbol": sym,
                        "field": "volume_24h_usd",
                        "value": vol,
                        "source": "coingecko",
                    }
                )
            if price is not None:
                out.append(
                    {
                        "as_of_date": today,
                        "report_date": today,
                        "symbol": sym,
                        "field": "price_usd",
                        "value": price,
                        "source": "coingecko",
                    }
                )

    # Global stats
    try:
        glob = await _get("/global")
    except Exception as e:  # noqa: BLE001
        log.warning(f"coingecko: /global failed: {type(e).__name__}: {e}")
        glob = None

    if isinstance(glob, dict):
        data = glob.get("data") or {}
        total_mcap = (data.get("total_market_cap") or {}).get(vs_currency)
        if total_mcap is not None:
            out.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": "CRYPTO_TOTAL",
                    "field": "market_cap_usd",
                    "value": total_mcap,
                    "source": "coingecko",
                }
            )
        btc_dom = (data.get("market_cap_percentage") or {}).get("btc")
        if btc_dom is not None:
            out.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": "BTC",
                    "field": "dominance_pct",
                    "value": btc_dom,
                    "source": "coingecko",
                }
            )
    return out


async def ingest_coingecko(
    *, top_n: int = 50, session: AsyncSession | None = None
) -> int:
    log.info("ingest.coingecko starting")
    rows = await fetch_coingecko_snapshot(top_n=top_n)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.coingecko done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_coingecko())
