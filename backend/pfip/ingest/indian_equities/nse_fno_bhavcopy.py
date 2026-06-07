"""NSE F&O bhavcopy (derivatives EOD).

URL: ``https://archives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MON}/fo{DDMONYYYY}bhav.csv.zip``
Stores each contract's EOD close into OHLCV with source=``nse_fno`` and
timeframe=``1d``. Contract symbol format: ``{UNDERLYING}{EXPIRY-YYMMDD}{CE/PE/FUT}``.
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

log = get_logger("pfip.ingest.indian_equities.nse_fno_bhavcopy")


def _url(d: date) -> str:
    return (
        "https://archives.nseindia.com/content/historical/DERIVATIVES/"
        f"{d.strftime('%Y')}/{d.strftime('%b').upper()}/"
        f"fo{d.strftime('%d%b%Y').upper()}bhav.csv.zip"
    )


@retry_http(max_attempts=3)
async def _download(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (PFIP) " + USER_AGENT,
        "Referer": "https://www.nseindia.com/",
    }
    async with get_async_client(headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def fetch_fno_bhavcopy(d: date | None = None) -> list[dict[str, Any]]:
    d = d or (date.today() - timedelta(days=1))
    try:
        content = await _download(_url(d))
    except Exception as e:  # noqa: BLE001
        log.warning(f"nse_fno: {d} download failed: {type(e).__name__}")
        return []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f)
    df.columns = [c.strip().upper() for c in df.columns]
    rows: list[dict[str, Any]] = []
    t = datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
    for _, r in df.iterrows():
        sym = str(r.get("SYMBOL") or "").strip()
        exp = str(r.get("EXPIRY_DT") or "").strip()
        inst = str(r.get("INSTRUMENT") or "").strip()
        opt = str(r.get("OPTION_TYP") or "").strip()
        strike = r.get("STRIKE_PR") or 0
        if not sym or not inst:
            continue
        # Contract identifier
        suffix = inst if not opt or opt == "XX" else f"{inst}_{opt}_{int(float(strike))}"
        contract = f"{sym}_{exp}_{suffix}"
        rows.append(
            {
                "time": t,
                "symbol": contract,
                "market": "NSE_FNO",
                "source": "nse_fno",
                "timeframe": "1d",
                "open": r.get("OPEN", 0),
                "high": r.get("HIGH", 0),
                "low": r.get("LOW", 0),
                "close": r.get("CLOSE", 0),
                "volume": r.get("CONTRACTS", 0) or r.get("VAL_INLAKH", 0) or 0,
            }
        )
    return rows


async def ingest_fno_bhavcopy(d: date | None = None, session: AsyncSession | None = None) -> int:
    log.info("ingest.nse_fno_bhavcopy starting")
    rows = await fetch_fno_bhavcopy(d)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.nse_fno_bhavcopy done: {n} rows")
    return n
