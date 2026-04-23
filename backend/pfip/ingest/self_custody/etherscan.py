"""Etherscan — ETH + ERC-20 address balances + tx.

Rate limit: 5 req/s on free tier. We enforce a 0.25 s gap between calls.
API key required — if ETHERSCAN_API_KEY is empty we log a warning and no-op.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_news

log = get_logger("pfip.ingest.self_custody.etherscan")

BASE = "https://api.etherscan.io/api"
_DELAY_SEC = 0.25  # 4 req/s, under the 5/s free-tier limit


@retry_http(max_attempts=3)
async def _get(params: dict[str, Any]) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(BASE, params=params)
        r.raise_for_status()
        return r.json()


async def _eth_balance(address: str, api_key: str) -> Decimal | None:
    try:
        p = {
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
            "apikey": api_key,
        }
        j = await _get(p)
        if j.get("status") != "1" and j.get("message") != "OK":
            return None
        wei = Decimal(str(j.get("result") or 0))
        return wei / Decimal(10**18)
    except Exception as e:  # noqa: BLE001
        log.warning(f"etherscan: balance {address} failed: {type(e).__name__}: {e}")
        return None


async def _recent_txs(address: str, api_key: str) -> list[dict[str, Any]]:
    try:
        p = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 25,
            "sort": "desc",
            "apikey": api_key,
        }
        j = await _get(p)
        return j.get("result") or []
    except Exception as e:  # noqa: BLE001
        log.warning(f"etherscan: txs {address} failed: {type(e).__name__}: {e}")
        return []


async def fetch_addresses(addresses: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    api_key = os.environ.get("ETHERSCAN_API_KEY", "").strip()
    if not api_key:
        log.warning("ETHERSCAN_API_KEY not set, etherscan ingest no-op")
        return [], []
    today = date.today()
    funds: list[dict[str, Any]] = []
    news: list[dict[str, Any]] = []
    for addr in addresses:
        bal = await _eth_balance(addr, api_key)
        await asyncio.sleep(_DELAY_SEC)
        if bal is not None:
            funds.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": addr,
                    "field": "eth_balance",
                    "value": bal,
                    "source": "etherscan",
                }
            )
        txs = await _recent_txs(addr, api_key)
        await asyncio.sleep(_DELAY_SEC)
        for tx in txs:
            h = tx.get("hash")
            ts = tx.get("timeStamp")
            if not h or not ts:
                continue
            try:
                t = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except Exception:
                t = datetime.now(tz=timezone.utc)
            news.append(
                {
                    "time": t,
                    "title": f"ETH tx {h[:12]}… ({addr[:8]}…)",
                    "url": f"https://etherscan.io/tx/{h}",
                    "source": "etherscan",
                    "symbol": addr,
                    "summary": f"value_wei={tx.get('value')} gas={tx.get('gasUsed')}",
                    "category": "self_custody_tx",
                }
            )
    return funds, news


async def ingest_etherscan(
    addresses: Iterable[str] = (), session: AsyncSession | None = None
) -> int:
    log.info("ingest.etherscan starting")
    addresses = list(addresses)
    if not addresses:
        log.info("etherscan: no addresses, no-op")
        return 0
    funds, news = await fetch_addresses(addresses)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            a = await upsert_fundamentals(s, funds)
            b = await upsert_news(s, news)
    else:
        a = await upsert_fundamentals(session, funds)
        b = await upsert_news(session, news)
    total = a + b
    log.info(f"ingest.etherscan done: {total} rows")
    return total
