"""Solscan — SOL + SPL token balances + recent tx.

Public API (v2): ``https://public-api.solscan.io``.
Requires ``SOLSCAN_API_KEY`` header ``token``. If empty, adapter no-ops.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_news

log = get_logger("pfip.ingest.self_custody.solscan")

BASE = "https://public-api.solscan.io"


@retry_http(max_attempts=3)
async def _get(path: str, api_key: str, params: dict[str, Any] | None = None) -> Any:
    async with get_async_client(headers={"token": api_key}) as client:
        r = await client.get(f"{BASE}{path}", params=params or {})
        r.raise_for_status()
        return r.json()


async def fetch_addresses(addresses: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    key = os.environ.get("SOLSCAN_API_KEY", "").strip()
    if not key:
        log.warning("SOLSCAN_API_KEY not set, solscan ingest no-op")
        return [], []
    today = date.today()
    funds: list[dict[str, Any]] = []
    news: list[dict[str, Any]] = []
    for addr in addresses:
        try:
            acct = await _get(f"/account/{addr}", key)
            lamports = acct.get("lamports") or acct.get("data", {}).get("lamports") or 0
            funds.append(
                {
                    "as_of_date": today,
                    "report_date": today,
                    "symbol": addr,
                    "field": "sol_lamports",
                    "value": lamports,
                    "source": "solscan",
                }
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"solscan: balance {addr} failed: {type(e).__name__}: {e}")

        try:
            tokens = await _get(f"/account/tokens", key, {"account": addr})
            for tok in tokens if isinstance(tokens, list) else []:
                mint = tok.get("tokenAddress") or tok.get("mint")
                bal = tok.get("tokenAmount", {}).get("uiAmount") or tok.get("amount")
                if not mint or bal is None:
                    continue
                funds.append(
                    {
                        "as_of_date": today,
                        "report_date": today,
                        "symbol": f"{addr}:{mint}",
                        "field": "spl_balance",
                        "value": bal,
                        "source": "solscan",
                    }
                )
        except Exception as e:  # noqa: BLE001
            log.warning(f"solscan: tokens {addr} failed: {type(e).__name__}: {e}")

        try:
            txs = await _get(f"/account/transactions", key, {"account": addr, "limit": 20})
            for tx in txs if isinstance(txs, list) else []:
                sig = tx.get("txHash") or tx.get("signature")
                ts = tx.get("blockTime")
                if not sig:
                    continue
                t = (
                    datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    if ts
                    else datetime.now(tz=timezone.utc)
                )
                news.append(
                    {
                        "time": t,
                        "title": f"SOL tx {sig[:12]}… ({addr[:8]}…)",
                        "url": f"https://solscan.io/tx/{sig}",
                        "source": "solscan",
                        "symbol": addr,
                        "summary": f"slot={tx.get('slot')} status={tx.get('status')}",
                        "category": "self_custody_tx",
                    }
                )
        except Exception as e:  # noqa: BLE001
            log.warning(f"solscan: txs {addr} failed: {type(e).__name__}: {e}")
    return funds, news


async def ingest_solscan(
    addresses: Iterable[str] = (), session: AsyncSession | None = None
) -> int:
    log.info("ingest.solscan starting")
    addresses = list(addresses)
    if not addresses:
        log.info("solscan: no addresses, no-op")
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
    log.info(f"ingest.solscan done: {total} rows")
    return total
