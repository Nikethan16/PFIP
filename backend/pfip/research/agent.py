"""Deep company-research agent (Phase 6).

Resolve a company NAME → ticker, gather everything PFIP already knows (the
``diligence`` aggregate: fundamentals / filings / news, plus price performance),
and synthesise a cited research DOSSIER with the LLM.

Design: **decision-support, not advice.** Every financial claim is grounded in
the gathered evidence or explicitly flagged as unverified. For names already in
the tracked universe the dossier is rich; for arbitrary names it resolves the
ticker, pulls any matching news, gives an honest business + bull/bear overview,
and nudges the user to add it to the watchlist for full tracking.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select

from pfip.core.logging import get_logger

log = get_logger("pfip.research.agent")

_RESOLVE_SYS = (
    "You map a company name to its stock ticker. Return STRICT JSON only: "
    '{"company": "...", "ticker": "...", "exchange": "NSE|BSE|NASDAQ|NYSE|other", '
    '"confident": true|false}. For Indian NSE listings give the BARE NSE symbol '
    "with no suffix (e.g. RELIANCE, WAAREEENER, TATAPOWER). If unsure, set ticker "
    "to null and confident=false. Output JSON only, no prose."
)

_DOSSIER_SYS = (
    "You are a sober equity-research analyst writing a DECISION-SUPPORT dossier "
    "(never a buy/sell recommendation). Ground every financial figure and recent "
    "event in the EVIDENCE provided. Where evidence is thin or missing, say so "
    "plainly — never fabricate financials, orders, or filings. If EVIDENCE has a "
    "'business_overview' (sourced company profile) use it for 'What they do'; "
    "otherwise you may use general knowledge there and should flag it as such. "
    "When 'fundamentals_are_live' is true the ratios are a fresh real-time pull "
    "(state the as-of is today). Output these markdown sections:\n"
    "**What they do** · **Financial health** · **Recent developments** · "
    "**Bull case** · **Bear case** · **Key risks** · **Market sentiment** · "
    "**What to verify yourself**\n"
    "Be concise and concrete. End with exactly: "
    "'Decision-support only — not investment advice; verify independently.'"
)


async def _resolve_ticker(query: str) -> dict[str, Any]:
    """LLM name→ticker resolution. Returns {company, ticker, exchange, confident}."""
    try:
        from pfip.agent.llm_client import ChatMessage, get_llm_client
        from pfip.agent.router import Sensitivity, TaskType

        raw = await get_llm_client().complete(
            [
                ChatMessage(role="system", content=_RESOLVE_SYS),
                ChatMessage(role="user", content=query.strip()),
            ],
            task=TaskType.QUICK_SUMMARY,
            sensitivity=Sensitivity.PUBLIC,
            max_tokens=120,
            temperature=0.0,
        )
        blob = raw[raw.find("{") : raw.rfind("}") + 1]
        d = json.loads(blob)
        return {
            "company": d.get("company") or query,
            "ticker": (d.get("ticker") or None),
            "exchange": d.get("exchange"),
            "confident": bool(d.get("confident")),
        }
    except Exception as e:  # noqa: BLE001
        log.warning(f"resolve_ticker failed: {type(e).__name__}: {e}")
        return {"company": query, "ticker": None, "exchange": None, "confident": False}


def _candidate_symbols(resolved: dict[str, Any], query: str) -> list[str]:
    """Symbol variants to try against our DB (NSE .NS / BSE .BO / bare)."""
    cands: list[str] = []
    tk = (resolved.get("ticker") or "").strip().upper()
    exch = (resolved.get("exchange") or "").upper()
    if tk:
        if "NSE" in exch:
            cands += [f"{tk}.NS", tk]
        elif "BSE" in exch:
            cands += [f"{tk}.BO", tk]
        else:
            cands += [tk, f"{tk}.NS"]
    q = query.strip().upper()
    if q and len(q) <= 12 and " " not in q:
        cands.append(q)
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def _price_performance(session: Any, symbol: str) -> dict[str, Any] | None:
    from pfip.models.ohlcv import OHLCVRow

    freshest = (
        select(OHLCVRow.source)
        .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
        .order_by(OHLCVRow.time.desc())
        .limit(1)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(OHLCVRow.time, OHLCVRow.close)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.timeframe == "1d",
                OHLCVRow.source == freshest,
            )
            .order_by(OHLCVRow.time.asc())
        )
    ).all()
    if len(rows) < 2:
        return None
    closes = [(t, float(c)) for t, c in rows]
    last_t, last = closes[-1]

    def _ret(days: int) -> float | None:
        cutoff = last_t - timedelta(days=days)
        prior = [c for t, c in closes if t <= cutoff]
        base = prior[-1] if prior else closes[0][1]
        return round((last - base) / base * 100, 1) if base else None

    return {
        "last_close": round(last, 2),
        "as_of": last_t.isoformat(),
        "ret_1m_pct": _ret(30),
        "ret_3m_pct": _ret(90),
        "ret_1y_pct": _ret(365),
        "bars": len(closes),
    }


async def _company_news(
    session: Any, symbols: list[str], query: str, limit: int = 10
) -> list[dict[str, Any]]:
    from pfip.models.news import NewsRow

    conds: list[Any] = [NewsRow.symbol.in_(symbols)] if symbols else []
    conds += [NewsRow.entity_tickers.contains([s]) for s in symbols]
    name = query.strip()
    if name:
        conds.append(NewsRow.title.ilike(f"%{name}%"))
    if not conds:
        return []
    rows = (
        (
            await session.execute(
                select(NewsRow).where(or_(*conds)).order_by(NewsRow.time.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "title": n.title,
            "url": n.url,
            "time": n.time.isoformat(),
            "sentiment": n.sentiment,
            "source": n.source,
        }
        for n in rows
    ]


async def build_research_dossier(session: Any, query: str) -> dict[str, Any]:
    """Resolve → gather → synthesise a cited research dossier for ``query``."""
    resolved = await _resolve_ticker(query)
    candidates = _candidate_symbols(resolved, query)

    # Diligence aggregate on the first candidate that has tracked data.
    from pfip.diligence.service import build_diligence

    diligence: dict[str, Any] = {}
    matched: str | None = None
    for sym in candidates or [query]:
        try:
            d = await build_diligence(session, sym)
        except Exception:  # noqa: BLE001
            d = {}
        if d.get("found"):
            diligence, matched = d, sym
            break
        if not diligence:
            diligence = d

    perf = await _price_performance(session, matched) if matched else None
    news = await _company_news(session, candidates or [query], query)

    is_tracked = bool(diligence.get("found"))
    fundamentals_section = diligence.get("fundamentals")
    live: dict[str, Any] = {}

    # Untracked (or tracked-but-no-fundamentals) → fetch fundamentals LIVE so the
    # first search returns real numbers instead of an "add to watchlist" stub.
    tracked_metrics = (fundamentals_section or {}).get("key_metrics") if is_tracked else None
    if not tracked_metrics:
        from pfip.research.fundamentals import fetch_live_fundamentals, fetch_live_performance

        live = await fetch_live_fundamentals(candidates or [query], resolved)
        if live.get("key_metrics"):
            fundamentals_section = {
                "as_of_date": None,
                "source": live.get("source"),
                "key_metrics": live["key_metrics"],
                "values": live["key_metrics"],
                "live": True,
            }
        # Live price performance only when the DB had none (untracked names).
        if perf is None:
            perf = await fetch_live_performance(candidates or [query])

    evidence = {
        "resolved": resolved,
        "matched_symbol": matched or live.get("matched_symbol"),
        "is_tracked": is_tracked,
        "business_overview": {
            k: live.get(k)
            for k in ("name", "description", "sector", "industry", "exchange", "currency")
            if live.get(k)
        }
        or None,
        "fundamentals": fundamentals_section,
        "fundamentals_are_live": bool(live.get("key_metrics")),
        "filings": (diligence.get("filings") or [])[:6],
        "diligence_summary": diligence.get("summary"),
        "price_performance": perf,
        "recent_news": [
            {"title": n["title"], "sentiment": n["sentiment"], "date": n["time"][:10]} for n in news
        ],
    }

    dossier_md = "Dossier synthesis unavailable."
    try:
        from pfip.agent.llm_client import ChatMessage, get_llm_client
        from pfip.agent.router import Sensitivity, TaskType

        dossier_md = await get_llm_client().complete(
            [
                ChatMessage(role="system", content=_DOSSIER_SYS),
                ChatMessage(
                    role="user",
                    content=(
                        f"Company queried: {query}\n\nEVIDENCE (JSON):\n"
                        f"{json.dumps(evidence, default=str)[:6000]}"
                    ),
                ),
            ],
            task=TaskType.CHAT_PUBLIC,
            sensitivity=Sensitivity.PUBLIC,
            max_tokens=900,
            temperature=0.3,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"dossier synth failed: {type(e).__name__}: {e}")
        dossier_md = f"Dossier synthesis unavailable ({type(e).__name__})."

    return {
        "query": query,
        "resolved": resolved,
        "matched_symbol": matched or live.get("matched_symbol"),
        "is_tracked": is_tracked,
        "performance": perf,
        "fundamentals": fundamentals_section,
        "fundamentals_are_live": bool(live.get("key_metrics")),
        "business_overview": (
            {
                k: live.get(k)
                for k in ("name", "sector", "industry", "exchange", "currency")
                if live.get(k)
            }
            or None
        ),
        "news": news,
        "dossier_markdown": dossier_md,
        # Still nudge to watchlist for ongoing tracking, even though the one-off
        # dossier is now rich (live fundamentals don't get stored / charted).
        "suggest_add_to_watchlist": (resolved.get("ticker") is not None and not is_tracked),
        "disclaimer": "Decision-support research only — not investment advice. Verify independently.",
    }
