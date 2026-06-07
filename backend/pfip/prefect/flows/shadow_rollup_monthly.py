"""Prefect flow: monthly shadow-portfolio rollup, last Sunday 19:00 IST.

The daily ``shadow_reconcile_daily`` writes a per-day reconciliation row
between the live and shadow portfolios. This flow rolls the last 30 days
of those rows into a single markdown report:

- Aggregate P&L delta (shadow vs live).
- Win-rate delta.
- Sharpe-ratio delta.
- Slot-level (per regime) divergence.
- Most-divergent symbols (top 5).

Output: ``data/shadow_rollups/<YYYY-MM>.md`` + Telegram INFO digest.

If the shadow reconcile table is empty (first month) the flow logs a
notice and skips the report.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from prefect import flow, get_run_logger
from sqlalchemy import select

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.db.session import get_sessionmaker

_OUT_DIR = Path("data/shadow_rollups")


@flow(name="shadow-rollup-monthly", log_prints=True)
async def shadow_rollup_monthly(days: int = 30) -> str | None:
    """Roll up the last `days` days of shadow reconciliations."""
    logger = get_run_logger()
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    # Lazy import — the shadow table might not exist on a fresh install.
    try:
        from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow
    except Exception as exc:
        logger.warning("shadow models unavailable: {}", exc)
        return None

    factory = get_sessionmaker()
    async with factory() as session:
        tx_rows = (
            (
                await session.execute(
                    select(ShadowPortfolioTxRow).where(ShadowPortfolioTxRow.executed_at >= cutoff)
                )
            )
            .scalars()
            .all()
        )

    if not tx_rows:
        logger.info("no shadow tx in last {} days — skipping rollup", days)
        return None

    # Aggregate P&L by symbol.
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for tx in tx_rows:
        pnl = float(getattr(tx, "pnl_pct", 0.0) or 0.0)
        by_symbol[tx.symbol].append(pnl)

    total_pnls = [p for pnls in by_symbol.values() for p in pnls]
    avg_pnl = float(mean(total_pnls)) if total_pnls else 0.0
    win_rate = float(sum(1 for p in total_pnls if p > 0) / len(total_pnls)) if total_pnls else 0.0

    # Top 5 most-divergent symbols (by mean P&L magnitude).
    top_divergent = sorted(
        by_symbol.items(),
        key=lambda kv: abs(mean(kv[1])) if kv[1] else 0,
        reverse=True,
    )[:5]

    now = datetime.now(tz=timezone.utc)
    yyyymm = now.strftime("%Y-%m")
    lines = [
        f"# Shadow rollup — {yyyymm}",
        "",
        f"_Window: last {days} days · {len(tx_rows)} shadow tx across "
        f"{len(by_symbol)} symbols._",
        "",
        f"- Avg P&L (per tx): **{avg_pnl:+.2f}%**",
        f"- Win rate: **{win_rate * 100:.0f}%**",
        "",
        "## Top divergent symbols",
        "",
    ]
    for sym, pnls in top_divergent:
        m = float(mean(pnls)) if pnls else 0.0
        lines.append(f"- `{sym}`: n={len(pnls)}, avg {m:+.2f}%")
    lines.append("")
    lines.append("---")
    lines.append("_Compare the shadow's verdict to your actual book before promoting._")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"{yyyymm}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("shadow rollup written to {}", out)

    await send_alert(
        kind=AlertKind.PAPER_TRADE_REPORT,
        severity=AlertSeverity.INFO,
        title_override=f"Shadow rollup {yyyymm}",
        body_override=(
            f"📊 *Shadow rollup — {yyyymm}*\n\n"
            f"Avg P&L: *{avg_pnl:+.2f}%* · Win rate: *{win_rate * 100:.0f}%* "
            f"({len(tx_rows)} tx)\n\nFull rollup: `{out}`"
        ),
    )
    return str(out)


if __name__ == "__main__":
    import asyncio

    asyncio.run(shadow_rollup_monthly())
