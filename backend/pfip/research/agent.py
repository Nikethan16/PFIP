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
    "(never a buy/sell recommendation).\n\n"
    "GROUNDING RULES (non-negotiable):\n"
    "- Ground every financial figure and event in the EVIDENCE JSON. Never "
    "fabricate financials, orders, filings, or price levels.\n"
    "- Quote each metric with its UNIT and scale exactly as given: ratios like "
    "P/E as '22.7x'; percentages (ROCE, ROE, margins, growth, dividend yield) "
    "as e.g. '38.8%'; market cap and prices in their stated currency (₹ for "
    "INR, $ for USD) with thousands separators. Do NOT invent a currency.\n"
    "- When 'fundamentals_are_live' is true, say the ratios are a live pull as "
    "of today; otherwise cite the fundamentals 'as_of_date' if present.\n"
    "- If a section has no supporting evidence, write one honest line saying so "
    "(e.g. 'No recent filings in the evidence set') — do NOT pad with generic "
    "advice like 'analyse the annual report' or 'revenue growth is important'.\n"
    "- For 'What they do': use EVIDENCE 'business_overview' if present; else you "
    "may use general knowledge but must prefix it with 'From general knowledge "
    "(unverified):'.\n\n"
    "OUTPUT — these markdown sections, in order, each 1-4 tight sentences or "
    "bullets:\n"
    "**What they do** · **Financial health** (lead with the actual ratios) · "
    "**Recent developments** · **Bull case** · **Bear case** · **Key risks** · "
    "**Market sentiment** · **What to verify yourself**\n\n"
    "Concrete over verbose. No hedging filler. End with exactly: "
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
        # LLMs frequently emit the STRING "null" for an unknown ticker, which
        # is truthy — normalise it (and "none"/"n/a") to a real None so
        # downstream "did we resolve?" checks don't treat failure as success.
        ticker_raw = d.get("ticker")
        ticker = str(ticker_raw).strip() if ticker_raw is not None else ""
        if ticker.lower() in ("", "null", "none", "n/a"):
            ticker = None  # type: ignore[assignment]
        return {
            "company": d.get("company") or query,
            "ticker": ticker,
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
    is_india = any((s or "").upper().endswith((".NS", ".BO")) for s in (candidates or [])) or (
        (resolved.get("exchange") or "").upper() in ("NSE", "BSE")
    )
    fundamentals_section = diligence.get("fundamentals")
    live: dict[str, Any] = {}

    # Untracked (or tracked-but-no-fundamentals) → fetch fundamentals LIVE so the
    # first search returns real numbers instead of an "add to watchlist" stub.
    tracked_metrics = (fundamentals_section or {}).get("key_metrics") if is_tracked else None
    if not tracked_metrics:
        from pfip.research.fundamentals import (
            fetch_live_fundamentals,
            fetch_live_performance,
            persist_live_fundamentals,
        )

        live = await fetch_live_fundamentals(candidates or [query], resolved)
        if live.get("key_metrics"):
            fundamentals_section = {
                "as_of_date": None,
                "source": live.get("source"),
                "key_metrics": live["key_metrics"],
                "values": live["key_metrics"],
                "live": True,
            }
            # Persist so repeat searches accumulate a light fundamentals history.
            await persist_live_fundamentals(session, live)
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

    # Rich fundamentals: multi-year statements (US via AV, on-demand) + a peer
    # comparison over whatever metrics we have stored. Both best-effort.
    statements: dict[str, Any] = {}
    if not is_india and matched:
        try:
            from pfip.research.statements import fetch_us_statements

            statements = await fetch_us_statements(matched)
        except Exception as e:  # noqa: BLE001
            log.warning(f"statements fetch failed: {type(e).__name__}: {e}")

    peers_block: dict[str, Any] = {}
    try:
        from pfip.diligence.peers import compare, ensure_peer_metrics, peers_for

        target_sym = matched or (candidates[0] if candidates else query)
        peer_syms = peers_for(target_sym)
        if peer_syms:
            metrics_by = await ensure_peer_metrics(session, [target_sym, *peer_syms])
            # Seed the target's own metrics from the fundamentals we just built.
            tgt_metrics = (fundamentals_section or {}).get("key_metrics") or {}
            if tgt_metrics:
                metrics_by.setdefault(target_sym, {}).update(
                    {k: float(v) for k, v in tgt_metrics.items() if isinstance(v, (int, float))}
                )
            if len(metrics_by) >= 2:
                peers_block = compare(target_sym, metrics_by)
    except Exception as e:  # noqa: BLE001
        log.warning(f"peer comparison failed: {type(e).__name__}: {e}")

    # Feed the multi-year trend + peer standing into the LLM evidence so the
    # dossier can reason about trajectory and relative valuation, not just a
    # point-in-time snapshot.
    if statements.get("trend"):
        evidence["statements_trend"] = statements["trend"]
    if peers_block.get("fields"):
        evidence["peer_comparison"] = {
            f: {
                "target": d["target"],
                "peer_median": d["peer_median"],
                "rank": d["rank"],
                "n_peers": d["n_peers"],
            }
            for f, d in peers_block["fields"].items()
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
        "statements": statements or None,
        "peers": peers_block or None,
        "dossier_markdown": dossier_md,
        # Still nudge to watchlist for ongoing tracking, even though the one-off
        # dossier is now rich (live fundamentals don't get stored / charted).
        # Only when something actually resolved: suggesting "add to watchlist"
        # for a company we couldn't identify (and found zero data for) is noise.
        "suggest_add_to_watchlist": (
            resolved.get("ticker") is not None
            and not is_tracked
            and (bool(resolved.get("confident")) or bool(live.get("key_metrics")))
        ),
        "disclaimer": "Decision-support research only — not investment advice. Verify independently.",
    }
