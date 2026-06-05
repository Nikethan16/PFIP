"""Attach news to signals: top-K supporting + top-K opposing.

Each signal has a ``direction`` (BUY / SELL / HOLD). News rows have an
optional ``sentiment`` (-1.0 .. +1.0) and an ``entity_tickers`` list.
For a given signal we want:

- The top-5 *supporting* news in the last 48h: same-direction sentiment
  for the signal's symbol, ranked by impact score.
- The top-3 *opposing* news: opposite-direction sentiment, same ranking.

This is the "counter-argument extraction per signal" feature in plan §4.
Used by the dashboard signals card + the agent's reasoning prompts.

The module is database-aware (joins news to watchlist via
``entity_tickers``) but pure-Python computation at the ranking step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(slots=True)
class NewsForSignal:
    """One news item attached to a signal."""

    title: str
    url: str | None
    published_at: datetime
    sentiment: float  # -1..+1
    impact: int  # 0..100
    source: str | None = None


@dataclass(slots=True)
class SignalNewsAttachment:
    """The supporting/opposing news lists for one signal."""

    symbol: str
    direction: str
    supporting: list[NewsForSignal] = field(default_factory=list)
    opposing: list[NewsForSignal] = field(default_factory=list)


def _is_supporting(direction: str, sentiment: float) -> bool:
    """A news item supports a BUY when sentiment is positive; supports SELL when negative."""
    d = direction.upper()
    if d == "BUY":
        return sentiment > 0
    if d == "SELL":
        return sentiment < 0
    # HOLD: nothing 'supports' a HOLD per se; we treat neutral (|s| <= 0.2) as supporting.
    return abs(sentiment) <= 0.2


def _rank_key(item: NewsForSignal) -> tuple[int, float, datetime]:
    """Higher impact first, then higher absolute sentiment, then newer."""
    return (item.impact, abs(item.sentiment), item.published_at)


def select_news_for_signal(
    items: list[NewsForSignal],
    *,
    direction: str,
    top_support: int = 5,
    top_oppose: int = 3,
) -> tuple[list[NewsForSignal], list[NewsForSignal]]:
    """Pure ranker — no I/O. Used by the DB-backed wrapper and by tests.

    Returns ``(supporting, opposing)`` lists, each sorted by the rank key
    desc and trimmed to the requested top-K.
    """
    supporting = [n for n in items if _is_supporting(direction, n.sentiment)]
    opposing = [n for n in items if not _is_supporting(direction, n.sentiment)]
    supporting.sort(key=_rank_key, reverse=True)
    opposing.sort(key=_rank_key, reverse=True)
    return supporting[:top_support], opposing[:top_oppose]


async def attach_news_to_signal(
    session: Any,
    *,
    symbol: str,
    direction: str,
    lookback_hours: int = 48,
    top_support: int = 5,
    top_oppose: int = 3,
) -> SignalNewsAttachment:
    """DB-backed: pull recent news for `symbol` and run the ranker."""
    try:
        from sqlalchemy import desc, select

        from pfip.models.news import NewsRow
    except Exception:  # pragma: no cover
        return SignalNewsAttachment(symbol=symbol, direction=direction)

    since = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    rows = (
        (
            await session.execute(
                select(NewsRow)
                .where(NewsRow.time >= since)
                .order_by(desc(NewsRow.time))
                .limit(200)
            )
        )
        .scalars()
        .all()
    )

    items: list[NewsForSignal] = []
    for r in rows:
        ent = getattr(r, "entity_tickers", None) or []
        if symbol not in ent:
            continue
        items.append(
            NewsForSignal(
                title=r.title or "",
                url=getattr(r, "url", None),
                published_at=r.time,
                sentiment=float(getattr(r, "sentiment_score", 0.0) or 0.0),
                impact=int(getattr(r, "impact_score", 0) or 0),
                source=getattr(r, "source", None),
            )
        )

    supporting, opposing = select_news_for_signal(
        items,
        direction=direction,
        top_support=top_support,
        top_oppose=top_oppose,
    )
    return SignalNewsAttachment(
        symbol=symbol,
        direction=direction,
        supporting=supporting,
        opposing=opposing,
    )


__all__ = [
    "NewsForSignal",
    "SignalNewsAttachment",
    "attach_news_to_signal",
    "select_news_for_signal",
]
