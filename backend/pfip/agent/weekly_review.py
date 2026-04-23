"""Weekly post-mortem aggregator (plan §12.2).

Every Sunday 19:00 IST, this flow:

- reads all holdings closed in the trailing 7 days,
- reads all signals generated in the trailing 7 days,
- reads all journal entries edited in the trailing 7 days,
- asks the LLM to produce a "system did / you did / what to change" summary.

The result is persisted as a journal row with ``kind='weekly_review'``.
(The ``journal`` table doesn't carry a ``kind`` column today; we encode
the tag in ``notes`` as ``kind:weekly_review``.)
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


@dataclass(frozen=True, slots=True)
class WeeklyReview:
    """Output of :func:`build_weekly_review`."""

    markdown: str
    used_llm: bool
    week: str
    closed_count: int
    signal_count: int


def _iso_week(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


async def _closed_holdings(db: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    try:
        stmt = sql_text(
            """
            SELECT id, symbol, category, acquired_at, closed_at,
                   cost_basis_inr, exit_price_inr
            FROM holdings
            WHERE closed_at >= :since
            ORDER BY closed_at DESC
            """
        )
        return [dict(r) for r in (await db.execute(stmt, {"since": since})).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"closed holdings fetch failed: {exc}")
        return []


async def _signals_since(db: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    try:
        stmt = sql_text(
            """
            SELECT id, asset, direction, confidence, regime, generated_at
            FROM signals WHERE generated_at >= :since
            ORDER BY generated_at DESC
            LIMIT 200
            """
        )
        return [dict(r) for r in (await db.execute(stmt, {"since": since})).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"signals fetch failed: {exc}")
        return []


async def _journal_since(db: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    try:
        stmt = sql_text(
            """
            SELECT id, created_at, symbol, direction, thesis
            FROM journal WHERE created_at >= :since
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        return [dict(r) for r in (await db.execute(stmt, {"since": since})).mappings()]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"journal fetch failed: {exc}")
        return []


async def build_weekly_review(db: AsyncSession, as_of: datetime | None = None) -> WeeklyReview:
    """Produce the weekly review Markdown — does NOT write to the journal."""
    now = as_of or datetime.now(tz=timezone.utc)
    since = now - timedelta(days=7)

    closed = await _closed_holdings(db, since)
    signals = await _signals_since(db, since)
    journal = await _journal_since(db, since)

    chunks: list[tuple[str, str | None]] = []
    for h in closed[:20]:
        chunks.append((f"CLOSED: {h!r}", f"db://holdings/{h['id']}"))
    for s in signals[:20]:
        chunks.append((f"SIGNAL: {s!r}", f"db://signals/{s['id']}"))
    for j in journal[:20]:
        chunks.append((f"JOURNAL: {j!r}", f"db://journal/{j['id']}"))
    safe_block, _ = sanitize_many(chunks)

    header = f"## Weekly Review — {_iso_week(now)}\n\n_{since.date()} → {now.date()}_\n\n"

    try:
        router = get_llm_router()
        persona = load_prompt("trader_persona")
        system = (
            persona
            + "\n\n---\nProduce a weekly review with exactly three sections:\n"
            "1. **What the system did** (signal stats, calibration hits/misses).\n"
            "2. **What you did** (journal entries, closed positions, deviations).\n"
            "3. **What to change** (concrete, citable process tweaks).\n"
            "Every bullet must cite a db:// ref or a news URL."
        )
        prompt = f"Context:\n{safe_block}"
        body = (await router.generate(prompt, system=system)).strip()
        return WeeklyReview(
            markdown=header + body,
            used_llm=True,
            week=_iso_week(now),
            closed_count=len(closed),
            signal_count=len(signals),
        )
    except LLMUnavailable as exc:
        logger.warning(f"weekly review LLM unavailable: {exc}")
        body = (
            "### What the system did\n"
            f"- {len(signals)} signals generated this week.\n\n"
            "### What you did\n"
            f"- {len(closed)} holdings closed, {len(journal)} journal entries.\n\n"
            "### What to change\n"
            "- _LLM unavailable; fill in manually._\n"
        )
        return WeeklyReview(
            markdown=header + body,
            used_llm=False,
            week=_iso_week(now),
            closed_count=len(closed),
            signal_count=len(signals),
        )


async def persist_weekly_review(db: AsyncSession, review: WeeklyReview, symbol: str = "__META__") -> None:
    """Store the weekly review as a journal row tagged ``kind:weekly_review``."""
    stmt = sql_text(
        """
        INSERT INTO journal (symbol, direction, thesis, pre_trade_checklist, notes)
        VALUES (:symbol, 'HOLD', :thesis, '{}'::jsonb, :notes)
        """
    )
    await db.execute(
        stmt,
        {
            "symbol": symbol,
            "thesis": review.markdown[:8000],
            "notes": f"kind:weekly_review week:{review.week}",
        },
    )
    await db.commit()


__all__ = ["WeeklyReview", "build_weekly_review", "persist_weekly_review"]
