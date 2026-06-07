"""Prefect flow: self-custody refresh every 6 hours.

Cadence: 00:00 / 06:00 / 12:00 / 18:00 IST.

Reads addresses from ``self_custody_addresses`` (migration 0002). For each
chain, calls the appropriate adapter. If the table is missing or empty the
flow no-ops gracefully.

Manual run:
    python -m pfip.prefect.flows.ingest_self_custody_6h
"""

from __future__ import annotations

import asyncio
import os

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff
from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.source_health import record_run
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
                c = (chain or "").lower()
                if c in out:
                    out[c].append(addr)
    except Exception:
        pass

    # Env-var fallback so the flow is useful even before a user adds addresses
    # via the API.
    for chain, envvar in (
        ("btc", "BTC_ADDRESSES"),
        ("eth", "ETH_ADDRESSES"),
        ("sol", "SOL_ADDRESSES"),
    ):
        raw = os.environ.get(envvar, "").strip()
        if raw:
            for a in raw.split(","):
                a = a.strip()
                if a and a not in out[chain]:
                    out[chain].append(a)
    return out


@task(
    name="btc-self-custody", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10)
)
async def _btc(addrs: list[str]) -> int:
    n = 0
    err = None
    try:
        n = await ingest_mempool_btc(addresses=addrs)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("self_custody_btc", rows=n, error=err)
    return n


@task(
    name="eth-self-custody", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10)
)
async def _eth(addrs: list[str]) -> int:
    n = 0
    err = None
    try:
        n = await ingest_etherscan(addresses=addrs)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("self_custody_eth", rows=n, error=err)
    return n


@task(
    name="sol-self-custody", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10)
)
async def _sol(addrs: list[str]) -> int:
    # Solscan: user said skipped — adapter is wired in but logs and no-ops.
    n = 0
    err = None
    try:
        n = await ingest_solscan(addresses=addrs)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("self_custody_sol", rows=n, error=err)
    return n


@flow(name="ingest-self-custody-6h", log_prints=True)
async def ingest_self_custody_6h() -> int:
    log = get_run_logger()
    by_chain = await _addresses_by_chain()
    log.info(
        f"self-custody addresses: btc={len(by_chain['btc'])} "
        f"eth={len(by_chain['eth'])} sol={len(by_chain['sol'])}"
    )
    n_btc = await _btc(by_chain["btc"])
    n_eth = await _eth(by_chain["eth"])
    n_sol = await _sol(by_chain["sol"])
    total = int(n_btc) + int(n_eth) + int(n_sol)
    log.info(f"ingest-self-custody-6h total rows: {total}")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_self_custody_6h())
