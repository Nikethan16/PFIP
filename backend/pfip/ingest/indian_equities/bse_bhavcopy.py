"""BSE EOD bhavcopy.

URL pattern (ZIP, per-date): ``https://www.bseindia.com/download/BhavCopy/Equity/EQ{DDMMYY}_CSV.ZIP``.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.indian_equities.bse_bhavcopy")


def _url(d: date) -> str:
    return (
        "https://www.bseindia.com/download/BhavCopy/Equity/"
        f"EQ{d.strftime('%d%m%y')}_CSV.ZIP"
    )


@retry_http(max_attempts=3)
async def _download(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Referer": "https://www.bseindia.com/",
    }
    async with get_async_client(headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def fetch_bse_bhavcopy(d: date | None = None) -> list[dict[str, Any]]:
    d = d or (date.today() - timedelta(days=1))
    try:
        content = await _download(_url(d))
    except Exception as e:  # noqa: BLE001
        log.warning(f"bse_bhavcopy: download failed {d}: {type(e).__name__}")
        return []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f)
    df.columns = [c.strip().upper() for c in df.columns]
    rows: list[dict[str, Any]] = []
    t = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
    for _, r in df.iterrows():
        code = r.get("SC_CODE") or r.get("SC CODE")
        name = r.get("SC_NAME") or r.get("SC NAME") or ""
        if code is None:
            continue
        sym = str(code).strip() + ".BO"
        rows.append(
            {
                "time": t,
                "symbol": sym,
                "market": "BSE",
                "source": "bse_bhavcopy",
                "timeframe": "1d",
                "open": r.get("OPEN", 0),
                "high": r.get("HIGH", 0),
                "low": r.get("LOW", 0),
                "close": r.get("CLOSE", 0),
                "volume": r.get("NO_OF_SHRS", r.get("NO.OF.SHRS", 0)) or 0,
            }
        )
    return rows


async def ingest_bse_bhavcopy(
    d: date | None = None, session: AsyncSession | None = None
) -> int:
    log.info("ingest.bse_bhavcopy starting")
    rows = await fetch_bse_bhavcopy(d)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.bse_bhavcopy done: {n} rows")
    return n
