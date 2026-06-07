"""Queue-driven consumer that pulls un-classified news items and scores them.

The news ingest is expected to push the row's id onto a Redis list
``pfip:news:sentiment`` after insert; this consumer drains the list in batches,
runs FinBERT / CryptoBERT, and updates the sentiment column.

Falls back to a direct DB scan (``process_unscored``) when Redis is absent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from pfip.db.session import get_sessionmaker
from pfip.models.news import NewsRow
from pfip.sentiment.finbert_classifier import SentimentService, get_sentiment_service

log = logging.getLogger(__name__)


async def process_unscored(
    *,
    limit: int = 64,
    service: SentimentService | None = None,
) -> int:
    """DB scan: classify up to ``limit`` news rows whose ``sentiment`` is NULL."""
    svc = service or get_sentiment_service()
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(NewsRow)
            .where(NewsRow.sentiment.is_(None))
            .order_by(NewsRow.time.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        rows = list(res.scalars().all())
        if not rows:
            return 0
        # Route per-source to the right model
        news_texts, news_ids, crypto_texts, crypto_ids = [], [], [], []
        for r in rows:
            text = f"{r.title}. {r.summary or ''}".strip()
            if (r.source or "").lower().startswith(("crypto", "cointel", "x_")) or _looks_crypto(
                r.symbol
            ):
                crypto_texts.append(text)
                crypto_ids.append(r.id)
            else:
                news_texts.append(text)
                news_ids.append(r.id)

        updated = 0
        for ids, texts, kind in [
            (news_ids, news_texts, "news"),
            (crypto_ids, crypto_texts, "crypto"),
        ]:
            if not ids:
                continue
            results = svc.classify(texts, kind=kind)
            for rid, res_ in zip(ids, results, strict=False):
                await session.execute(
                    update(NewsRow).where(NewsRow.id == rid).values(sentiment=res_.score)
                )
                updated += 1
        await session.commit()
        return updated


def _looks_crypto(sym: str | None) -> bool:
    if not sym:
        return False
    s = sym.upper()
    return "/" in s or s.endswith("USD") or s.endswith("USDT") or s in {"BTC", "ETH", "SOL", "BNB"}


async def drain_redis_queue(
    *,
    queue_key: str = "pfip:news:sentiment",
    batch_size: int = 32,
    max_batches: int = 64,
) -> int:
    """Drain a Redis list into the classifier. No-op if Redis is unavailable."""
    try:  # pragma: no cover
        import redis.asyncio as aioredis  # type: ignore[import-untyped]

        from pfip.core.config import get_settings

        settings = get_settings()
        client = aioredis.from_url(settings.redis_url)
    except Exception as exc:  # pragma: no cover
        log.warning("redis unavailable (%s); falling back to DB scan", exc)
        return await process_unscored()

    svc = get_sentiment_service()
    factory = get_sessionmaker()
    total = 0
    try:  # pragma: no cover
        for _ in range(max_batches):
            pipeline = client.pipeline()
            for _j in range(batch_size):
                pipeline.lpop(queue_key)
            ids_raw: list[Any] = await pipeline.execute()
            ids: list[UUID] = []
            for raw in ids_raw:
                if raw is None:
                    continue
                try:
                    ids.append(UUID(raw.decode() if isinstance(raw, bytes) else str(raw)))
                except Exception:
                    continue
            if not ids:
                break
            async with factory() as session:
                rows = []
                for rid in ids:
                    row = await session.get(NewsRow, rid)
                    if row is None or row.sentiment is not None:
                        continue
                    rows.append(row)
                if not rows:
                    continue
                texts = [f"{r.title}. {r.summary or ''}".strip() for r in rows]
                results = svc.classify_news(texts)
                for r, s in zip(rows, results, strict=False):
                    await session.execute(
                        update(NewsRow).where(NewsRow.id == r.id).values(sentiment=s.score)
                    )
                    total += 1
                await session.commit()
    finally:
        try:  # pragma: no cover
            await client.close()
        except Exception:
            pass
    return total


if __name__ == "__main__":
    asyncio.run(process_unscored())
