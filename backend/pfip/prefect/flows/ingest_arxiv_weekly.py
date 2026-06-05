"""Prefect flow: arXiv q-fin weekly digest.

Cadence: Saturday 09:00 IST = Saturday 03:30 UTC.

Manual run:
    python -m pfip.prefect.flows.ingest_arxiv_weekly
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task
from prefect.tasks import exponential_backoff

from pfip.ingest._common.source_health import record_run
from pfip.ingest.academic.arxiv_qfin import ingest_arxiv_qfin


@task(name="arxiv-qfin", retries=2, retry_delay_seconds=exponential_backoff(backoff_factor=10))
async def _t() -> int:
    n = 0
    err = None
    try:
        n = await ingest_arxiv_qfin()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run("arxiv_qfin", rows=n, error=err)
    return n


@flow(name="ingest-arxiv-weekly", log_prints=True)
async def ingest_arxiv_weekly() -> int:
    log = get_run_logger()
    n = await _t()
    log.info(f"ingest-arxiv-weekly rows: {n}")
    return n


if __name__ == "__main__":
    asyncio.run(ingest_arxiv_weekly())
