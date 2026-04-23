"""mempool.space — BTC address balance + tx history (no key).

API:
- GET /api/address/{addr}                -> balance summary
- GET /api/address/{addr}/txs            -> recent transactions

We store a per-address fundamentals snapshot:
    symbol = address, field = "btc_balance_sat", value = chain_stats.funded - spent
Recent txs are stored as news rows with category=``self_custody_tx``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_news

log = get_logger("pfip.ingest.self_custody.mempool_btc")

BASE = "https://mempool.space/api"


@retry_http(max_attempts=3)
async def _get(path: str) -> Any:
    async with get_async_client() as client:
        r = await client.get(f"{BASE}{path}")
        r.raise_for_status()
        return r.json()


async def fetch_address_snapshot(address: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (fundamentals_rows, news_rows) for a single BTC address."""
    funds: list[dict[str, Any]] = []
    news: list[dict[str, Any]] = []
    today = date.today()
    try:
        summary = await _get(f"/address/{address}")
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_btc: balance {address} failed: {type(e).__name__}: {e}")
        return funds, news
    chain = summary.get("chain_stats") or {}
    mempool = summary.get("mempool_stats") or {}
    bal_sat = (
        (chain.get("funded_txo_sum") or 0)
        - (chain.get("spent_txo_sum") or 0)
        + (mempool.get("funded_txo_sum") or 0)
        - (mempool.get("spent_txo_sum") or 0)
    )
    funds.append(
        {
            "as_of_date": today,
            "report_date": today,
            "symbol": address,
            "field": "btc_balance_sat",
            "value": bal_sat,
            "source": "mempool",
        }
    )

    try:
        txs = await _get(f"/address/{address}/txs")
    except Exception as e:  # noqa: BLE001
        log.warning(f"mempool_btc: txs {address} failed: {type(e).__name__}: {e}")
        return funds, news
    if not isinstance(txs, list):
        return funds, news
    for tx in txs[:50]:
        tx_id = tx.get("txid")
        if not tx_id:
            continue
        ts = (tx.get("status") or {}).get("block_time")
        t = (
            datetime.fromtimestamp(int(ts), tz=timezone.utc)
            if ts
            else datetime.now(tz=timezone.utc)
        )
        news.append(
            {
                "time": t,
                "title": f"BTC tx {tx_id[:12]}… ({address[:8]}…)",
                "url": f"https://mempool.space/tx/{tx_id}",
                "source": "mempool",
                "symbol": address,
                "summary": f"fee={tx.get('fee')} vbytes={tx.get('weight', 0)//4}",
                "category": "self_custody_tx",
            }
        )
    return funds, news


async def ingest_mempool_btc(
    addresses: Iterable[str] = (),
    session: AsyncSession | None = None,
) -> int:
    """Fetch snapshots for each BTC address."""
    log.info("ingest.mempool_btc starting")
    addresses = list(addresses)
    if not addresses:
        log.info("mempool_btc: no addresses given, no-op")
        return 0
    all_funds: list[dict[str, Any]] = []
    all_news: list[dict[str, Any]] = []
    for addr in addresses:
        f, n = await fetch_address_snapshot(addr)
        all_funds.extend(f)
        all_news.extend(n)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            a = await upsert_fundamentals(s, all_funds)
            b = await upsert_news(s, all_news)
    else:
        a = await upsert_fundamentals(session, all_funds)
        b = await upsert_news(session, all_news)
    total = a + b
    log.info(f"ingest.mempool_btc done: {total} rows")
    return total
