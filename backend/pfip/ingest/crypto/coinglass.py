"""Coinglass derivatives market metrics.

Free-tier endpoints (v4 public API):
- ``/api/futures/fundingRate/exchange-list``  — current funding rates
- ``/api/futures/openInterest/exchange-list`` — open interest per exchange
- ``/api/futures/longShortRatio``             — long/short ratio
- ``/api/futures/liquidation/exchange-list``  — liquidation totals

We store derived per-symbol aggregates in ``fundamentals`` with source=coinglass.

If COINGLASS_API_KEY is not set the adapter no-ops with a warning.
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

log = get_logger("pfip.ingest.crypto.coinglass")

BASE = "https://open-api-v4.coinglass.com"

_ENDPOINTS: dict[str, str] = {
    "funding_rate": "/api/futures/fundingRate/exchange-list",
    "open_interest": "/api/futures/openInterest/exchange-list",
    "long_short_ratio": "/api/futures/longShortRatio",
    "liquidation": "/api/futures/liquidation/exchange-list",
}


@retry_http(max_attempts=3)
async def _fetch(endpoint: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client(headers={"CG-API-KEY": api_key}) as client:
        r = await client.get(f"{BASE}{endpoint}", params=params or {})
        r.raise_for_status()
        return r.json()


def _extract_symbol_value(payload: Any, symbol: str, metric: str) -> float | None:
    """Best-effort scan through Coinglass' nested payload shapes for a symbol value."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if data is None:
        return None
    # Common shapes: list of dicts with {"symbol": "BTC", "list": [...]} or flat.
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            sym = entry.get("symbol") or entry.get("instrument")
            if sym and sym.upper().startswith(symbol.upper()):
                for key in (metric, f"{metric}_avg", "value", "rate", "oi_total"):
                    if key in entry and isinstance(entry[key], (int, float)):
                        return float(entry[key])
    return None


async def fetch_coinglass_metrics(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch derivatives metrics and return fundamentals-shaped rows."""
    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    if not api_key:
        log.warning("COINGLASS_API_KEY not set, coinglass ingest no-op")
        return []
    syms = symbols or ["BTC", "ETH", "SOL"]
    today = date.today()
    out: list[dict[str, Any]] = []
    for sym in syms:
        for field, endpoint in _ENDPOINTS.items():
            try:
                payload = await _fetch(endpoint, api_key, params={"symbol": sym})
            except Exception as e:  # noqa: BLE001
                log.warning(f"coinglass: {sym} {field} failed: {type(e).__name__}: {e}")
                continue
            val = _extract_symbol_value(payload, sym, field)
            if val is None:
                continue
            out.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": sym,
                    "field": f"coinglass_{field}",
                    "value": val,
                    "source": "coinglass",
                }
            )
    return out


async def ingest_coinglass(
    symbols: list[str] | None = None, session: AsyncSession | None = None
) -> int:
    """Fetch Coinglass metrics and upsert into fundamentals."""
    log.info("ingest.coinglass starting")
    rows = await fetch_coinglass_metrics(symbols=symbols)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.coinglass done: {n} rows")
    return n
