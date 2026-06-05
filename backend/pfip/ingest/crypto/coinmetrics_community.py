"""CoinMetrics community-tier on-chain metrics — no key required.

Endpoint: ``https://community-api.coinmetrics.io/v4/timeseries/asset-metrics``
Free tier exposes ~30 daily metrics for BTC and ETH. We pull a curated subset.

Stored as fundamentals rows with source=``coinmetrics``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.crypto.coinmetrics_community")

BASE = "https://community-api.coinmetrics.io/v4"

# Community-tier metrics (each is free and covers BTC+ETH on the community API).
_METRICS: tuple[str, ...] = (
    "AdrActCnt",          # active addresses
    "TxCnt",              # tx count
    "TxTfrValAdjUSD",     # adjusted tx volume USD
    "FeeTotUSD",          # total fees USD
    "SplyCur",            # current supply
    "CapMrktCurUSD",      # market cap USD
    "HashRate",           # hash rate (BTC only — silently dropped for ETH)
    "BlkCnt",             # block count
    "IssTotUSD",          # issuance USD
    "VelCur1yr",          # velocity
)


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any]) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def fetch_coinmetrics(
    assets: Iterable[str] = ("btc", "eth"),
    *,
    lookback_days: int = 7,
) -> list[dict[str, Any]]:
    """Fetch the latest ``lookback_days`` of all metrics for each asset."""
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    out: list[dict[str, Any]] = []
    for asset in assets:
        params: dict[str, Any] = {
            "assets": asset,
            "metrics": ",".join(_METRICS),
            "frequency": "1d",
            "start_time": start,
            "end_time": today.isoformat(),
            "page_size": 1000,
        }
        try:
            j = await _get("/timeseries/asset-metrics", params)
        except Exception as e:  # noqa: BLE001
            log.warning(f"coinmetrics: {asset} failed: {type(e).__name__}: {e}")
            continue
        data = j.get("data") or []
        for row in data:
            try:
                obs_date = datetime.fromisoformat(
                    row["time"].replace("Z", "+00:00")
                ).date()
            except Exception:
                obs_date = today
            for metric in _METRICS:
                v = row.get(metric)
                if v is None or v == "":
                    continue
                try:
                    val = float(v)
                except (TypeError, ValueError):
                    continue
                out.append(
                    {
                        "as_of_date": today,  # data was visible to us today
                        "report_date": obs_date,
                        "symbol": asset.upper(),
                        "field": f"cm_{metric}",
                        "value": val,
                        "source": "coinmetrics",
                    }
                )
    return out


async def ingest_coinmetrics(
    assets: Iterable[str] = ("btc", "eth"),
    *,
    lookback_days: int = 7,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.coinmetrics_community starting")
    rows = await fetch_coinmetrics(assets, lookback_days=lookback_days)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.coinmetrics_community done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_coinmetrics())
