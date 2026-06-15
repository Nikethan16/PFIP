"""End-of-day market-close summary composer.

Called by the ``market_close_summary`` Prefect flow each weekday at
17:30 IST. Builds a compact 6-section snapshot of the trading day:

1. Index moves (NIFTY 50, SENSEX, S&P 500, BTC, ETH).
2. Watchlist movers (top 3 gainers / losers by abs % move).
3. Realized P&L for any positions closed today (joins to journal).
4. Risk-cap status (any breaches today; current drawdown vs halt).
5. New-signal count by regime.
6. Today's top 5 news by impact score.

Output is a plain markdown string the alert dispatcher can wrap and
push to Telegram (and the dashboard agent can render verbatim).

The composer is intentionally idempotent + side-effect-free at the
function boundary: pass in `today_ist_date` for tests; default is "now".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(slots=True)
class IndexMove:
    symbol: str
    close: float
    change_pct: float


@dataclass(slots=True)
class WatchlistMove:
    symbol: str
    change_pct: float


@dataclass(slots=True)
class ClosedTrade:
    symbol: str
    realized_pnl_pct: float
    pattern_tag: str | None


@dataclass(slots=True)
class RiskBreach:
    rule: str
    value: float
    threshold: float


@dataclass(slots=True)
class SignalCount:
    regime: str
    count: int


@dataclass(slots=True)
class NewsHit:
    title: str
    impact: int
    url: str | None = None


@dataclass(slots=True)
class MarketCloseSummary:
    fy_date: date
    indexes: list[IndexMove] = field(default_factory=list)
    watchlist_gainers: list[WatchlistMove] = field(default_factory=list)
    watchlist_losers: list[WatchlistMove] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    risk_breaches: list[RiskBreach] = field(default_factory=list)
    signal_counts: list[SignalCount] = field(default_factory=list)
    top_news: list[NewsHit] = field(default_factory=list)
    current_drawdown_pct: float = 0.0
    halt_threshold_pct: float = 20.0


def _fmt_pct(p: float) -> str:
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.2f}%"


def render_markdown(summary: MarketCloseSummary) -> str:
    """Compose the markdown — pure function, no I/O."""
    lines: list[str] = [
        f"# 🛎️ Market close — {summary.fy_date.strftime('%a %d %b %Y')}",
        "",
    ]

    # 1. Indexes
    if summary.indexes:
        lines.append("## Indexes")
        lines.append("")
        for ix in summary.indexes:
            lines.append(f"- **{ix.symbol}** {ix.close:,.2f} ({_fmt_pct(ix.change_pct)})")
        lines.append("")
    else:
        lines.append("## Indexes\n\n_No data._\n")

    # 2. Watchlist movers
    if summary.watchlist_gainers or summary.watchlist_losers:
        lines.append("## Watchlist movers")
        lines.append("")
        if summary.watchlist_gainers:
            lines.append("_Gainers:_")
            for g in summary.watchlist_gainers:
                lines.append(f"- `{g.symbol}` {_fmt_pct(g.change_pct)}")
        if summary.watchlist_losers:
            lines.append("")
            lines.append("_Losers:_")
            for l in summary.watchlist_losers:
                lines.append(f"- `{l.symbol}` {_fmt_pct(l.change_pct)}")
        lines.append("")

    # 3. Closed trades
    if summary.closed_trades:
        lines.append("## Closed trades today")
        lines.append("")
        for t in summary.closed_trades:
            tag = f" — _{t.pattern_tag}_" if t.pattern_tag else ""
            lines.append(f"- **{t.symbol}**: {_fmt_pct(t.realized_pnl_pct)}{tag}")
        lines.append("")

    # 4. Risk
    lines.append("## Risk")
    lines.append("")
    lines.append(
        f"- Current drawdown: **{_fmt_pct(-abs(summary.current_drawdown_pct))}** "
        f"(halt at -{summary.halt_threshold_pct:.0f}%)"
    )
    if summary.risk_breaches:
        lines.append("- ⚠️ Breaches today:")
        for b in summary.risk_breaches:
            lines.append(f"  - `{b.rule}`: {b.value:.2f} (threshold {b.threshold:.2f})")
    else:
        lines.append("- ✅ No breaches today")
    lines.append("")

    # 5. Signals
    if summary.signal_counts:
        lines.append("## New signals today")
        lines.append("")
        total = sum(c.count for c in summary.signal_counts)
        lines.append(f"- Total: **{total}**")
        for c in summary.signal_counts:
            lines.append(f"  - {c.regime}: {c.count}")
        lines.append("")

    # 6. News
    if summary.top_news:
        lines.append("## Top news by impact")
        lines.append("")
        for n in summary.top_news[:5]:
            link = f" [→]({n.url})" if n.url else ""
            lines.append(f"- _(impact {n.impact})_ {n.title}{link}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Auto-generated. The numbers come from your DB; the takeaways are yours._")
    return "\n".join(lines)


async def build_summary_from_db(today_ist: date | None = None) -> MarketCloseSummary:
    """Pull everything from the DB.

    Best-effort: any section that fails is skipped (empty list). The
    composer always returns a usable shell.
    """
    if today_ist is None:
        today_ist = datetime.now(tz=IST).date()
    summary = MarketCloseSummary(fy_date=today_ist)

    # Local imports — the agent should boot even if a model is missing.
    try:
        from sqlalchemy import desc, func, select

        from pfip.db.session import get_sessionmaker
        from pfip.models.journal import JournalRow
        from pfip.models.ohlcv import OHLCVRow
        from pfip.models.signals import SignalRow
        from pfip.models.watchlist import WatchlistRow
    except Exception:  # pragma: no cover — best-effort
        return summary

    factory = get_sessionmaker()
    async with factory() as session:
        # 1. Indexes — use a fixed set; tolerate missing rows.
        for sym in ("^NSEI", "^BSESN", "^GSPC", "BTC/USD", "ETH/USD"):
            try:
                rows = (
                    await session.execute(
                        select(OHLCVRow.close, OHLCVRow.ts)
                        .where(OHLCVRow.symbol == sym)
                        .order_by(desc(OHLCVRow.ts))
                        .limit(2)
                    )
                ).all()
                if len(rows) < 2:
                    continue
                today_close = float(rows[0][0])
                yday_close = float(rows[1][0])
                change_pct = (
                    ((today_close - yday_close) / yday_close * 100.0) if yday_close else 0.0
                )
                summary.indexes.append(
                    IndexMove(symbol=sym, close=today_close, change_pct=change_pct)
                )
            except Exception:
                continue

        # 2. Watchlist movers — top 3 by absolute % move.
        try:
            wl_rows = (await session.execute(select(WatchlistRow.symbol).distinct())).all()
            wl_syms = [r[0] for r in wl_rows]
            moves: list[WatchlistMove] = []
            for sym in wl_syms:
                bars = (
                    await session.execute(
                        select(OHLCVRow.close, OHLCVRow.ts)
                        .where(OHLCVRow.symbol == sym)
                        .order_by(desc(OHLCVRow.ts))
                        .limit(2)
                    )
                ).all()
                if len(bars) < 2:
                    continue
                today_c = float(bars[0][0])
                yday_c = float(bars[1][0])
                if yday_c == 0:
                    continue
                pct = (today_c - yday_c) / yday_c * 100.0
                moves.append(WatchlistMove(symbol=sym, change_pct=pct))
            moves.sort(key=lambda m: m.change_pct, reverse=True)
            summary.watchlist_gainers = [m for m in moves[:3] if m.change_pct > 0]
            summary.watchlist_losers = [m for m in moves[-3:] if m.change_pct < 0]
        except Exception:
            pass

        # 3. Closed trades today
        try:
            since = datetime.combine(today_ist, datetime.min.time(), tzinfo=timezone.utc)
            closed = (
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
            for j in closed:
                pnl = 0.0
                pm = getattr(j, "post_mortem", None)
                if isinstance(pm, dict):
                    pnl = float(pm.get("outcome_pnl_pct") or 0.0)
                summary.closed_trades.append(
                    ClosedTrade(symbol=j.symbol, realized_pnl_pct=pnl, pattern_tag=None)
                )
        except Exception:
            pass

        # 5. Signal counts by regime
        try:
            since = datetime.combine(today_ist, datetime.min.time(), tzinfo=timezone.utc)
            counts = (
                await session.execute(
                    select(SignalRow.regime, func.count(SignalRow.id))
                    .where(SignalRow.generated_at >= since)
                    .group_by(SignalRow.regime)
                )
            ).all()
            for regime, n in counts:
                summary.signal_counts.append(SignalCount(regime=str(regime), count=int(n)))
        except Exception:
            pass

    return summary


__all__ = [
    "ClosedTrade",
    "IndexMove",
    "MarketCloseSummary",
    "NewsHit",
    "RiskBreach",
    "SignalCount",
    "WatchlistMove",
    "build_summary_from_db",
    "render_markdown",
]
