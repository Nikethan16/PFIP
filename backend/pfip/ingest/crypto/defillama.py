"""DeFiLlama TVL / fees / yields / stablecoins — no API key required.

Endpoints:
- https://api.llama.fi/protocols                  — all protocols with TVL
- https://api.llama.fi/overview/fees              — fees
- https://yields.llama.fi/pools                   — yields
- https://stablecoins.llama.fi/stablecoins        — stablecoin mcaps

We pull a digest snapshot per run and record aggregate values as fundamentals
keyed by a pseudo-symbol (e.g. ``DEFI_TOTAL``, per-protocol slug in chunks).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals

log = get_logger("pfip.ingest.crypto.defillama")


@retry_http(max_attempts=3)
async def _get_json(url: str) -> Any:
    async with get_async_client() as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


async def fetch_defillama_snapshot(max_protocols: int = 50) -> list[dict[str, Any]]:
    """Return a list of fundamentals rows capturing a daily snapshot."""
    today = date.today()
    rows: list[dict[str, Any]] = []

    # --- protocols / total TVL ---
    try:
        protocols = await _get_json("https://api.llama.fi/protocols")
    except Exception as e:  # noqa: BLE001
        log.warning(f"defillama: protocols failed: {type(e).__name__}: {e}")
        protocols = []

    if isinstance(protocols, list):
        top = sorted(
            (p for p in protocols if isinstance(p, dict)),
            key=lambda p: float(p.get("tvl") or 0),
            reverse=True,
        )[:max_protocols]
        total_tvl = sum(float(p.get("tvl") or 0) for p in protocols if isinstance(p, dict))
        rows.append(
            {
                "as_of_date": today,
                "report_date": today,
                "symbol": "DEFI_TOTAL",
                "field": "tvl_usd",
                "value": total_tvl,
                "source": "defillama",
            }
        )
        for p in top:
            slug = str(p.get("slug") or p.get("name") or "").upper()
            if not slug:
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": f"DEFI_{slug}",
                    "field": "tvl_usd",
                    "value": float(p.get("tvl") or 0),
                    "source": "defillama",
                }
            )

    # --- stablecoins total mcap ---
    try:
        stables = await _get_json("https://stablecoins.llama.fi/stablecoins")
        total_mcap = 0.0
        for s in stables.get("peggedAssets", []) if isinstance(stables, dict) else []:
            circ = s.get("circulating") or {}
            total_mcap += float(circ.get("peggedUSD") or 0)
        if total_mcap:
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": "STABLES_TOTAL",
                    "field": "mcap_usd",
                    "value": total_mcap,
                    "source": "defillama",
                }
            )
    except Exception as e:  # noqa: BLE001
        log.warning(f"defillama: stablecoins failed: {type(e).__name__}: {e}")

    # --- yields top pools ---
    try:
        yields_resp = await _get_json("https://yields.llama.fi/pools")
        pools = yields_resp.get("data", []) if isinstance(yields_resp, dict) else []
        pools_sorted = sorted(
            (p for p in pools if isinstance(p, dict)),
            key=lambda p: float(p.get("tvlUsd") or 0),
            reverse=True,
        )[:25]
        for p in pools_sorted:
            proj = str(p.get("project") or "").upper()
            sym = str(p.get("symbol") or "").upper().replace("-", "_")
            if not proj or not sym:
                continue
            apy = p.get("apy")
            if apy is None:
                continue
            rows.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": f"YIELD_{proj}_{sym}",
                    "field": "apy_pct",
                    "value": float(apy),
                    "source": "defillama",
                }
            )
    except Exception as e:  # noqa: BLE001
        log.warning(f"defillama: yields failed: {type(e).__name__}: {e}")

    return rows


async def ingest_defillama(session: AsyncSession | None = None) -> int:
    """Fetch a DeFiLlama snapshot and upsert into fundamentals."""
    log.info("ingest.defillama starting")
    rows = await fetch_defillama_snapshot()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fundamentals(s, rows)
    else:
        n = await upsert_fundamentals(session, rows)
    log.info(f"ingest.defillama done: {n} rows")
    return n
