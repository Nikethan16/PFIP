"""Frankfurter — ECB reference FX rates (no key).

Endpoint: https://api.frankfurter.app/latest?from=EUR&to=USD,INR,GBP,JPY...

We store per-pair OHLCV rows with open=high=low=close=rate, timeframe=1d.
Also fetches historical range via /YYYY-MM-DD..YYYY-MM-DD endpoint.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_ohlcv_rows

log = get_logger("pfip.ingest.fx.frankfurter")

BASE = "https://api.frankfurter.app"

_DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("EUR", "USD"),
    ("USD", "INR"),
    ("GBP", "USD"),
    ("EUR", "INR"),
    ("USD", "JPY"),
    ("USD", "CNY"),
]


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def fetch_frankfurter(
    pairs: Iterable[tuple[str, str]] = tuple(_DEFAULT_PAIRS),
    *,
    lookback_days: int = 400,
) -> list[dict[str, Any]]:
    """Fetch historical daily rates for each pair."""
    end = date.today()
    start = end - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    # Group by base currency to cut request count.
    by_base: dict[str, list[str]] = {}
    for base, quote in pairs:
        by_base.setdefault(base, []).append(quote)
    for base, quotes in by_base.items():
        try:
            data = await _get(
                f"/{start.isoformat()}..{end.isoformat()}",
                {"from": base, "to": ",".join(quotes)},
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"frankfurter: {base}->{quotes} failed: {type(e).__name__}: {e}")
            continue
        rates = data.get("rates") or {}
        for d_str, row in rates.items():
            try:
                t = datetime.fromisoformat(d_str).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            for q, v in row.items():
                sym = f"{base}{q}"
                rows.append(
                    {
                        "time": t,
                        "symbol": sym,
                        "market": "FX",
                        "source": "frankfurter",
                        "timeframe": "1d",
                        "open": v,
                        "high": v,
                        "low": v,
                        "close": v,
                        "volume": 0,
                    }
                )
    return rows


async def ingest_frankfurter(
    pairs: Iterable[tuple[str, str]] = tuple(_DEFAULT_PAIRS),
    *,
    lookback_days: int = 400,
    session: AsyncSession | None = None,
) -> int:
    log.info("ingest.frankfurter starting")
    rows = await fetch_frankfurter(pairs, lookback_days=lookback_days)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
    else:
        n = await upsert_ohlcv_rows(session, rows)
    log.info(f"ingest.frankfurter done: {n} rows")
    return n
