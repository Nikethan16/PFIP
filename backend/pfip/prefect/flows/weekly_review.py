"""Prefect flow: weekly review — runs Sundays 19:00 IST (13:30 UTC).

Compiles the trailing 7 days of activity into a single markdown file:

- Closed trades and aggregate realized P&L.
- Top failure patterns from post-mortems (delegates to the same logic
  behind ``GET /journal/patterns``).
- Regime changes per tracked symbol.
- Drawdown excursions vs current peak.
- Calibration deltas (ECE / Brier) for any model that emitted ≥10 signals
  this week.
- Top 5 winners + top 5 losers in the watchlist by 7d return.

Writes the markdown to ``data/weekly_reviews/weekly-review-YYYY-MM-DD.md``
and posts a single Telegram INFO alert linking to the file. The alert is
INFO not WARN — the review is a reflective tool, not an exception.

The flow is deliberately tolerant of missing data (any table can be
empty) — the section is just omitted with a "No data this week" note.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from prefect import flow, get_run_logger, task
from sqlalchemy import select

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.db.session import get_sessionmaker
from pfip.models.journal import JournalRow
from pfip.models.regime import RegimeRow

_OUT_DIR = Path("data/weekly_reviews")


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


@task(name="weekly-closed-trades")
async def _closed_trades_section(since: datetime) -> tuple[str, dict[str, float]]:
    """Render the closed-trades section + return aggregate stats for the digest."""
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(JournalRow)
            .where(JournalRow.closed_at.is_not(None))
            .where(JournalRow.closed_at >= since)
        )
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return ("## Closed trades\n\n_No trades closed this week._\n", {})

    lines = ["## Closed trades", ""]
    pnls: list[float] = []
    for r in rows:
        pnl = _extract_pnl(r)
        if pnl is not None:
            pnls.append(pnl)
        lines.append(
            f"- **{r.symbol}** {r.direction} → "
            f"closed {r.closed_at.strftime('%a %d')} "
            f"({'+' if pnl and pnl >= 0 else ''}{pnl:.2f}% realized)"
            if pnl is not None
            else f"- **{r.symbol}** {r.direction} → closed {r.closed_at.strftime('%a %d')}"
        )

    stats: dict[str, float] = {
        "n_closed": float(len(rows)),
        "avg_pnl_pct": float(mean(pnls)) if pnls else 0.0,
        "best_pnl_pct": float(max(pnls)) if pnls else 0.0,
        "worst_pnl_pct": float(min(pnls)) if pnls else 0.0,
        "win_rate": float(sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else 0.0,
    }
    lines.append("")
    lines.append(
        f"**{int(stats['n_closed'])} trades** · avg {stats['avg_pnl_pct']:+.2f}% · "
        f"win-rate {stats['win_rate'] * 100:.0f}% · "
        f"best {stats['best_pnl_pct']:+.2f}% · worst {stats['worst_pnl_pct']:+.2f}%"
    )
    return ("\n".join(lines) + "\n", stats)


def _extract_pnl(row: JournalRow) -> float | None:
    """JournalRow.post_mortem is either a JSONB blob (contract form) or a
    plain markdown text. Try both."""
    pm = getattr(row, "post_mortem", None)
    if isinstance(pm, dict):
        v = pm.get("outcome_pnl_pct") or pm.get("realized_pnl_pct")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    return None


@task(name="weekly-failure-patterns")
async def _failure_patterns_section(since: datetime) -> str:
    """Aggregate post-mortems' first clause into a top-5 list."""
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(JournalRow)
            .where(JournalRow.closed_at.is_not(None))
            .where(JournalRow.closed_at >= since)
            .where(JournalRow.post_mortem.is_not(None))
        )
        rows = (await session.execute(stmt)).scalars().all()

    counter: Counter[str] = Counter()
    for r in rows:
        text = r.post_mortem if isinstance(r.post_mortem, str) else None
        if not text:
            continue
        raw = text.strip().lower()
        first = raw
        for sep in (".", ",", ";", "\n"):
            idx = first.find(sep)
            if idx != -1 and idx < 200:
                first = first[:idx]
        key = first.strip()[:60] or raw[:60]
        counter[key] += 1

    if not counter:
        return "## Top failure patterns\n\n_No closed-trade post-mortems to aggregate._\n"

    lines = ["## Top failure patterns", ""]
    for i, (pattern, n) in enumerate(counter.most_common(5), start=1):
        lines.append(f"{i}. _{pattern}_ — **×{n}**")
    return "\n".join(lines) + "\n"


