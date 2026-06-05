"""arXiv q-fin RSS — daily feed of quantitative finance pre-prints.

Pulls the q-fin RSS plus a few sub-categories. After parsing:
- Filter by watchlist keywords (symbols, common asset names) — keeps the noise
  manageable for the agent's "papers worth reading" digest.
- Trigger an embedding pass into the Qdrant ``research`` collection when the
  embedder is online.

Each entry is stored in ``news`` with category=``academic``.

URLs:
- http://rss.arxiv.org/rss/q-fin       — all q-fin
- http://rss.arxiv.org/rss/q-fin.PR    — Pricing
- http://rss.arxiv.org/rss/q-fin.ST    — Statistical Finance
- http://rss.arxiv.org/rss/q-fin.RM    — Risk Management
- http://rss.arxiv.org/rss/q-fin.TR    — Trading & Market Microstructure
- http://rss.arxiv.org/rss/q-fin.CP    — Computational Finance
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import fetch_feed

log = get_logger("pfip.ingest.academic.arxiv_qfin")

ARXIV_URLS: list[tuple[str, str, str]] = [
    ("arxiv_qfin", "academic", "http://rss.arxiv.org/rss/q-fin"),
    ("arxiv_qfin_pr", "academic", "http://rss.arxiv.org/rss/q-fin.PR"),
    ("arxiv_qfin_st", "academic", "http://rss.arxiv.org/rss/q-fin.ST"),
    ("arxiv_qfin_rm", "academic", "http://rss.arxiv.org/rss/q-fin.RM"),
    ("arxiv_qfin_tr", "academic", "http://rss.arxiv.org/rss/q-fin.TR"),
    ("arxiv_qfin_cp", "academic", "http://rss.arxiv.org/rss/q-fin.CP"),
]

# Default keywords — augmented at runtime by the active watchlist.
DEFAULT_KEYWORDS: tuple[str, ...] = (
    "bitcoin", "btc", "ethereum", "eth", "crypto",
    "stock", "equity", "etf", "futures", "options",
    "regime", "volatility", "garch", "kalman", "hmm",
    "portfolio", "risk", "hedging", "factor",
    "rsi", "macd", "momentum", "mean reversion",
    "fed", "rbi", "inflation", "cpi",
    "transformer", "lstm", "deep learning", "reinforcement",
)


async def _watchlist_keywords() -> list[str]:
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            r = await s.execute(text("SELECT symbol FROM watchlist"))
            return [row[0] for row in r.fetchall() if row and row[0]]
    except Exception as e:  # noqa: BLE001
        log.warning(f"arxiv: watchlist read failed: {type(e).__name__}: {e}")
        return []


def _filter_by_keywords(items: list[dict[str, Any]], keywords: Iterable[str]) -> list[dict[str, Any]]:
    if not items:
        return []
    patterns = [
        re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in keywords if k
    ]
    if not patterns:
        return items
    kept: list[dict[str, Any]] = []
    for it in items:
        hay = " ".join(s for s in (it.get("title"), it.get("summary")) if s)
        if not hay:
            continue
        if any(p.search(hay) for p in patterns):
            kept.append(it)
    return kept


async def fetch_arxiv_qfin(*, filter_keywords: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, cat, url in ARXIV_URLS:
        items = await fetch_feed(name, cat, url)
        out.extend(items)
    if not filter_keywords:
        return out
    keywords = list(DEFAULT_KEYWORDS) + await _watchlist_keywords()
    return _filter_by_keywords(out, keywords)


async def ingest_arxiv_qfin(
    session: AsyncSession | None = None,
    *,
    filter_keywords: bool = True,
) -> int:
    log.info("ingest.arxiv_qfin starting")
    items = await fetch_arxiv_qfin(filter_keywords=filter_keywords)
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.arxiv_qfin done: {n} rows (filtered={filter_keywords})")
    return n


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_arxiv_qfin())
