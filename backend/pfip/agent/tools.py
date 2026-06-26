"""Tool registry for the chat agent.

When `pfip.agent.intent.classify_intent` returns `DB_QUERY`, the agent
graph calls into this registry to actually fetch the number. We deliberately
keep these as plain async functions (not LangGraph tools or LiteLLM tool
descriptions) because the v1 surface only needs ~6 of them and the LLM
doesn't pick — the heuristic intent step does.

Each tool:
- Takes an :class:`AsyncSession` and a small dict of kwargs.
- Returns a JSON-safe dict the agent can format into the user response.
- Never raises on missing data; returns ``{"ok": False, "error": ...}``.

The registry is a plain mapping; the agent looks up by name (a string the
intent classifier emits alongside the intent).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any


async def _safe_decimal(value: Any) -> float:
    try:
        return float(Decimal(str(value)))
    except Exception:
        return 0.0


async def get_holdings(session: Any, *, asset_class: str | None = None) -> dict[str, Any]:
    """Return current holdings, optionally filtered by asset class."""
    try:
        from sqlalchemy import select

        from pfip.models.holdings import HoldingRow
    except Exception as exc:
        return {"ok": False, "error": f"holdings model unavailable: {exc}"}
    stmt = select(HoldingRow).where(HoldingRow.qty > 0)
    if asset_class:
        stmt = stmt.where(HoldingRow.asset_class == asset_class)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "ok": True,
        "holdings": [
            {
                "symbol": r.symbol,
                "qty": float(r.qty),
                "asset_class": getattr(r, "asset_class", None),
                "avg_cost_inr": float(getattr(r, "avg_cost_inr", 0) or 0),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def get_current_price(session: Any, *, symbol: str) -> dict[str, Any]:
    """Return the latest close price for a symbol."""
    try:
        from sqlalchemy import desc, select

        from pfip.models.ohlcv import OHLCVRow
    except Exception as exc:
        return {"ok": False, "error": f"ohlcv model unavailable: {exc}"}
    row = (
        await session.execute(
            select(OHLCVRow.close, OHLCVRow.ts)
            .where(OHLCVRow.symbol == symbol)
            .order_by(desc(OHLCVRow.ts))
            .limit(1)
        )
    ).first()
    if row is None:
        return {"ok": False, "error": f"no ohlcv for {symbol}"}
    return {
        "ok": True,
        "symbol": symbol,
        "close": float(row[0]),
        "as_of": row[1].isoformat() if row[1] else None,
    }


async def get_recent_pnl(session: Any, *, days: int = 7) -> dict[str, Any]:
    """Aggregate realized P&L from closed journal entries in the last `days`."""
    try:
        from sqlalchemy import select

        from pfip.models.journal import JournalRow
    except Exception as exc:
        return {"ok": False, "error": f"journal model unavailable: {exc}"}
    since = datetime.now(tz=UTC) - timedelta(days=max(1, days))
    rows = (
        (
            await session.execute(
                select(JournalRow)
                .where(JournalRow.closed_at.is_not(None))
                .where(JournalRow.closed_at >= since)
            )
        )
        .scalars()
        .all()
    )
    pnls: list[float] = []
    for j in rows:
        pm = getattr(j, "post_mortem", None)
        if isinstance(pm, dict):
            v = pm.get("outcome_pnl_pct") or pm.get("realized_pnl_pct")
            if v is not None:
                try:
                    pnls.append(float(v))
                except (TypeError, ValueError):
                    continue
    return {
        "ok": True,
        "days": days,
        "n_closed": len(rows),
        "n_with_pnl": len(pnls),
        "avg_pnl_pct": float(sum(pnls) / len(pnls)) if pnls else 0.0,
        "best_pnl_pct": max(pnls) if pnls else 0.0,
        "worst_pnl_pct": min(pnls) if pnls else 0.0,
    }


async def get_open_signals(session: Any, *, limit: int = 20) -> dict[str, Any]:
    """Return recent signals above confidence floor (default 65).

    Honours the ``FEATURE_ML_SIGNALS`` gate: returns an empty set when signals
    are off (the directional model has no demonstrated edge — see
    docs/SIGNAL_BACKTEST_2026-06-26), so the agent never cites gated signals.
    """
    from pfip.core.config import get_settings

    if not get_settings().feature_ml_signals:
        return {"ok": True, "signals": [], "count": 0, "note": "signals gated off"}
    try:
        from sqlalchemy import desc, select

        from pfip.models.signals import SignalRow
    except Exception as exc:
        return {"ok": False, "error": f"signals model unavailable: {exc}"}
    rows = (
        (
            await session.execute(
                select(SignalRow)
                .where(SignalRow.confidence >= 65)
                .order_by(desc(SignalRow.generated_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "ok": True,
        "signals": [
            {
                "symbol": s.asset,
                "direction": s.direction,
                "confidence": float(s.confidence),
                "regime": getattr(s, "regime", None),
                "generated_at": s.generated_at.isoformat() if s.generated_at else None,
            }
            for s in rows
        ],
        "count": len(rows),
    }


async def get_diligence(session: Any, *, symbol: str) -> dict[str, Any]:
    """Aggregate everything PFIP knows about ``symbol`` for a due-diligence read.

    Thin wrapper over :func:`pfip.diligence.service.build_diligence` (the single
    shared implementation also backing ``GET /api/v1/diligence/{symbol}``).
    Returns the same structured aggregate — price, fundamentals + key metrics,
    filings, insider/PIT disclosures, FII/DII flows, on-chain metrics,
    regime/signal model read, recent news, and an honest derived summary.

    Never raises: a blank symbol or a lookup failure safe-fails to
    ``{"ok": False, ...}`` like the other tools. ``found=False`` means the symbol
    is unknown to the platform (no OHLCV history) — the dict is still well-formed.
    """
    sym = (symbol or "").strip()
    if not sym:
        return {"ok": False, "error": "symbol is required for diligence"}
    try:
        from pfip.diligence.service import build_diligence

        data = await build_diligence(session, sym)
    except Exception as exc:  # — tool surface never raises
        return {"ok": False, "error": f"diligence aggregation failed: {exc}"}
    return {"ok": True, "diligence": data, "found": bool(data.get("found"))}


async def get_tax_summary(session: Any, *, fy: str) -> dict[str, Any]:
    """Quick tax-summary lookup for an FY. Just the headline numbers."""
    try:
        from sqlalchemy import select

        from pfip.models.portfolio_tx import PortfolioTxRow
        from pfip.tax.engine import (
            build_tax_summary,
            classify_capital_gains,
        )

        rows = (await session.execute(select(PortfolioTxRow))).scalars().all()
        events = classify_capital_gains([dict(r.__dict__) for r in rows])
        summary = build_tax_summary(fy, events, gross_income=Decimal("0"))
        return {
            "ok": True,
            "fy": fy,
            "stcg_equity_inr": float(summary.stcg_equity_inr),
            "ltcg_equity_inr": float(summary.ltcg_equity_inr),
            "vda_gain_inr": float(summary.vda_gain_inr),
            "dividend_inr": float(summary.dividend_inr),
            "total_tax_inr": float(summary.total_tax_inr),
            "recommended_regime": summary.recommended_regime,
        }
    except Exception as exc:
        return {"ok": False, "error": f"tax engine failed: {exc}"}


# Registry — name → callable. The agent looks up by name when dispatching.
ToolFn = Callable[..., Awaitable[dict[str, Any]]]

REGISTRY: dict[str, ToolFn] = {
    "get_holdings": get_holdings,
    "get_current_price": get_current_price,
    "get_recent_pnl": get_recent_pnl,
    "get_open_signals": get_open_signals,
    "get_tax_summary": get_tax_summary,
    "get_diligence": get_diligence,
}


def dispatch(name: str) -> ToolFn | None:
    """Lookup a tool by name. Returns None if not registered."""
    return REGISTRY.get(name)


__all__ = ["REGISTRY", "dispatch", "ToolFn"]
