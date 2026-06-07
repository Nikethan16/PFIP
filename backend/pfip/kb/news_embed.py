"""Embed news rows into the Qdrant ``news`` collection.

Consumed by :mod:`pfip.agent.graph` so the chat agent can pull the most
relevant recent-news snippets as context. The flow runs periodically as a
Prefect job; it's also importable and re-entrant.

Pipeline per row:

1. Pull ``news`` rows where ``embedded = false``.
2. Embed ``title + summary`` via ``nomic-embed-text``.
3. Upsert into Qdrant ``news`` collection with metadata:
   ``title, url, published_at, sentiment, entity_tickers, source, symbol``.
4. Mark row ``embedded = true`` in Postgres.

Safe to call many times — the ``embedded`` flag is the idempotency gate.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from loguru import logger
from prefect import flow, get_run_logger, task
from qdrant_client.http import models as qmodels
from sqlalchemy import text as sql_text

from pfip.agent.llm_client import LLMUnavailable, get_llm_router
from pfip.db.session import get_sessionmaker
from pfip.kb.search import NEWS_COLLECTION, get_qdrant

# Batch size per flow run — keeps memory flat on low-RAM hosts.
BATCH_SIZE = 200


async def _ensure_news_collection(dim: int) -> None:
    client = get_qdrant()
    try:
        await client.get_collection(NEWS_COLLECTION)
        return
    except Exception:  # noqa: BLE001
        pass
    logger.info(f"Creating Qdrant collection '{NEWS_COLLECTION}' dim={dim}")
    await client.create_collection(
        collection_name=NEWS_COLLECTION,
        vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
    )


@task(name="fetch-unembedded-news")
async def _fetch_batch(limit: int) -> list[dict[str, Any]]:
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            stmt = sql_text(
                """
                SELECT id, time, title, url, source, symbol, sentiment, summary,
                       COALESCE(entity_tickers, '[]'::jsonb) AS entity_tickers
                FROM news
                WHERE embedded = false
                ORDER BY time DESC
                LIMIT :limit
                """
            )
            result = await session.execute(stmt, {"limit": limit})
        except Exception as exc:  # noqa: BLE001 — migrations may not be applied in test
            logger.warning(f"news fetch failed: {exc}")
            return []
        return [dict(row._mapping) for row in result]


@task(name="mark-embedded")
async def _mark_embedded(ids: list[str]) -> None:
    if not ids:
        return
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = sql_text("UPDATE news SET embedded = true WHERE id = ANY(:ids)")
        await session.execute(stmt, {"ids": ids})
        await session.commit()


@flow(name="embed-news-backlog", log_prints=True)
async def embed_news_backlog(batch_size: int = BATCH_SIZE) -> int:
    """Embed up to ``batch_size`` unembedded news rows. Returns count written."""
    log = get_run_logger()
    rows = await _fetch_batch(batch_size)
    if not rows:
        log.info("No unembedded news rows")
        return 0

    router = get_llm_router()
    # Embed first row to learn dim + bootstrap collection.
    try:
        first_vec = await router.embed(_row_text(rows[0]))
    except LLMUnavailable as exc:
        log.warning(f"Embedding unavailable: {exc}")
        return 0
    await _ensure_news_collection(len(first_vec))

    vectors: list[list[float]] = [first_vec]
    for r in rows[1:]:
        try:
            vectors.append(await router.embed(_row_text(r)))
        except LLMUnavailable as exc:
            log.warning(f"Embed aborted mid-batch: {exc}")
            break

    n = len(vectors)
    client = get_qdrant()
    points = []
    for r, vec in zip(rows[:n], vectors, strict=True):
        pid = int(hashlib.sha1(str(r["id"]).encode()).hexdigest()[:15], 16)
        payload: dict[str, Any] = {
            "text": _row_text(r),
            "source_type": "news",
            "title": r["title"],
            "url": r["url"],
            "source": r["source"],
            "symbol": r.get("symbol"),
            "sentiment": float(r["sentiment"]) if r.get("sentiment") is not None else None,
            "entity_tickers": r.get("entity_tickers") or [],
            "published_at": r["time"].isoformat() if r.get("time") else None,
        }
        points.append(qmodels.PointStruct(id=pid, vector=vec, payload=payload))
    if points:
        await client.upsert(collection_name=NEWS_COLLECTION, points=points)

    await _mark_embedded([str(r["id"]) for r in rows[:n]])
    log.info(f"Embedded {n} news rows")
    return n


def _row_text(row: dict[str, Any]) -> str:
    """Concatenate title + summary for embedding."""
    bits = [row.get("title") or ""]
    if row.get("summary"):
        bits.append(row["summary"])
    return "\n".join(b for b in bits if b).strip()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(embed_news_backlog())


__all__ = ["BATCH_SIZE", "embed_news_backlog"]
