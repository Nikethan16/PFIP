"""arXiv q-fin RSS — daily feed of quantitative finance pre-prints.

URL: ``http://rss.arxiv.org/rss/q-fin`` (covers all q-fin subcategories).
Each entry is stored in news with category=``academic``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_news
from pfip.ingest.news.rss_fetcher import fetch_feed

log = get_logger("pfip.ingest.academic.arxiv_qfin")

ARXIV_URLS: list[tuple[str, str, str]] = [
    ("arxiv_qfin", "academic", "http://rss.arxiv.org/rss/q-fin"),
    ("arxiv_qfin_pr", "academic", "http://rss.arxiv.org/rss/q-fin.PR"),  # Pricing of securities
    ("arxiv_qfin_st", "academic", "http://rss.arxiv.org/rss/q-fin.ST"),  # Statistical finance
    ("arxiv_qfin_rm", "academic", "http://rss.arxiv.org/rss/q-fin.RM"),  # Risk management
]


async def fetch_arxiv_qfin() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, cat, url in ARXIV_URLS:
        items = await fetch_feed(name, cat, url)
        out.extend(items)
    return out


async def ingest_arxiv_qfin(session: AsyncSession | None = None) -> int:
    log.info("ingest.arxiv_qfin starting")
    items = await fetch_arxiv_qfin()
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_news(s, items)
    else:
        n = await upsert_news(session, items)
    log.info(f"ingest.arxiv_qfin done: {n} rows")
    return n
