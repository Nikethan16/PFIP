"""mempool.space — BTC mempool, hashrate, fees daily snapshot (no key).

Distinct from :mod:`pfip.ingest.self_custody.mempool_btc` which uses
mempool.space to read user-owned addresses. This module pulls *network-level*
aggregate stats and stores them as fundamentals for BTC.

Endpoints used:
- ``/api/v1/fees/recommended``       — current fee estimates (sat/vB)
- ``/api/v1/mining/hashrate/3d``     — hash rate
- ``/api/mempool``                   — mempool size + fee histogram
- ``/api/blocks/tip/height``         — chain tip height
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.crypto.mempool_space")

BASE = "https://mempool.space/api"


@retry_http(max_attempts=3)
async def _get(path: str) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}")
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text


async def fetch_mempool_snapshot() -> list[dict[str, Any]]:
    """Return fundamentals rows capturing today's BTC network snapshot."""
    today = date.today()
    out: list[dict[str, Any]] = []

    # Fees
    try:
        fees = await _get("/v1/fees/recommended")
        if isinstance(fees, dict):
            for k in ("fastestFee", "halfHourFee", "hourFee", "economyFee", "minimumFee"):
                v = fees.get(k)
                if v is not None:
                    out.append(
                        {
                            "as_of_date": today,
                            "report_date": today,
                            "symbol": "BTC",
                            "field": f"mempool_{k}",
                            "value": float(v),
                            "source": "mempool",
                        }
                    )
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_space: fees failed: {type(e).__name__}: {e}")

    # Hashrate (3d window — latest sample)
    try:
        hr = await _get("/v1/mining/hashrate/3d")
        latest = None
        if isinstance(hr, dict):
            arr = hr.get("hashrates") or []
            if arr and isinstance(arr, list):
                latest = arr[-1].get("avgHashrate")
        if latest is not None:
            out.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": "BTC",
                    "field": "mempool_hashrate_3d",
                    "value": float(latest),
                    "source": "mempool",
                }
            )
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_space: hashrate failed: {type(e).__name__}: {e}")

    # Mempool size
    try:
        mp = await _get("/mempool")
        if isinstance(mp, dict):
            for k in ("count", "vsize", "total_fee"):
                v = mp.get(k)
                if v is not None:
                    out.append(
                        {
                            "as_of_date": today,
                            "report_date": today,
                            "symbol": "BTC",
                            "field": f"mempool_{k}",
                            "value": float(v),
                            "source": "mempool",
                        }
                    )
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_space: mempool failed: {type(e).__name__}: {e}")

    # Chain tip height
    try:
        tip = await _get("/blocks/tip/height")
        if tip is not None:
            try:
                height = int(str(tip).strip())
                out.append(
                    {
                        "as_of_date": today,
                        "report_date": today,
                        "symbol": "BTC",
                        "field": "chain_tip_height",
                        "value": height,
                        "source": "mempool",
                    }
                )
            except ValueError:
                pass
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_space: tip failed: {type(e).__name__}: {e}")

    return out


async def ingest_mempool_space(session: AsyncSession | None = None) -> int:
    log.info("ingest.mempool_space starting")
    rows = await fetch_mempool_snapshot()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.mempool_space done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_mempool_space())
