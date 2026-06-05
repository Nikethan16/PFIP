"""NASDAQ Data Link (formerly Quandl) — free-tier datasets.

Free-tier examples used here:
- ``LBMA/GOLD``       — London gold AM/PM fix (daily)
- ``MOSL/IN10Y``      — India 10y bond yield
- ``CHRIS/CME_GC1``   — front-month gold futures (continuous)
- ``ML/USTRI``        — Merrill Lynch US Treasury index

If ``NASDAQ_DATA_LINK_API_KEY`` is not set we log a warning and no-op.

API docs: https://docs.data.nasdaq.com/docs
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.commodities.nasdaq_data_link")

BASE = "https://data.nasdaq.com/api/v3"

# Each tuple: (dataset_code, field_name, value_column_index)
# The Time-Series endpoint returns rows = [[date, ...numeric_cols]].
DEFAULT_DATASETS: tuple[tuple[str, str, int], ...] = (
    ("LBMA/GOLD", "gold_usd_am", 1),
    ("LBMA/GOLD", "gold_usd_pm", 2),
    ("LBMA/SILVER", "silver_usd", 1),
    ("MOSL/IN10Y", "india_10y_yield", 1),
    ("CHRIS/CME_GC1", "gc_futures_settle", 4),
)


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any]) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def fetch_nasdaq_data_link(
    datasets: Iterable[tuple[str, str, int]] = DEFAULT_DATASETS,
    *,
    lookback_days: int = 30,
) -> list[dict[str, Any]]:
    api_key = os.environ.get("NASDAQ_DATA_LINK_API_KEY", "").strip()
    if not api_key:
        log.warning("NASDAQ_DATA_LINK_API_KEY not set, ndl ingest no-op")
        return []
    today = date.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # dedupe (dataset, field)
    for code, field, col in datasets:
        key = (code, field)
        if key in seen:
            continue
        seen.add(key)
        try:
            j = await _get(
                f"/datasets/{code}.json",
                {"api_key": api_key, "start_date": start, "limit": 200},
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"ndl: {code} failed: {type(e).__name__}: {e}")
            continue
        ds = (j or {}).get("dataset") or {}
        rows = ds.get("data") or []
        slug = code.replace("/", "_").upper()
        for row in rows:
            if not row or len(row) <= col:
                continue
            ds_str = row[0]
            val = row[col]
            if val is None:
                continue
            try:
                obs_date = date.fromisoformat(str(ds_str))
            except Exception:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "as_of_date": today,
                    "report_date": obs_date,
                    "symbol": slug,
                    "field": field,
                    "value": v,
                    "source": "nasdaq_data_link",
                }
            )
    return out


async def ingest_nasdaq_data_link(
    *, lookback_days: int = 30, session: AsyncSession | None = None
) -> int:
    log.info("ingest.nasdaq_data_link starting")
    rows = await fetch_nasdaq_data_link(lookback_days=lookback_days)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.nasdaq_data_link done: {n} rows")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_nasdaq_data_link())
