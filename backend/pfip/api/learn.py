"""Learn module API (D9) — teach an asset from scratch.

``GET /learn/{symbol}`` returns a price series for a chart, the biggest single-
day moves each matched to a *real* news catalyst where one exists, a beginner
primer (LLM, grounded, with a deterministic fallback), and general educational
strategies. Explicitly educational — no buy/sell affordances, no predictions,
and swings are only annotated with catalysts that actually exist in the news
store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import or_, select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.news import NewsRow
from pfip.models.ohlcv import OHLCVRow
from pfip.research.learn import (
    PricePoint,
    Strategy,
    default_strategies,
    detect_notable_moves,
    fallback_primer,
    is_crypto_symbol,
)

router = APIRouter(prefix="/learn", tags=["learn"])


class Catalyst(BaseModel):
    title: str
    url: Optional[str] = None
    at: datetime


class MoveWithCatalyst(BaseModel):
    date: str
    close: float
    move_pct: float
    direction: str
    catalyst: Optional[Catalyst] = None
    explanation: str


class LearnResponse(BaseModel):
    symbol: str
    is_crypto: bool
    series: list[PricePoint]
    notable_moves: list[MoveWithCatalyst]
    primer_markdown: str
    strategies: list[Strategy]
    used_llm: bool
    disclaimer: str = (
        "Educational walkthrough built from stored prices and news — swings are "
        "annotated only where a real catalyst exists. Not investment advice, and "
        "past moves don't predict future ones."
    )


@router.get("/{symbol}", response_model=LearnResponse)
async def learn(symbol: str, db: DbSession, _user: CurrentUser, days: int = 180) -> LearnResponse:
    symbol = symbol.strip()
    is_crypto = is_crypto_symbol(symbol)
    series = await _price_series(db, symbol, days)
    moves = detect_notable_moves(series)
    news = await _news_window(db, symbol, days)
    moves_with_catalysts = [_attach_catalyst(m, news, symbol) for m in moves]

    primer, used_llm = await _primer(symbol, is_crypto, moves_with_catalysts)

    return LearnResponse(
        symbol=symbol,
        is_crypto=is_crypto,
        series=series,
        notable_moves=moves_with_catalysts,
        primer_markdown=primer,
        strategies=default_strategies(is_crypto),
        used_llm=used_llm,
    )


async def _price_series(db: DbSession, symbol: str, days: int) -> list[PricePoint]:
    try:
        freshest = (
            select(OHLCVRow.source)
            .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
            .order_by(OHLCVRow.time.desc())
            .limit(1)
            .scalar_subquery()
        )
        since = datetime.now(tz=UTC) - timedelta(days=days)
        rows = (
            await db.execute(
                select(OHLCVRow.time, OHLCVRow.close)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.timeframe == "1d",
                    OHLCVRow.source == freshest,
                    OHLCVRow.time >= since,
                )
                .order_by(OHLCVRow.time.asc())
            )
        ).all()
    except Exception:  # noqa: BLE001
        return []
    return [PricePoint(date=t.date(), close=float(c)) for t, c in rows if c is not None]


async def _news_window(db: DbSession, symbol: str, days: int) -> list[NewsRow]:
    try:
        since = datetime.now(tz=UTC) - timedelta(days=days)
        rows = (
            (
                await db.execute(
                    select(NewsRow)
                    .where(
                        or_(
                            NewsRow.symbol == symbol,
                            NewsRow.entity_tickers.contains([symbol]),
                        ),
                        NewsRow.time >= since,
                    )
                    .order_by(NewsRow.time.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
    except Exception:  # noqa: BLE001
        return []


def _attach_catalyst(move, news: list[NewsRow], symbol: str) -> MoveWithCatalyst:
    """Match the closest news item within ±3 days of the move."""
    best: Optional[NewsRow] = None
    best_delta = timedelta(days=4)
    for n in news:
        delta = abs(n.time.date() - move.date)
        if isinstance(delta, timedelta) and delta <= timedelta(days=3) and delta < best_delta:
            best = n
            best_delta = delta
    if best is not None:
        return MoveWithCatalyst(
            date=move.date.isoformat(),
            close=move.close,
            move_pct=move.move_pct,
            direction=move.direction,
            catalyst=Catalyst(title=best.title, url=best.url, at=best.time),
            explanation=(
                f"{symbol} {'rose' if move.direction == 'up' else 'fell'} "
                f"{abs(move.move_pct):.1f}% around {move.date.isoformat()}. "
                f"Nearby headline: “{best.title}”."
            ),
        )
    return MoveWithCatalyst(
        date=move.date.isoformat(),
        close=move.close,
        move_pct=move.move_pct,
        direction=move.direction,
        catalyst=None,
        explanation=(
            f"{symbol} {'rose' if move.direction == 'up' else 'fell'} "
            f"{abs(move.move_pct):.1f}% around {move.date.isoformat()}. "
            "No clear catalyst in the available news."
        ),
    )


_SYSTEM = (
    "You teach a beginner about a financial asset. Given the symbol and a list of "
    "its biggest recent price moves (each possibly with a real news headline), "
    "write a short primer: (1) what the asset is and how it works, (2) how to read "
    "the marked moves on the chart. Cite ONLY the headlines provided — never invent "
    "news or figures. Do not predict prices. Do not give buy/sell advice. Plain, "
    "encouraging, 3-5 short paragraphs."
)


async def _primer(symbol: str, is_crypto: bool, moves: list[MoveWithCatalyst]) -> tuple[str, bool]:
    facts = [f"Symbol: {symbol} ({'crypto' if is_crypto else 'equity/other'})"]
    for m in moves:
        line = f"- {m.date}: {m.move_pct:+.1f}%"
        if m.catalyst:
            line += f" — headline: “{m.catalyst.title}”"
        facts.append(line)
    prompt = "Teach me about this asset.\n\n" + "\n".join(facts)

    from pfip.agent.llm_client import LLMUnavailable, get_llm_router

    try:
        router_ = get_llm_router()
        text = (await router_.generate(prompt, system=_SYSTEM) or "").strip()
        if text:
            return text, True
    except LLMUnavailable:
        pass
    except Exception:  # noqa: BLE001
        pass
    return fallback_primer(symbol, is_crypto), False