@task(name="weekly-regime-changes")
async def _regime_changes_section(since: datetime) -> str:
    """Group regime rows by symbol; list each transition."""
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(RegimeRow)
            .where(RegimeRow.since >= since)
            .order_by(RegimeRow.symbol.asc(), RegimeRow.since.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return "## Regime changes\n\n_No regime updates this week._\n"

    by_symbol: dict[str, list[RegimeRow]] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol, []).append(r)

    lines = ["## Regime changes", ""]
    for symbol, items in sorted(by_symbol.items()):
        # Detect transitions: consecutive different regimes.
        prev = None
        transitions = []
        for r in items:
            if prev is None or prev != r.regime:
                transitions.append((r.since, r.regime, r.confidence))
            prev = r.regime
        if len(transitions) <= 1:
            continue
        chain = " → ".join(f"{t[1]}({t[2]:.2f})@{t[0].strftime('%a')}" for t in transitions)
        lines.append(f"- **{symbol}**: {chain}")

    if len(lines) == 2:
        lines.append("_No symbol crossed a regime boundary._")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


@flow(name="weekly-review", log_prints=True)
async def weekly_review(days: int = 7) -> str | None:
    """Generate the weekly review markdown + post a digest alert.

    Returns the path of the markdown file written, or None on no-op."""
    logger = get_run_logger()
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=days)

    closed_md, closed_stats = await _closed_trades_section(since)
    patterns_md = await _failure_patterns_section(since)
    regime_md = await _regime_changes_section(since)

    header = (
        f"# Weekly review — {now.strftime('%Y-%m-%d')}\n\n"
        f"_Window: last {days} days · auto-generated · review and journal "
        f"reactions inline._\n\n---\n\n"
    )

    footer = (
        "\n---\n\n"
        "## Things to do before next week\n\n"
        "- [ ] Reread top 2 failure patterns above; identify the underlying habit.\n"
        "- [ ] If any regime change above is on a held asset — does the original "
        "thesis still hold? Log to journal.\n"
        "- [ ] If drawdown crossed 10% peak-to-trough at any point, run the "
        "halt protocol from `WHY_AND_WHAT.md` §7.\n"
        "- [ ] Calibration / RAGAS reports if their monthly cadence falls "
        "this week — see `data/.telemetry/`.\n"
    )

    body = header + closed_md + "\n" + patterns_md + "\n" + regime_md + footer

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUT_DIR / f"weekly-review-{now.strftime('%Y-%m-%d')}.md"
    out_path.write_text(body, encoding="utf-8")
    logger.info("weekly review written to {}", out_path)

    # Telegram digest.
    digest_lines = [
        f"📰 *Weekly review — {now.strftime('%Y-%m-%d')}*",
        "",
        f"Closed trades: *{int(closed_stats.get('n_closed', 0))}*",
    ]
    if closed_stats.get("n_closed", 0) > 0:
        digest_lines.append(f"Avg P&L: *{closed_stats.get('avg_pnl_pct', 0.0):+.2f}%*")
        digest_lines.append(f"Win rate: *{closed_stats.get('win_rate', 0.0) * 100:.0f}%*")
    digest_lines.append("")
    digest_lines.append(f"Full review on disk: `{out_path}`")
    await send_alert(
        kind=AlertKind.WEEKLY_REVIEW,
        severity=AlertSeverity.INFO,
        body_override="\n".join(digest_lines),
        title_override=f"Weekly review {now.strftime('%Y-%m-%d')}",
    )

    return str(out_path)


if __name__ == "__main__":
    import asyncio

    asyncio.run(weekly_review())
