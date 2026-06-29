"""Assets & market-data routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import OHLCV, NewsItem
from pfip.models.features import FeatureRow
from pfip.models.news import NewsRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.regime import RegimeRow
from pfip.models.watchlist import WatchlistRow

router = APIRouter(prefix="/assets", tags=["assets"])


def _rank(symbol: str, needle: str) -> int:
    """Lower is better: exact (0) < prefix (1) < substring (2)."""
    s = symbol.upper()
    n = needle.upper()
    if s == n:
        return 0
    if s.startswith(n):
        return 1
    return 2


@router.get("/search")
async def search_assets(
    db: DbSession,
    _user: CurrentUser,
    q: str = Query(..., min_length=1, description="Case-insensitive ticker/symbol fragment."),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Search known tickers by symbol fragment.

    Looks across the watchlist (curated symbol+market pairs) and any symbol that
    already has OHLCV history, so the user can find anything the platform can
    actually price. Case-insensitive substring match, ranked so exact and prefix
    matches surface first. Watchlist hits are flagged ``"source": "watchlist"``;
    price-only hits ``"source": "ohlcv"``. Returns
    ``{"query": q, "results": [{symbol, market, source}]}``.

    Defined before the ``/{symbol:path}`` routes so ``GET /assets/search`` is
    never swallowed by the symbol matcher.
    """
    needle = q.strip()
    if not needle:
        return {"query": q, "results": []}
    pattern = f"%{needle}%"

    # Watchlist is authoritative for the (symbol, market) pair and the user's
    # curated names, so it wins on dedupe.
    wl_rows = (
        await db.execute(
            select(WatchlistRow.symbol, WatchlistRow.market)
            .where(WatchlistRow.symbol.ilike(pattern))
            .order_by(WatchlistRow.symbol)
            .limit(limit * 4)
        )
    ).all()
    # Symbols we already have priced — distinct (symbol, market) pairs.
    ohlcv_rows = (
        await db.execute(
            select(OHLCVRow.symbol, OHLCVRow.market)
            .where(OHLCVRow.symbol.ilike(pattern))
            .distinct()
            .limit(limit * 4)
        )
    ).all()

    # Dedupe by symbol, watchlist first.
    by_symbol: dict[str, dict] = {}
    for r in wl_rows:
        by_symbol.setdefault(
            r.symbol, {"symbol": r.symbol, "market": r.market, "source": "watchlist"}
        )
    for r in ohlcv_rows:
        by_symbol.setdefault(r.symbol, {"symbol": r.symbol, "market": r.market, "source": "ohlcv"})

    results = sorted(
        by_symbol.values(),
        key=lambda d: (_rank(d["symbol"], needle), d["symbol"].upper()),
    )[:limit]
    return {"query": needle, "results": results}


# Canonical typed feature columns (mirrors FeatureRow); extras live in JSONB.
_FEATURE_COLS: tuple[str, ...] = (
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "return_7d",
    "volatility_30d",
)


@router.get("/{symbol:path}/candles", response_model=list[OHLCV])
async def get_candles(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    timeframe: str = Query("1d"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
) -> list[OHLCV]:
    """Return OHLCV rows for ``symbol`` in ``timeframe``. Empty list if none.

    Bounded to the most recent ``limit`` rows (default 1000, max 5000) so the
    endpoint can never stream an entire multi-year history in one response.
    """
    # A symbol can have rows from several sources (e.g. tiingo + the yfinance
    # fallback). Pin to the source with the FRESHEST bar so (a) the chart never
    # shows duplicate timestamps and (b) a fresh fallback wins over a stale
    # primary instead of the other way round.
    freshest_source = (
        select(OHLCVRow.source)
        .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == timeframe)
        .order_by(OHLCVRow.time.desc())
        .limit(1)
        .scalar_subquery()
    )
    stmt = select(OHLCVRow).where(
        OHLCVRow.symbol == symbol,
        OHLCVRow.timeframe == timeframe,
        OHLCVRow.source == freshest_source,
    )
    if since is not None:
        stmt = stmt.where(OHLCVRow.time >= since)
    if until is not None:
        stmt = stmt.where(OHLCVRow.time <= until)
    # Take the most recent ``limit`` rows, then return them in ascending order.
    stmt = stmt.order_by(OHLCVRow.time.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()
    return [OHLCV.model_validate(row) for row in rows]


@router.get("/{symbol:path}/features")
async def get_features(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    as_of: datetime | None = Query(None),
    timeframe: str = Query("1d"),
) -> dict:
    """Return the latest feature row for ``symbol``.

    Returns the canonical 5+ typed features, the ``extras`` JSONB blob and the
    ``as_of`` time of the bar. If ``as_of`` is given we take the most-recent row
    at or before that instant. When no feature row exists we return a
    well-formed payload with null features rather than 501 (the Prefect compute
    flow may simply not have run for this symbol yet).
    """
    stmt = select(FeatureRow).where(FeatureRow.symbol == symbol, FeatureRow.timeframe == timeframe)
    if as_of is not None:
        stmt = stmt.where(FeatureRow.time <= as_of)
    stmt = stmt.order_by(FeatureRow.time.desc()).limit(1)
    row = (await db.execute(stmt)).scalars().first()

    if row is None:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "as_of": None,
            "source": None,
            "features": {col: None for col in _FEATURE_COLS},
            "extras": {},
        }

    return {
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "as_of": row.time.isoformat(),
        "source": row.source,
        "features": {col: getattr(row, col) for col in _FEATURE_COLS},
        "extras": row.extras or {},
    }


