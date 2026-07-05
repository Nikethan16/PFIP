"""AMFI daily NAV feed.

Endpoint: https://www.amfiindia.com/spages/NAVAll.txt (tab/semicolon-delimited).
The file contains one row per scheme with:
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

We store each scheme's NAV as an OHLCV row with source=``amfi``,
symbol = scheme_code (as string), market = ``MF_INDIA``. open=high=low=close=nav.

Volume is 0 (meaningless for MFs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.indian_mf.amfi_nav")

URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# Market labels a MF holding/watchlist row may carry.
_MF_MARKETS = ("mutual_fund", "mf", "india_mf", "mf_india", "amfi")


async def _tracked_scheme_ids(session: AsyncSession) -> set[str]:
    """Identifiers (scheme code, ``MF_<code>``, or ISIN) of the MFs the user
    actually holds or watchlists.

    AMFI's NAVAll.txt lists ~50,000 schemes; upserting all of them into a
    free-tier Neon over the network is what blows the pipeline's time budget.
    We only need NAVs for schemes the user tracks, so we filter to this set
    before the upsert. Empty set ⇒ nothing to ingest (a fast, correct no-op).
    """
    ids: set[str] = set()
    try:
        # Holdings: MF category, keyed by symbol and/or ISIN.
        rows = (
            await session.execute(
                text(
                    "SELECT symbol, isin FROM holdings "
                    "WHERE lower(category) IN :mkts AND closed_at IS NULL"
                ).bindparams(bindparam("mkts", expanding=True)),
                {"mkts": list(_MF_MARKETS)},
            )
        ).all()
        for sym, isin in rows:
            for v in (sym, isin):
                if v:
                    ids.add(str(v).strip().upper())
    except Exception as e:  # noqa: BLE001 — never break ingest on the lookup
        log.debug(f"amfi: holdings MF lookup failed: {type(e).__name__}: {e}")
    try:
        rows = (
            await session.execute(
                text("SELECT symbol FROM watchlist WHERE lower(market) IN :mkts").bindparams(
                    bindparam("mkts", expanding=True)
                ),
                {"mkts": list(_MF_MARKETS)},
            )
        ).all()
        for (sym,) in rows:
            if sym:
                ids.add(str(sym).strip().upper())
    except Exception as e:  # noqa: BLE001
        log.debug(f"amfi: watchlist MF lookup failed: {type(e).__name__}: {e}")
    # Normalise ``MF_<code>`` ⇄ ``<code>`` so either storage form matches.
    for v in list(ids):
        if v.startswith("MF_"):
            ids.add(v[3:])
        else:
            ids.add(f"MF_{v}")
    return ids


@retry_http(max_attempts=3)
async def _download() -> str:
    # AMFI now 302-redirects NAVAll.txt; httpx does NOT follow redirects by
    # default, so without this the adapter got a tiny redirect page (0 NAV rows)
    # and could hang. With follow_redirects it pulls the full ~1.6MB file in <1s.
    async with get_async_client(headers={"Accept": "text/plain"}) as client:
        r = await client.get(URL, follow_redirects=True, timeout=60.0)
        r.raise_for_status()
        return r.text


async def fetch_amfi_nav(allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """Parse AMFI NAVAll.txt into OHLCV rows.

    ``allowed`` (upper-cased scheme codes / ``MF_<code>`` / ISINs) filters to the
    schemes the user tracks. ``None`` keeps everything (explicit full sync);
    an empty set keeps nothing.
    """
    try:
        txt = await _download()
    except Exception as e:  # noqa: BLE001
        log.warning(f"amfi_nav: download failed: {type(e).__name__}: {e}")
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("Scheme Code") or ";" not in line:
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        code, isin_g, isin_d, name, nav_str, date_str = parts[:6]
        if allowed is not None:
            keys = {code.upper(), f"MF_{code}".upper(), isin_g.upper(), isin_d.upper()}
            if keys.isdisjoint(allowed):
                continue
        try:
            nav = float(nav_str)
        except ValueError:
            continue
        try:
            d = datetime.strptime(date_str, "%d-%b-%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rows.append(
            {
                "time": d,
                "symbol": f"MF_{code}",
                "market": "MF_INDIA",
                "source": "amfi",
                "timeframe": "1d",
                "open": nav,
                "high": nav,
                "low": nav,
                "close": nav,
                "volume": 0,
            }
        )
    return rows


async def ingest_amfi_nav(session: AsyncSession | None = None, *, include_all: bool = False) -> int:
    """Ingest AMFI NAVs for tracked schemes (or all when ``include_all=True``).

    Default: filter to the MFs the user holds/watchlists — the whole ~50k-scheme
    file no longer heads-of-line-blocks the nightly pipeline. With no tracked
    MFs this is a fast, correct no-op (0 rows).
    """
    log.info("ingest.amfi_nav starting")

    async def _run(s: AsyncSession) -> int:
        allowed: set[str] | None = None
        if not include_all:
            allowed = await _tracked_scheme_ids(s)
            if not allowed:
                log.info("amfi_nav: no tracked MF schemes; skipping (0 rows)")
                return 0
        rows = await fetch_amfi_nav(allowed)
        n = await upsert_ohlcv_rows(s, rows)
        log.info(f"ingest.amfi_nav done: {n} rows ({'all' if include_all else 'tracked'})")
        return n

    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            return await _run(s)
    return await _run(session)
