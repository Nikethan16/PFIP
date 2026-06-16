"""Weekly arXiv digest (plan §5.7 + §12.2).

Reads ``news`` rows with ``category='academic'`` from the trailing week,
asks the LLM to rank the top 5 papers by relevance to the user's watchlist
and methodology keywords, and formats them for Telegram + dashboard.

If the LLM is unavailable, falls back to "top 5 by recency" with a note.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.agent.llm_client import LLMUnavailable, get_llm_router
from pfip.agent.prompts import load as load_prompt
from pfip.agent.sanitizer import sanitize_many

# Methodology keywords we always up-weight — tune to taste.
METHOD_KEYWORDS = (
    "walk-forward",
    "walk forward",
    "monte carlo",
    "cpcv",
    "foundation model",
    "hmm",
    "regime",
    "ensemble",
    "backtest",
    "cross-validation",
    "purged k-fold",
    "calibration",
    "reliability diagram",
)


@dataclass(frozen=True, slots=True)
class ArxivDigest:
    """Output of :func:`build_arxiv_digest`."""

    markdown: str
    used_llm: bool
    week: str
    papers_count: int


def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def _fetch_papers(db: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    try:
        stmt = sql_text(
            """
            SELECT id, time, title, url, source, summary
            FROM news
            WHERE category = 'academic'
              AND time >= :since
            ORDER BY time DESC
            LIMIT 100
            """
        )
        return [dict(r) for r in (await db.execute(stmt, {"since": since})).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"arxiv papers fetch failed: {exc}")
        return []


async def _watchlist_symbols(db: AsyncSession) -> list[str]:
    try:
        stmt = sql_text("SELECT symbol FROM watchlist LIMIT 50")
        return [r["symbol"] for r in (await db.execute(stmt)).mappings()]
    except Exception:  # noqa: BLE001
        return []


def _format_fallback(papers: list[dict[str, Any]]) -> str:
    """Recency-sorted top-5 with a disclaimer."""
    lines = ["_(LLM unavailable — showing top 5 by recency.)_\n"]
    for p in papers[:5]:
        lines.append(f"- **{p['title']}** — [arxiv]({p['url']}) _{p['time'].date()}_")
        if p.get("summary"):
            lines.append(f"  > {p['summary'][:200]}")
    return "\n".join(lines)


async def build_arxiv_digest(db: AsyncSession, as_of: datetime | None = None) -> ArxivDigest:
    """Produce the weekly arXiv digest Markdown."""
    now = as_of or datetime.now(tz=timezone.utc)
    since = now - timedelta(days=7)
    papers = await _fetch_papers(db, since)
    watchlist = await _watchlist_symbols(db)

    header = (
        f"## arXiv q-fin — papers worth reading — week of {now.date()}\n\n"
        f"_{since.date()} → {now.date()}_ · {len(papers)} papers ingested\n\n"
    )

    if not papers:
        return ArxivDigest(
            markdown=header + "_No academic papers ingested this week._\n",
            used_llm=False,
            week=_iso_week(now),
            papers_count=0,
        )

    chunks: list[tuple[str, str | None]] = [
        (f"{p['title']}\n{p.get('summary') or ''}", p["url"]) for p in papers
    ]
    safe_block, _ = sanitize_many(chunks)

    try:
        system = load_prompt("trader_persona") + (
            "\n\n---\nYou are ranking arXiv q-fin papers for a retail quant. "
            "Rank the top 5 by relevance to the user's watchlist and "
            "methodology keywords. Output a numbered markdown list with one "
            "sentence of value ('why read this') and cite the URL. Papers "
            "lacking methodology rigor or relevance should be dropped."
        )
        prompt = (
            f"Watchlist tickers: {watchlist}\n"
            f"Methodology keywords to up-weight: {METHOD_KEYWORDS}\n\n"
            f"Candidate papers:\n{safe_block}"
        )
        body = (await get_llm_router().generate(prompt, system=system)).strip()
        return ArxivDigest(
            markdown=header + body,
            used_llm=True,
            week=_iso_week(now),
            papers_count=len(papers),
        )
    except LLMUnavailable as exc:
        logger.warning(f"arxiv digest LLM unavailable: {exc}")
        return ArxivDigest(
            markdown=header + _format_fallback(papers),
            used_llm=False,
            week=_iso_week(now),
            papers_count=len(papers),
        )


__all__ = ["ArxivDigest", "METHOD_KEYWORDS", "build_arxiv_digest"]