@router.get("/{symbol:path}/news", response_model=list[NewsItem])
async def get_news(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    since: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[NewsItem]:
    """Return recent news items for ``symbol``, newest first.

    Bounded to the most recent ``limit`` rows (default 50, max 200). Empty list
    if there's no news for the symbol.
    """
    # Match the scalar ``symbol`` OR membership in the ``entity_tickers`` JSONB
    # array (the entity-linker tags multi-symbol stories there, so filtering on
    # the mostly-NULL scalar alone silently returned nothing).
    stmt = select(NewsRow).where(
        or_(NewsRow.symbol == symbol, NewsRow.entity_tickers.contains([symbol]))
    )
    if since is not None:
        stmt = stmt.where(NewsRow.time >= since)
    stmt = stmt.order_by(NewsRow.time.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [NewsItem.model_validate(row) for row in rows]


@router.get("/{symbol:path}/regime")
async def get_regime(symbol: str, db: DbSession, _user: CurrentUser) -> dict:
    """Return the latest regime label + confidence for ``symbol``.

    Returns a well-formed ``{regime: "unknown", confidence: 0.0}`` payload when
    the classifier hasn't labelled this symbol yet (rather than 501/404), so the
    UI can render a neutral state.
    """
    stmt = (
        select(RegimeRow)
        .where(RegimeRow.symbol == symbol)
        .order_by(RegimeRow.since.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()

    if row is None:
        return {
            "symbol": symbol,
            "regime": "unknown",
            "since": None,
            "confidence": 0.0,
        }

    return {
        "symbol": row.symbol,
        "regime": row.regime,
        "since": row.since.isoformat(),
        "confidence": row.confidence,
    }


# ---------------------------------------------------------------------------
# Narrative "why" engine (Phase 2) — explain a move from ingested news + KB
# ---------------------------------------------------------------------------

_EXPLAIN_SYS = (
    "You are a sober financial analyst. Explain the LIKELY drivers of the given "
    "price move using ONLY the provided news headlines and context. Cite each "
    "claim inline like [1], [2] referring to the numbered sources. Be concise "
    "(2-4 sentences). If the provided evidence does not plausibly explain the "
    "move, reply EXACTLY: 'No clear catalyst in the available data.' Do NOT "
    "speculate, invent causes, or use outside knowledge. Advisory only, not advice."
)


async def _explain_cache(key: str, value: dict | None = None):
    """Tiny best-effort Redis cache (get if value is None, else set 6h)."""
    from pfip.core.config import get_settings

    url = getattr(get_settings(), "redis_url", None)
    if not url:
        return None
    try:
        from redis.asyncio import Redis

        r = Redis.from_url(url, decode_responses=True)
        if value is None:
            raw = await r.get(key)
            await r.aclose()
            return json.loads(raw) if raw else None
        await r.set(key, json.dumps(value), ex=6 * 3600)
        await r.aclose()
    except Exception:  # noqa: BLE001 — cache is optional
        return None
    return None


@router.get("/{symbol:path}/explain")
async def explain_move(
    symbol: str,
    db: DbSession,
    _user: CurrentUser,
    window_days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    """Explain *why* ``symbol`` moved over the trailing window, grounded in the
    news PFIP ingested (+ KB), with numbered citations. Abstains ("No clear
    catalyst…") when the evidence is thin — it never invents a cause.

    Cached per (symbol, day, window) for 6h to bound LLM cost.
    """
    cache_key = f"explain:{symbol}:{datetime.now(tz=UTC).date()}:{window_days}"
    cached = await _explain_cache(cache_key)
    if cached:
        cached["cached"] = True
        return cached

    # 1) Price move over the window (freshest source per symbol).
    freshest = (
        select(OHLCVRow.source)
        .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
        .order_by(OHLCVRow.time.desc())
        .limit(1)
        .scalar_subquery()
    )
    since = datetime.now(tz=UTC) - timedelta(days=window_days)
    closes = (
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
    move_pct: float | None = None
    last_close: float | None = None
    if len(closes) >= 2:
        first_c, last_c = float(closes[0][1]), float(closes[-1][1])
        last_close = last_c
        if first_c > 0:
            move_pct = round((last_c - first_c) / first_c * 100.0, 2)

    # 2) News linked to the symbol in the window (scalar or entity_tickers).
    news_rows = (
        (
            await db.execute(
                select(NewsRow)
                .where(
                    or_(NewsRow.symbol == symbol, NewsRow.entity_tickers.contains([symbol])),
                    NewsRow.time >= since,
                )
                .order_by(NewsRow.time.desc())
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    sources = [
        {"n": i + 1, "title": n.title, "url": n.url, "published_at": n.time.isoformat()}
        for i, n in enumerate(news_rows)
    ]

    # 3) Latest regime (context only).
    regime_row = (
        (
            await db.execute(
                select(RegimeRow)
                .where(RegimeRow.symbol == symbol)
                .order_by(RegimeRow.since.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    regime = regime_row.regime if regime_row else "unknown"

    # 4) Guardrail: with no news evidence, abstain rather than hallucinate.
    if not sources:
        out = {
            "symbol": symbol,
            "window_days": window_days,
            "move_pct": move_pct,
            "last_close": last_close,
            "regime": regime,
            "explanation": "No clear catalyst in the available data.",
            "sources": [],
            "used_llm": False,
            "cached": False,
        }
        await _explain_cache(cache_key, out)
        return out

    # 5) Best-effort KB context (degrades to none if Qdrant is down).
    kb_block = ""
    try:
        from pfip.kb.search import format_citations, search as kb_search

        hits = await kb_search(f"drivers of {symbol} price move", k=3)
        if hits:
            kb_block = "\n\nReference context:\n" + format_citations(hits)
    except Exception:  # noqa: BLE001
        kb_block = ""

    # 6) Synthesize with cite-or-abstain.
    news_block = "\n".join(f"[{s['n']}] {s['title']} ({s['published_at'][:10]})" for s in sources)
    move_desc = (
        f"{symbol} moved {move_pct:+.2f}% over the last {window_days} days"
        if move_pct is not None
        else f"{symbol} over the last {window_days} days"
    )
    user_msg = (
        f"{move_desc}. Current regime: {regime}.\n\nNews headlines:\n{news_block}{kb_block}\n\n"
        "Explain the likely drivers using only the above, with [n] citations."
    )

    explanation = "No clear catalyst in the available data."
    used_llm = False
    try:
        from pfip.agent.llm_client import ChatMessage, get_llm_client
        from pfip.agent.router import Sensitivity, TaskType

        explanation = await get_llm_client().complete(
            [
                ChatMessage(role="system", content=_EXPLAIN_SYS),
                ChatMessage(role="user", content=user_msg),
            ],
            task=TaskType.QUICK_SUMMARY,
            sensitivity=Sensitivity.PUBLIC,
            max_tokens=400,
            temperature=0.2,
        )
        used_llm = True
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        explanation = f"Explanation unavailable (LLM error: {type(exc).__name__})."

    out = {
        "symbol": symbol,
        "window_days": window_days,
        "move_pct": move_pct,
        "last_close": last_close,
        "regime": regime,
        "explanation": explanation,
        "sources": sources,
        "used_llm": used_llm,
        "cached": False,
    }
    if used_llm:
        await _explain_cache(cache_key, out)
    return out
