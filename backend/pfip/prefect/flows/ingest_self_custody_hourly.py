"""Prefect flow: self-custody hourly refresh.

Reads addresses from ``self_custody_addresses`` (0002 migration). For each
chain, calls the appropriate adapter. If the table is missing (pre-migration)
we log and no-op.

Schedule: every hour.
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest.self_custody.etherscan import ingest_etherscan
from pfip.ingest.self_custody.mempool_btc import ingest_mempool_btc
from pfip.ingest.self_custody.solscan import ingest_solscan


async def _addresses_by_chain() -> dict[str, list[str]]:
    factory = get_sessionmaker()
    out: dict[str, list[str]] = {"btc": [], "eth": [], "sol": []}
    try:
        async with factory() as s:
            res = await s.execute(text("SELECT chain, address FROM self_custody_addresses"))
            for chain, addr in res.fetchall():
                if chain in out:
                    out[chain].append(addr)
    except Exception:
        # Table may not exist yet (pre-0002). Just return empty and let flow no-op.
        pass
    return out


@task(name="btc", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _btc(addrs: list[str]) -> int:
    return await ingest_mempool_btc(addresses=addrs)


@task(name="eth", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _eth(addrs: list[str]) -> int:
    return await ingest_etherscan(addresses=addrs)


@task(name="sol", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _sol(addrs: list[str]) -> int:
    return await ingest_solscan(addresses=addrs)


@flow(name="ingest-self-custody-hourly", log_prints=True)
async def ingest_self_custody_hourly() -> int:
    log = get_run_logger()
    by_chain = await _addresses_by_chain()
    log.info(
        f"self-custody addresses: btc={len(by_chain['btc'])} eth={len(by_chain['eth'])} sol={len(by_chain['sol'])}"
    )
    n_btc = await _btc(by_chain["btc"])
    n_eth = await _eth(by_chain["eth"])
    n_sol = await _sol(by_chain["sol"])
    total = int(n_btc) + int(n_eth) + int(n_sol)
    log.info(f"ingest-self-custody-hourly total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_self_custody_hourly())
