"""Prefect flow: arXiv q-fin daily."""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest.academic.arxiv_qfin import ingest_arxiv_qfin


@task(name="arxiv-qfin", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _t() -> int:
    return await ingest_arxiv_qfin()


@flow(name="ingest-arxiv-daily", log_prints=True)
async def ingest_arxiv_daily() -> int:
    log = get_run_logger()
    n = await _t()
    log.info(f"ingest-arxiv-daily rows: {n}")
    return n


if __name__ == "__main__":
    asyncio.run(ingest_arxiv_daily())
