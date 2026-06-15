"""Auto-draft a post-mortem for a closed holding.

Called from the API (``POST /agent/post-mortem``) or from the weekly
post-mortem aggregator. Fetches all relevant context from Postgres, hands
it to the LLM via the ``post_mortem_drafter`` prompt, and returns a
Markdown draft. The *user* confirms (or edits) the draft in the UI
before it is persisted to the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.agent.llm_client import (
    ChatMessage,
    LLMAllProvidersFailed,
    LLMUnavailable,
    get_llm_client,
)
from pfip.agent.prompts import load as load_prompt
from pfip.agent.router import Sensitivity, TaskType
from pfip.agent.sanitizer import sanitize_many


@dataclass(frozen=True, slots=True)
class PostMortemDraft:
    """Output of :func:`draft_post_mortem`."""

    holding_id: UUID
    markdown: str
    used_llm: bool
    warnings: list[str]


async def _holding(db: AsyncSession, hid: UUID) -> dict[str, Any] | None:
    try:
        stmt = sql_text("""
            SELECT id, category, symbol, isin, broker, acquired_at, qty,
                   cost_basis_inr, fx_rate, closed_at, exit_price_inr, notes
            FROM holdings WHERE id = :hid LIMIT 1
            """)
        row = (await db.execute(stmt, {"hid": str(hid)})).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"holding fetch failed: {exc}")
        return None
    return dict(row) if row else None


async def _entry_signal(
    db: AsyncSession, symbol: str, entry_time: datetime
) -> dict[str, Any] | None:
    try:
        stmt = sql_text("""
            SELECT id, asset, direction, confidence, regime,
                   model_name, model_version, generated_at, drivers, counter_arguments
            FROM signals
            WHERE asset = :asset
              AND generated_at <= :t
              AND generated_at > :cutoff
            ORDER BY generated_at DESC
            LIMIT 1
            """)
        cutoff = entry_time - timedelta(hours=48)
        row = (
            (await db.execute(stmt, {"asset": symbol, "t": entry_time, "cutoff": cutoff}))
            .mappings()
            .first()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"entry signal fetch failed: {exc}")
        return None
    return dict(row) if row else None


async def _calibration_at(
    db: AsyncSession, model_name: str, model_version: str, as_of: datetime
) -> dict[str, Any] | None:
    try:
        stmt = sql_text("""
            SELECT id, model_name, model_version, as_of, brier_score, ece, reliability
            FROM calibration
            WHERE model_name = :mn AND model_version = :mv AND as_of <= :t
            ORDER BY as_of DESC
            LIMIT 1
            """)
        row = (
            (await db.execute(stmt, {"mn": model_name, "mv": model_version, "t": as_of}))
            .mappings()
            .first()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"calibration fetch failed: {exc}")
        return None
    return dict(row) if row else None


async def _news_around(
    db: AsyncSession, symbol: str, around: datetime, window_hours: int = 48
) -> list[dict[str, Any]]:
    start = around - timedelta(hours=window_hours)
    end = around + timedelta(hours=window_hours)
    try:
        stmt = sql_text("""
            SELECT id, time, title, url, source, sentiment
            FROM news
            WHERE (symbol = :sym OR :sym = ANY(SELECT jsonb_array_elements_text(COALESCE(entity_tickers, '[]'::jsonb))))
              AND time BETWEEN :start AND :end
            ORDER BY (COALESCE(ABS(sentiment), 0)) DESC, time DESC
            LIMIT 3
            """)
        rows = [
            dict(r)
            for r in (
                await db.execute(stmt, {"sym": symbol, "start": start, "end": end})
            ).mappings()
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"news fetch failed: {exc}")
        rows = []
    return rows


async def _journal_row(db: AsyncSession, symbol: str, since: datetime) -> dict[str, Any] | None:
    try:
        stmt = sql_text("""
            SELECT id, created_at, symbol, direction, thesis, pre_trade_checklist, notes
            FROM journal
            WHERE symbol = :sym AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT 1
            """)
        row = (
            (await db.execute(stmt, {"sym": symbol, "since": since - timedelta(days=1)}))
            .mappings()
            .first()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"journal fetch failed: {exc}")
        return None
    return dict(row) if row else None


def _fallback_markdown(holding: dict[str, Any], warnings: list[str]) -> str:
    """Produce a safe, data-only post-mortem when the LLM is unavailable."""
    acquired = holding["acquired_at"]
    closed = holding.get("closed_at") or datetime.now(tz=timezone.utc)
    entry = float(holding["cost_basis_inr"])
    exit_price = float(holding.get("exit_price_inr") or 0)
    pnl = exit_price - entry if exit_price else None
    pct = (pnl / entry * 100) if (pnl is not None and entry) else None
    warn = ("\n".join(f"- warning: {w}" for w in warnings)) if warnings else ""
    return (
        f"## Post-mortem — {holding.get('symbol') or '?'} closed "
        f"{closed.strftime('%Y-%m-%d')}\n\n"
        f"### Thesis outcome\n"
        f"- Original thesis: _not enough data_\n"
        f"- Realised P&L: {'_n/a_' if pnl is None else f'₹{pnl:+,.0f} ({pct:+.2f}%)'}\n"
        f"- Holding period: {(closed - acquired).days} days "
        f"(`db://holdings/{holding['id']}`)\n\n"
        f"### Signal review\n"
        f"- Entry signal: _not matched_\n\n"
        f"### What I'd do differently\n"
        f"- _LLM was unavailable; fill in manually._\n\n"
        f"### What the system would do differently\n"
        f"- _not enough data_\n\n"
        f"### Tag for pattern-tracking\n"
        f"- other\n"
        f"{warn}\n"
    )


async def draft_post_mortem(db: AsyncSession, holding_id: UUID) -> PostMortemDraft:
    """Build a post-mortem draft for ``holding_id``.

    Returns the markdown plus a ``used_llm`` flag so the UI can say
    "drafted by LLM" vs "data-only fallback".
    """
    warnings: list[str] = []
    holding = await _holding(db, holding_id)
    if holding is None:
        raise ValueError(f"holding {holding_id} not found")
    if holding.get("closed_at") is None:
        warnings.append("holding is not closed; post-mortem is premature")

    symbol = holding.get("symbol") or holding.get("isin") or "?"
    entry_time = holding["acquired_at"]
    exit_time = holding.get("closed_at") or datetime.now(tz=timezone.utc)

    signal = await _entry_signal(db, symbol, entry_time)
    calibration = None
    if signal:
        calibration = await _calibration_at(
            db, signal["model_name"], signal["model_version"], entry_time
        )
    journal = await _journal_row(db, symbol, entry_time)
    news_entry = await _news_around(db, symbol, entry_time)
    news_exit = await _news_around(db, symbol, exit_time)

    # Build sanitized context block.
    chunks: list[tuple[str, str | None]] = []
    chunks.append((f"HOLDING: {holding!r}", f"db://holdings/{holding['id']}"))
    if signal:
        chunks.append((f"ENTRY_SIGNAL: {signal!r}", f"db://signals/{signal['id']}"))
    if calibration:
        chunks.append(
            (f"CALIBRATION_AT_ENTRY: {calibration!r}", f"db://calibration/{calibration['id']}")
        )
    if journal:
        chunks.append((f"JOURNAL: {journal!r}", f"db://journal/{journal['id']}"))
    for n in news_entry:
        chunks.append((f"NEWS_AT_ENTRY: {n['title']}", n["url"]))
    for n in news_exit:
        chunks.append((f"NEWS_AT_EXIT: {n['title']}", n["url"]))

    safe_block, flagged = sanitize_many(chunks)
    if flagged:
        warnings.append(f"prompt-injection patterns suppressed: {flagged}")

    try:
        system = load_prompt("post_mortem_drafter")
        client = get_llm_client()
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(
                role="user",
                content=(
                    f"Holding ID: {holding_id}\n"
                    f"Draft a post-mortem using the template. Context:\n\n{safe_block}\n"
                ),
            ),
        ]
        # Post-mortems concern your real holdings → SENSITIVE. Strict mode
        # forces local Ollama; non-strict routes to DeepSeek-R1 for best
        # chain-of-thought analysis on a closed position.
        md_raw = await client.complete(
            messages,
            task=TaskType.POST_MORTEM,
            sensitivity=Sensitivity.SENSITIVE,
            max_tokens=2000,
            temperature=0.2,
        )
        md = md_raw.strip()
        return PostMortemDraft(holding_id=holding_id, markdown=md, used_llm=True, warnings=warnings)
    except (LLMUnavailable, LLMAllProvidersFailed) as exc:
        warnings.append(f"LLM unavailable: {exc}")
        md = _fallback_markdown(holding, warnings)
        return PostMortemDraft(
            holding_id=holding_id, markdown=md, used_llm=False, warnings=warnings
        )


__all__ = ["PostMortemDraft", "draft_post_mortem"]
