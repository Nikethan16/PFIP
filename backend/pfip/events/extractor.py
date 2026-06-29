"""Deterministic catalyst extraction over the (entity-linked) news table.

Reliability-first: this is **rule-based**, not an LLM-JSON parser — it never
costs tokens, never hallucinates, and degrades to "0 events" rather than wrong
events. It scans recent news, classifies each headline into a typed event kind
by keyword patterns, links it to the ticker(s) the entity-linker already tagged,
scores materiality, and upserts idempotently by ``dedup_key``.

LLM enrichment (richer summaries) is a future enhancement layered on top; the
detection itself stays deterministic.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pfip.core.logging import get_logger
from pfip.models.event import EventRow

log = get_logger("pfip.events.extractor")

# (kind, compiled pattern, base materiality). Order = priority; first match wins.
_PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("m_and_a", re.compile(r"\b(acqui\w+|merger|takeover|buyout|to buy|stake in)\b", re.I), 0.85),
    (
        "contract_win",
        re.compile(
            r"\b(wins?|won|bags?|secures?|awarded|order win|tender|new order|deal worth)\b", re.I
        ),
        0.75,
    ),
    (
        "regulatory",
        re.compile(
            r"\b(sebi|\bsec\b|probe|investigat\w+|fine|penalt\w+|ban|sanction|approval|lawsuit)\b",
            re.I,
        ),
        0.7,
    ),
    (
        "upgrade",
        re.compile(
            r"\b(upgrade[sd]?|raises? (target|rating|to buy)|outperform|overweight|price target hike)\b",
            re.I,
        ),
        0.55,
    ),
    (
        "downgrade",
        re.compile(
            r"\b(downgrade[sd]?|cuts? (target|rating)|underperform|underweight|sell rating)\b", re.I
        ),
        0.6,
    ),
    (
        "earnings_surprise",
        re.compile(
            r"\b(beats?|missed?|tops? estimates|q[1-4] (results|profit|earnings)|net profit (jumps|rises|falls)|revenue (rises|falls))\b",
            re.I,
        ),
        0.6,
    ),
    ("buyback", re.compile(r"\b(buyback|repurchase|to buy back shares)\b", re.I), 0.5),
    (
        "guidance",
        re.compile(
            r"\b(guidance|raises outlook|cuts outlook|forecast|warns?|profit warning)\b", re.I
        ),
        0.55,
    ),
    (
        "management",
        re.compile(
            r"\b(ceo|cfo|managing director|resign\w*|steps down|appoint\w*|new chief)\b", re.I
        ),
        0.45,
    ),
]


def classify_headline(text_in: str) -> tuple[str, float] | None:
    """Return (kind, base_materiality) for a headline, or None if no catalyst."""
    for kind, pat, base in _PATTERNS:
        if pat.search(text_in):
            return kind, base
    return None


def _dedup_key(ticker: str, kind: str, title: str) -> str:
    raw = f"{ticker.upper()}|{kind}|{title.strip().lower()[:80]}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()  # noqa: S324 — non-crypto id


async def extract_events(session, *, days: int = 7, limit: int = 1500) -> dict[str, Any]:
    """Scan recent entity-linked news → typed events; idempotent upsert.

    Returns ``{"scanned": n, "events": m}``. Never raises on a single bad row.
    """
    since = datetime.now(tz=UTC) - timedelta(days=days)
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT title, summary, url, time, symbol, entity_tickers
                    FROM news
                    WHERE time >= :since
                      AND (entity_tickers IS NOT NULL AND entity_tickers <> '[]'::jsonb)
                    ORDER BY time DESC
                    LIMIT :lim
                    """
                ),
                {"since": since, "lim": limit},
            )
        ).all()
    except Exception as e:  # noqa: BLE001
        log.warning(f"extract_events: news scan failed: {type(e).__name__}: {e}")
        return {"scanned": 0, "events": 0}

    inserted = 0
    for title, summary, url, ts, symbol, tickers in rows:
        hay = " ".join(x for x in (title, summary) if x) or ""
        hit = classify_headline(hay)
        if not hit:
            continue
        kind, base = hit
        # Tickers this story is linked to (JSONB list) + any scalar symbol.
        linked = list(tickers or [])
        if symbol and symbol not in linked:
            linked.append(symbol)
        for tk in linked:
            if not tk:
                continue
            key = _dedup_key(str(tk), kind, title or "")
            stmt = (
                pg_insert(EventRow)
                .values(
                    ticker=str(tk),
                    kind=kind,
                    materiality=base,
                    title=(title or "")[:500],
                    summary=(summary or None),
                    source_url=url,
                    occurred_at=ts,
                    dedup_key=key,
                )
                .on_conflict_do_nothing(index_elements=["dedup_key"])
            )
            try:
                res = await session.execute(stmt)
                inserted += res.rowcount or 0
            except Exception as e:  # noqa: BLE001 — one row can't abort the batch
                log.debug(f"event upsert failed for {tk}/{kind}: {type(e).__name__}")
    await session.commit()
    log.info(f"extract_events: scanned={len(rows)} new_events={inserted}")
    return {"scanned": len(rows), "events": inserted}


async def recent_events(session, *, ticker: str | None = None, days: int = 30, limit: int = 100):
    """Read recent events (optionally for one ticker), newest first."""
    since = datetime.now(tz=UTC) - timedelta(days=days)
    stmt = select(EventRow).where(EventRow.occurred_at >= since)
    if ticker:
        stmt = stmt.where(EventRow.ticker == ticker)
    stmt = stmt.order_by(EventRow.occurred_at.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()
