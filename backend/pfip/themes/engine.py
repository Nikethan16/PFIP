"""Theme → beneficiary scoring over the entity-linked news (Phase 4).

Deterministic + evidence-first: a tracked company "benefits" from a theme to the
extent its recently-linked news matches the theme's keywords. The score is a
recency-weighted count of matching stories; the EVIDENCE is the actual headlines
(with links) — so every ranking is auditable and nothing is invented.

Honest scope: the beneficiary universe is the **watchlist** (the symbols PFIP
actually tracks + prices). A broader market-wide discovery universe is future
work (needs a companies→sector reference dataset). This surfaces "which of the
things I track have exposure to theme X", which is the practical first cut.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from pfip.core.logging import get_logger
from pfip.themes.catalogue import THEMES

log = get_logger("pfip.themes.engine")


async def score_theme(
    session, slug: str, *, days: int = 90, top: int = 15, evidence_per: int = 4
) -> dict[str, Any] | None:
    """Rank watchlist tickers by news exposure to ``slug``, with evidence.

    Returns ``None`` for an unknown theme. Never raises on data issues.
    """
    theme = THEMES.get(slug)
    if not theme:
        return None
    kws = [k.lower() for k in theme["keywords"]]
    since = datetime.now(tz=UTC) - timedelta(days=days)
    now = datetime.now(tz=UTC)

    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT title, summary, url, time, entity_tickers
                    FROM news
                    WHERE time >= :since
                      AND (entity_tickers IS NOT NULL AND entity_tickers <> '[]'::jsonb)
                    ORDER BY time DESC
                    LIMIT 4000
                    """
                ),
                {"since": since},
            )
        ).all()
    except Exception as e:  # noqa: BLE001
        log.warning(f"score_theme: news scan failed: {type(e).__name__}: {e}")
        rows = []

    by_ticker: dict[str, dict[str, Any]] = {}
    matched_stories = 0
    for title, summary, url, ts, tickers in rows:
        hay = f"{title or ''} {summary or ''}".lower()
        if not any(k in hay for k in kws):
            continue
        matched_stories += 1
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0) if ts else days
        recency = max(0.1, 1.0 - age_days / days)
        for tk in tickers or []:
            if not tk:
                continue
            d = by_ticker.setdefault(tk, {"ticker": tk, "score": 0.0, "n": 0, "evidence": []})
            d["score"] += recency
            d["n"] += 1
            if len(d["evidence"]) < evidence_per:
                d["evidence"].append(
                    {
                        "title": title,
                        "url": url,
                        "published_at": ts.isoformat() if ts else None,
                    }
                )

    ranked = sorted(by_ticker.values(), key=lambda d: d["score"], reverse=True)[:top]
    for d in ranked:
        d["score"] = round(d["score"], 3)

    return {
        "slug": slug,
        "label": theme["label"],
        "window_days": days,
        "matched_stories": matched_stories,
        "beneficiaries": ranked,
        "universe": "watchlist",
        "disclaimer": (
            "Research aid only — ranks tracked companies by recent NEWS EXPOSURE to "
            "the theme, not by fundamentals or expected return. Not investment advice."
        ),
    }
