"""Prefect flow: hourly crypto OHLCV + on-chain refresh.

Cadence: every hour at :05 UTC.
Symbols: BTC-USD, ETH-USD, SOL-USD, BNB-USD on Coinbase (primary) + Kraken/
Bybit/OKX (fallback per exchange-specific symbol rewrite).

Each task reports rows-ingested into Prefect logs and writes to source_health.

Manual run:
    python -m pfip.prefect.flows.ingest_crypto_hourly
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterable

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest._common.source_health import record_run
from pfip.ingest.crypto.ccxt_multi import ingest_watchlist
from pfip.ingest.crypto.coingecko import ingest_coingecko
from pfip.ingest.crypto.coinmetrics_community import ingest_coinmetrics
from pfip.ingest.crypto.defillama import ingest_defillama
from pfip.ingest.crypto.glassnode import ingest_glassnode
from pfip.ingest.crypto.mempool_space import ingest_mempool_space

DEFAULT_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD")


@task(name="ccxt-multi", retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _ccxt(symbols: list[str], timeframe: str, lookback_hours: int) -> int:
    # The adapter takes lookback_days (it computes `since` internally). Convert
    # the flow's lookback_hours into days, rounding up so we always have at
    # least 1 day of coverage even for short lookbacks.
    lookback_days = max(1, (int(lookback_hours) + 23) // 24)
    n = 0
    err: str | None = None
    try:
        n = await ingest_watchlist(
            symbols=symbols, timeframe=timeframe, lookback_days=lookback_days
        )
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("ccxt_multi", rows=n, error=err)
    return n


@task(name="defillama", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _defillama() -> int:
    n = 0
    err = None
    try:
        n = await ingest_defillama()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("defillama", rows=n, error=err)
    return n


@task(name="coinmetrics", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _coinmetrics() -> int:
    n = 0
    err = None
    try:
        n = await ingest_coinmetrics()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("coinmetrics", rows=n, error=err)
    return n


@task(name="coingecko", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _coingecko() -> int:
    n = 0
    err = None
    try:
        n = await ingest_coingecko()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("coingecko", rows=n, error=err)
    return n


@task(name="glassnode", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _glassnode() -> int:
    n = 0
    err = None
    try:
        n = await ingest_glassnode()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("glassnode", rows=n, error=err)
    return n


@task(name="mempool-space", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _mempool() -> int:
    n = 0
    err = None
    try:
        n = await ingest_mempool_space()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        await record_run("mempool_space", rows=n, error=err)
    return n


@flow(name="ingest-crypto-hourly", log_prints=True)
async def ingest_crypto_hourly(
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    timeframe: str = "1h",
    lookback_hours: int = 6,
    on_chain_every_n_runs: int = 24,  # on-chain metrics are daily — only run once a day
    run_index: int = 0,
) -> int:
    """Hourly OHLCV + on-chain metric refresh.

    On-chain adapters (DeFiLlama, CoinMetrics, CoinGecko, Glassnode,
    mempool.space) only run when ``run_index % on_chain_every_n_runs == 0``
    to respect free-tier limits. Prefect can pass run_index via the
    deployment parameters.
    """
    log = get_run_logger()
    syms = list(symbols)
    n_ohlcv = await _ccxt(syms, timeframe, lookback_hours)
    total = int(n_ohlcv)
    if run_index % max(1, on_chain_every_n_runs) == 0:
        results = await asyncio.gather(
            _defillama(),
            _coinmetrics(),
            _coingecko(),
            _glassnode(),
            _mempool(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                log.warning(f"on-chain task failed: {type(r).__name__}: {r}")
                continue
            total += int(r)
    log.info(f"ingest-crypto-hourly total rows: {total} (ohlcv={n_ohlcv})")
    return total


if __name__ == "__main__":
    asyncio.run(ingest_crypto_hourly())
