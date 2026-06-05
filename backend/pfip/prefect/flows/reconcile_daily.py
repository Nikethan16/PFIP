"""Prefect flow: daily cross-source price reconciliation.

Pulls each symbol's latest close from each ``ohlcv.source``, asks
``pfip.ingest._common.reconcile`` to find divergent pairs, persists
findings to ``data/reconciliation/<date>.jsonl``, and fires a Telegram
WARN when the worst divergence exceeds the threshold.

Scheduled at 18:45 UTC (after the anomaly scan, both around 00:00 IST).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, get_run_logger, task
from sqlalchemy import desc, distinct, select

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.reconcile import (
    Divergence,
    PriceObservation,
    reconcile_latest_closes,
)
from pfip.models.ohlcv import OHLCVRow

_OUT_DIR = Path("data/reconciliation")
_DEFAULT_THRESHOLD = 0.005  # 0.5%


@task(name="reconcile-fetch-latest")
async def _fetch_latest_closes() -> list[PriceObservation]:
    """One row per (symbol, source) — latest close."""
    factory = get_sessionmaker()
    async with factory() as session:
        # SQLAlchemy 2.0: use a window function / subquery to get max-ts per
        # (symbol, source). For simplicity, we fetch distinct pairs then
        # latest per pair.
        pairs_q = await session.execute(
            select(distinct(OHLCVRow.symbol), OHLCVRow.source)
        )
        pairs = list(pairs_q.all())
        out: list[PriceObservation] = []
        for symbol, source in pairs:
            row_q = await session.execute(
                select(OHLCVRow)
                .where(OHLCVRow.symbol == symbol)
                .where(OHLCVRow.source == source)
                .order_by(desc(OHLCVRow.ts))
                .limit(1)
            )
            row = row_q.scalar_one_or_none()
            if row is None:
                continue
            out.append(
                PriceObservation(
                    symbol=row.symbol,
                    source=row.source,
                    ts=row.ts,
                    close=float(row.close),
                )
            )
        return out


@task(name="reconcile-persist")
def _persist(divergences: list[Divergence]) -> Path | None:
    if not divergences:
        return None
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    out = _OUT_DIR / f"{today}.jsonl"
    with out.open("a", encoding="utf-8") as fp:
        for d in divergences:
            fp.write(
                json.dumps(
                    {
                        "symbol": d.symbol,
                        "source_a": d.source_a,
                        "source_b": d.source_b,
                        "close_a": d.close_a,
                        "close_b": d.close_b,
                        "diff_pct": d.diff_pct,
                    }
                )
                + "\n"
            )
    return out


@task(name="reconcile-alert")
async def _maybe_alert(divergences: list[Divergence], *, threshold: float) -> None:
    if not divergences:
        return
    worst = divergences[0]
    if abs(worst.diff_pct) < threshold:
        return
    lines = [
        "⚠️ *Cross-source price divergence*",
        f"Worst: `{worst.symbol}` "
        f"`{worst.source_a}={worst.close_a:.4f}` vs "
        f"`{worst.source_b}={worst.close_b:.4f}` "
        f"({worst.diff_pct * 100:+.2f}%)",
    ]
    if len(divergences) > 1:
        lines.append("")
        lines.append("Other divergences this run:")
        for d in divergences[1:5]:
            lines.append(
                f"- `{d.symbol}` {d.source_a} vs {d.source_b}: "
                f"{d.diff_pct * 100:+.2f}%"
            )
    lines.append("")
    lines.append("Open `data/reconciliation/<date>.jsonl` for the full list.")
    await send_alert(
        kind=AlertKind.INGEST_FAILURE,
        severity=AlertSeverity.WARN,
        body_override="\n".join(lines),
        title_override="Cross-source divergence",
    )


@flow(name="reconcile-daily", log_prints=True)
async def reconcile_daily(threshold_pct: float = _DEFAULT_THRESHOLD) -> dict[str, int]:
    """End-to-end reconcile flow."""
    logger = get_run_logger()
    obs = await _fetch_latest_closes()
    if len(obs) < 2:
        logger.info("Skipping reconcile — fewer than 2 (symbol,source) observations")
        return {"observations": len(obs), "divergences": 0}

    findings = reconcile_latest_closes(obs, threshold_pct=threshold_pct)
    path = _persist(findings)
    await _maybe_alert(findings, threshold=threshold_pct)

    logger.info(
        "Reconcile complete: {} observations, {} divergences ≥ {:.2%}",
        len(obs),
        len(findings),
        threshold_pct,
    )
    return {
        "observations": len(obs),
        "divergences": len(findings),
        "log_path": str(path) if path else None,
    }


if __name__ == "__main__":
    import asyncio

    asyncio.run(reconcile_daily())
