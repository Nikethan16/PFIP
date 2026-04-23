"""World Bank WDI indicators — no key.

Endpoint: ``https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json``

Stores annual observations into fundamentals.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.macro.world_bank")

BASE = "https://api.worldbank.org/v2"

DEFAULT_INDICATORS: tuple[str, ...] = (
    "NY.GDP.MKTP.CD",       # GDP current US$
    "FP.CPI.TOTL.ZG",       # Inflation consumer prices annual %
    "BX.KLT.DINV.CD.WD",    # FDI, net inflows
    "NE.TRD.GNFS.ZS",       # Trade as % of GDP
)

DEFAULT_COUNTRIES: tuple[str, ...] = ("USA", "IND", "CHN", "GBR", "JPN", "EUU")


@retry_http(max_attempts=3)
async def _fetch(country: str, indicator: str) -> list[dict[str, Any]]:
    async with get_async_client() as client:
        r = await client.get(
            f"{BASE}/country/{country}/indicator/{indicator}",
            params={"format": "json", "per_page": "200"},
        )
        r.raise_for_status()
        data = r.json()
        # WB returns [metadata, list_of_rows]
        return data[1] if isinstance(data, list) and len(data) > 1 else []


async def fetch_wdi(
    countries: Iterable[str] = DEFAULT_COUNTRIES,
    indicators: Iterable[str] = DEFAULT_INDICATORS,
) -> list[dict[str, Any]]:
    today = date.today()
    out: list[dict[str, Any]] = []
    for country in countries:
        for ind in indicators:
            try:
                rows = await _fetch(country, ind)
            except Exception as e:  # noqa: BLE001
                log.warning(f"wdi: {country} {ind} failed: {type(e).__name__}: {e}")
                continue
            for r in rows:
                val = r.get("value")
                yr = r.get("date")
                if val is None or not yr:
                    continue
                try:
                    report_date = date(int(yr), 12, 31)
                    v = float(val)
                except Exception:
                    continue
                out.append(
                    {
                        "as_of_date": today,
                        "report_date": report_date,
                        "symbol": f"WB_{country}_{ind}",
                        "field": "value",
                        "value": v,
                        "source": "world_bank",
                    }
                )
    return out


async def ingest_world_bank(
    countries: Iterable[str] = DEFAULT_COUNTRIES,
    indicators: Iterable[str] = DEFAULT_INDICATORS,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.world_bank starting")
    rows = await fetch_wdi(countries, indicators)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.world_bank done: {n} rows")
    return n
