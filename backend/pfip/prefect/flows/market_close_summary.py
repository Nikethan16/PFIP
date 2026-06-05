"""Prefect flow: daily market-close summary at 17:30 IST (12:00 UTC).

Composer lives in `pfip.agent.market_close`. This flow drives it,
persists the rendered markdown to `data/market_close/<date>.md` and
posts a Telegram INFO with the path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, get_run_logger

from pfip.agent.market_close import build_summary_from_db, render_markdown
from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

_OUT_DIR = Path("data/market_close")


@flow(name="market-close-summary", log_prints=True)
async def market_close_summary() -> str | None:
    """Compose + persist + alert. Returns the markdown file path."""
    logger = get_run_logger()
    summary = await build_summary_from_db()
    md = render_markdown(summary)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"close-{summary.fy_date.isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    logger.info("market close summary written to {}", out)

    # Compact digest for Telegram.
    lines = [
        f"🛎️ *Market close — {summary.fy_date.isoformat()}*",
        "",
    ]
    if summary.indexes:
        lines.append("*Indexes:*")
        for ix in summary.indexes:
            sign = "+" if ix.change_pct >= 0 else ""
            lines.append(f"  {ix.symbol} {sign}{ix.change_pct:.2f}%")
    if summary.closed_trades:
        lines.append("")
        lines.append(f"*Closed trades:* {len(summary.closed_trades)}")
    if summary.risk_breaches:
        lines.append("")
        lines.append(f"⚠️ *Risk breaches:* {len(summary.risk_breaches)}")
    lines.append("")
    lines.append(f"Full markdown: `{out}`")
    await send_alert(
        kind=AlertKind.SYSTEM_HEALTH,
        severity=AlertSeverity.INFO,
        title_override=f"Market close {summary.fy_date.isoformat()}",
        body_override="\n".join(lines),
    )
    return str(out)


if __name__ == "__main__":
    import asyncio

    asyncio.run(market_close_summary())
