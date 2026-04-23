"""Prefect flow: backlog-clear news rows whose ``sentiment`` is NULL.

Uses the shared sentiment service (FinBERT + CryptoBERT) through the
queue consumer. Safe to run repeatedly — the consumer drops rows that
already have a sentiment score.
"""

from __future__ import annotations

import asyncio

from prefect import flow, get_run_logger, task

from pfip.sentiment.queue_consumer import drain_redis_queue, process_unscored


@task(name="drain-redis-then-db")
async def _drain() -> int:
    # Redis first (fast path), then DB scan to mop up.
    via_redis = await drain_redis_queue()
    via_db = await process_unscored(limit=128)
    return via_redis + via_db


@flow(name="classify-news-backlog", log_prints=True)
async def classify_news_backlog_flow(passes: int = 3) -> int:
    """Classify un-scored news rows in up to ``passes`` batches."""
    log = get_run_logger()
    total = 0
    for i in range(passes):
        count = await _drain()
        log.info(f"pass {i + 1}: scored {count} rows")
        total += count
        if count == 0:
            break
    log.info(f"classify-news-backlog: scored {total} rows total")
    return total


if __name__ == "__main__":
    asyncio.run(classify_news_backlog_flow())
