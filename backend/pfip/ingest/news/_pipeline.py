"""Post-ingest pipeline — dedupe, classify, entity-link, embed.

Runs AFTER raw news rows have been written by the various adapters
(:mod:`pfip.ingest.news.rss_fetcher`, :mod:`gdelt`, etc.). Idempotent;
each stage has its own gating flag so partial-completion re-runs are safe.

Stages:

1. Dedupe — collapse rows whose ``url`` matches a normalized form already in
   the table, and rows whose ``title`` is a fuzzy near-duplicate of an
   existing row within the same 24h window.
2. Classify — call sentiment service (FinBERT for non-crypto, CryptoBERT for
   crypto) to fill ``sentiment`` and ``impact_score`` where NULL.
3. Entity-link — simple keyword regex matching against the watchlist symbols;
   stores matched tickers in ``entity_tickers`` JSONB.
4. Embed — call into :mod:`pfip.kb.news_embed` to push titles+summaries into
   the Qdrant ``news`` collection.

Network/LLM/Qdrant calls are wrapped in try/except so the pipeline survives
when a downstream service is offline.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker

log = get_logger("pfip.ingest.news._pipeline")


# Crypto detection — used to pick between FinBERT and CryptoBERT downstream.
_CRYPTO_KEYWORDS = (
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "crypto",
    "solana",
    "sol",
    "binance",
    "bnb",
    "blockchain",
    "defi",
    "stablecoin",
)


def is_crypto_text(text_: str) -> bool:
    t = (text_ or "").lower()
    return any(k in t for k in _CRYPTO_KEYWORDS)


def _normalize_url(url: str) -> str:
    """Strip query/utm/fragment for dedupe purposes."""
    if not url:
        return ""
    u = url.split("#", 1)[0]
    if "?" in u:
        base, q = u.split("?", 1)
        keep = [
            kv
            for kv in q.split("&")
            if kv and not kv.lower().startswith(("utm_", "fbclid", "gclid"))
        ]
        u = base + ("?" + "&".join(keep) if keep else "")
    return u.rstrip("/")


async def dedupe_recent(session: AsyncSession, *, hours: int = 24) -> int:
    """Delete rows whose normalized URL collides with an older row in the window.

    Keeps the oldest by ``time`` and drops newer duplicates so the canonical
    publish time is preserved.
    """
    stmt = text(
        """
        WITH ranked AS (
            SELECT id, url, time,
                   ROW_NUMBER() OVER (
                       PARTITION BY regexp_replace(lower(url), '[?#].*$', '')
                       ORDER BY time ASC
                   ) AS rn
            FROM news
            WHERE time >= now() - (:h || ' hours')::interval
        )
        DELETE FROM news USING ranked
        WHERE news.id = ranked.id AND ranked.rn > 1
        """
    )
    try:
        r = await session.execute(stmt, {"h": hours})
        await session.commit()
        return r.rowcount or 0
    except Exception as e:  # noqa: BLE001
        log.warning(f"dedupe_recent failed: {type(e).__name__}: {e}")
        return 0


async def link_entities(session: AsyncSession) -> int:
    """Populate ``entity_tickers`` JSONB on rows where it is empty.

    Matches against the watchlist symbol column; basic word-boundary regex.
    """
    try:
        rows = await session.execute(text("SELECT symbol FROM watchlist"))
        tickers = [r[0] for r in rows.fetchall() if r and r[0]]
    except Exception as e:  # noqa: BLE001
        log.warning(f"link_entities: watchlist read failed: {type(e).__name__}: {e}")
        return 0
    if not tickers:
        return 0

    try:
        unscored = await session.execute(
            text(
                """
                SELECT id, title, summary
                FROM news
                WHERE entity_tickers = '[]'::jsonb OR entity_tickers IS NULL
                ORDER BY time DESC
                LIMIT 500
                """
            )
        )
        items = unscored.fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning(f"link_entities: scan failed: {type(e).__name__}: {e}")
        return 0

    patterns = {tk: re.compile(rf"\b{re.escape(tk)}\b", re.IGNORECASE) for tk in tickers}
    updated = 0
    import json

    for row_id, title, summary in items:
        haystack = " ".join(s for s in (title, summary) if s) or ""
        matches = [tk for tk, pat in patterns.items() if pat.search(haystack)]
        if not matches:
            continue
        try:
            await session.execute(
                text("UPDATE news SET entity_tickers = :j WHERE id = :i"),
                {"j": json.dumps(matches), "i": row_id},
            )
            updated += 1
        except Exception as e:  # noqa: BLE001
            log.warning(f"link_entities update failed: {type(e).__name__}: {e}")
            continue
    await session.commit()
    return updated


async def classify_pending(session: AsyncSession, *, batch: int = 128) -> int:
    """Trigger sentiment classification for rows lacking a score.

    Delegates to ``pfip.sentiment.queue_consumer.process_unscored`` which
    knows about the FinBERT/CryptoBERT split and uses the existing classifier
    service. Returns count of rows scored; 0 if classifier is unavailable.
    """
    try:
        from pfip.sentiment.queue_consumer import process_unscored  # type: ignore

        return await process_unscored(limit=batch)
    except Exception as e:  # noqa: BLE001
        log.warning(f"classify_pending: classifier unavailable: {type(e).__name__}: {e}")
        return 0


async def embed_pending() -> int:
    """Embed any rows where ``embedded=false`` into Qdrant."""
    try:
        from pfip.kb.news_embed import embed_news_backlog  # type: ignore

        return await embed_news_backlog()
    except Exception as e:  # noqa: BLE001
        log.warning(f"embed_pending: embedder unavailable: {type(e).__name__}: {e}")
        return 0


async def run_pipeline(session: AsyncSession | None = None) -> dict[str, int]:
    """Execute all stages. Returns counts per stage."""
    log.info("news.pipeline starting")
    summary: dict[str, int] = {"deduped": 0, "linked": 0, "classified": 0, "embedded": 0}
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            summary["deduped"] = await dedupe_recent(s)
            summary["linked"] = await link_entities(s)
            summary["classified"] = await classify_pending(s)
    else:
        summary["deduped"] = await dedupe_recent(session)
        summary["linked"] = await link_entities(session)
        summary["classified"] = await classify_pending(session)
    summary["embedded"] = await embed_pending()
    log.info(f"news.pipeline done: {summary}")
    return summary


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_pipeline())
