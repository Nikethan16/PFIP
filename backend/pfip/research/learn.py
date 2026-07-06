"""Learn module (D9) — teach an asset from scratch.

Given a price series, find the *notable* moves (the biggest single-day swings)
so the API can attach a real news catalyst to each and explain what happened.
Move detection is pure and unit-tested; the catalyst attachment + LLM primer
live in the API layer. We only ever annotate a swing with a catalyst that
actually exists in the news store — no invented reasons.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class PricePoint(BaseModel):
    date: date
    close: float


class NotableMove(BaseModel):
    date: date
    close: float
    move_pct: float  # single-day % change into this date
    direction: str  # "up" | "down"


def detect_notable_moves(
    series: list[PricePoint],
    *,
    top_n: int = 6,
    min_abs_pct: float = 3.0,
) -> list[NotableMove]:
    """Return the largest single-day moves in the series (by |%|), date-ordered.

    A move is the close-to-close change into a day. Only moves of at least
    ``min_abs_pct`` qualify; the ``top_n`` biggest are returned, then sorted
    chronologically so the UI can lay them along the chart.
    """
    moves: list[NotableMove] = []
    for prev, cur in zip(series, series[1:]):
        if prev.close <= 0:
            continue
        pct = (cur.close - prev.close) / prev.close * 100.0
        if abs(pct) >= min_abs_pct:
            moves.append(
                NotableMove(
                    date=cur.date,
                    close=cur.close,
                    move_pct=round(pct, 2),
                    direction="up" if pct >= 0 else "down",
                )
            )
    moves.sort(key=lambda m: abs(m.move_pct), reverse=True)
    top = moves[:top_n]
    top.sort(key=lambda m: m.date)
    return top


# --- static educational content --------------------------------------------


class Strategy(BaseModel):
    name: str
    description: str
    when_it_helps: str


def default_strategies(is_crypto: bool) -> list[Strategy]:
    """General, educational strategy primers (not advice)."""
    common = [
        Strategy(
            name="Dollar-cost averaging (DCA)",
            description=(
                "Invest a fixed amount at regular intervals regardless of price, so "
                "you buy more when it's cheap and less when it's dear."
            ),
            when_it_helps="Smooths out entry timing in volatile or trending assets.",
        ),
        Strategy(
            name="Buy and hold",
            description=(
                "Take a position based on a long-term thesis and hold through "
                "short-term noise, rather than trading every swing."
            ),
            when_it_helps="When you believe in the asset's multi-year trajectory.",
        ),
        Strategy(
            name="Position sizing & risk limits",
            description=(
                "Decide up front how much of your portfolio a single asset may be, "
                "and what loss would invalidate your thesis."
            ),
            when_it_helps="Always — it caps how much any one call can hurt you.",
        ),
        Strategy(
            name="Rebalancing",
            description=(
                "Periodically trim winners and top up laggards back to your target "
                "weights, locking in gains and controlling concentration."
            ),
            when_it_helps="When a position grows to dominate the portfolio.",
        ),
    ]
    if is_crypto:
        common.append(
            Strategy(
                name="Volatility awareness",
                description=(
                    "Crypto can move 10%+ in a day and trades 24/7. Size positions "
                    "for that reality and avoid leverage you can't stomach."
                ),
                when_it_helps="For high-volatility, always-on assets like crypto.",
            )
        )
    return common


def fallback_primer(symbol: str, is_crypto: bool) -> str:
    """Deterministic primer when the LLM is offline."""
    kind = "cryptocurrency" if is_crypto else "security"
    return (
        f"### What is {symbol}?\n\n"
        f"{symbol} is a {kind}. This primer is generated offline, so it is generic — "
        "connect the language model for a tailored explanation.\n\n"
        "**How to read the chart:** the line is the closing price over time. The "
        "marked points are the biggest single-day moves in the window; each is "
        "matched to a news item from that period where one exists, so you can see "
        "*why* it moved rather than just *that* it moved.\n\n"
        "_Educational only — not investment advice._"
    )


def is_crypto_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith("-USD") or s.endswith("USDT") or s in {"BTC", "ETH"}
