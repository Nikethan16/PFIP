"""DBnomics aggregator — no key.

https://api.db.nomics.world/v22/series?series_ids=...

Used as a fallback for when FRED is rate-limited and to pull non-US series
(ECB, RBI, OECD) by ID. Stores values in ``fundamentals``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.macro.dbnomics")

BASE = "https://api.db.nomics.world/v22/series"

DEFAULT_SERIES: tuple[str, ...] = (
    "ECB/EXR/D.USD.EUR.SP00.A",         # ECB USD/EUR daily
    "OECD/MEI/IND.CPALTT01.IXOB.M",     # OECD CPI index
    "IMF/IFS/M.IN.FILR_PA",             # IMF India CPI
)


@retry_http(max_attempts=3)
async def _fetch(series_id: str) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(BASE, params={"series_ids": series_id})
        r.raise_for_status()
        return r.json()


async def fetch_dbnomics(series_ids: Iterable[str] = DEFAULT_SERIES) -> list[dict[str, Any]]:
    today = date.today()
    rows: list[dict[str, Any]] = []
    for sid in series_ids:
        try:
            resp = await _fetch(sid)
        except Exception as e:  # noqa: BLE001
            log.warning(f"dbnomics: {sid} failed: {type(e).__name__}: {e}")
            continue
        docs = (resp.get("series") or {}).get("docs") or []
        for doc in docs:
            periods = doc.get("period") or []
            values = doc.get("value") or []
            for p, v in zip(periods, values):
                if v is None:
                    continue
                try:
                    d = date.fromisoformat(str(p)[:10])
                    val = float(v)
                except Exception:
                    continue
                rows.append(
                    {
                        "as_of_date": today,
                        "report_date": d,
                        "symbol": sid,
                        "field": "value",
                        "value": val,
                        "source": "dbnomics",
                    }
                )
    return rows


async def ingest_dbnomics(
    series_ids: Iterable[str] = DEFAULT_SERIES, session: AsyncSession | None = None
) -> int:
    log.info("ingest.dbnomics starting")
    rows = await fetch_dbnomics(series_ids)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.dbnomics done: {n} rows")
    return n
