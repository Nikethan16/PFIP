"""Prefect flow: annual ITR calibration drill.

Fires once a year on June 15 (advance-tax milestone) for the just-completed
FY. Recomputes the engine's tax summary against the user's filed numbers
(if available in `data/itr_filed/<FY>.json`) and writes a delta report.

The calibration target is ±2% on every aggregate line. Anything outside
that band is a code bug, a rate-table drift, or a missed transaction —
all of which want human review.

Output: `data/itr_calibration/<FY>.md` + Telegram WARN if any line is
out-of-band (else INFO).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert


_FILED_DIR = Path("data/itr_filed")
_OUT_DIR = Path("data/itr_calibration")
_BAND = Decimal("0.02")  # 2%


def _previous_fy() -> str:
    """Return the FY just ended, e.g. on 2026-06-15 → '2025-26'."""
    today = date.today()
    if today.month >= 4:
        start = today.year - 1
    else:
        start = today.year - 2
    return f"{start}-{(start + 1) % 100:02d}"


def _delta_pct(filed: Decimal, computed: Decimal) -> Decimal:
    """|computed - filed| / max(|filed|, 1) → fractional band."""
    base = abs(filed) if abs(filed) > 1 else Decimal("1")
    return abs(computed - filed) / base


@flow(name="annual-itr-drill", log_prints=True)
async def annual_itr_drill(fy: str | None = None) -> dict[str, Any]:
    """Reconcile the engine against the filed ITR for `fy`."""
    logger = get_run_logger()
    fy = fy or _previous_fy()

    filed_path = _FILED_DIR / f"{fy}.json"
    if not filed_path.exists():
        logger.warning(
            "no filed ITR at {} — calibration deferred. Drop the filed JSON in "
            "`data/itr_filed/<FY>.json` shape: "
            "{{stcg_equity_inr, ltcg_equity_inr, vda_gain_inr, dividend_inr, "
            "interest_inr, total_tax_inr}}",
            filed_path,
        )
        return {"fy": fy, "status": "no-filed-json"}

    try:
        filed = {
            k: Decimal(str(v))
            for k, v in json.loads(filed_path.read_text(encoding="utf-8")).items()
        }
    except Exception as exc:
        logger.warning("filed JSON unreadable: {}", exc)
        return {"fy": fy, "status": "filed-unreadable", "error": str(exc)}

    # Recompute via the engine.
    try:
        from pfip.tax.engine import (
            build_tax_summary,
            classify_capital_gains,
            fy_bounds,
        )
        from sqlalchemy import select

        from pfip.db.session import get_sessionmaker
        from pfip.models.portfolio_tx import PortfolioTxRow

        factory = get_sessionmaker()
        async with factory() as session:
            tx = (await session.execute(select(PortfolioTxRow))).scalars().all()
        events = classify_capital_gains([dict(t.__dict__) for t in tx])
        computed_summary = build_tax_summary(fy, events, gross_income=Decimal("0"))
        computed = {
            "stcg_equity_inr": computed_summary.stcg_equity_inr,
            "ltcg_equity_inr": computed_summary.ltcg_equity_inr,
            "vda_gain_inr": computed_summary.vda_gain_inr,
            "dividend_inr": computed_summary.dividend_inr,
            "interest_inr": computed_summary.interest_inr,
            "total_tax_inr": computed_summary.total_tax_inr,
        }
    except Exception as exc:
        logger.warning("engine recompute failed: {}", exc)
        return {"fy": fy, "status": "engine-failed", "error": str(exc)}

    # Compare line by line.
    rows: list[tuple[str, Decimal, Decimal, Decimal, bool]] = []
    out_of_band: list[str] = []
    for k, f_val in filed.items():
        c_val = Decimal(str(computed.get(k, "0")))
        delta = _delta_pct(f_val, c_val)
        is_oob = delta > _BAND
        rows.append((k, f_val, c_val, delta, is_oob))
        if is_oob:
            out_of_band.append(k)

    # Write markdown.
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"{fy}.md"
    lines = [
        f"# ITR calibration — FY {fy}",
        "",
        f"_Generated {datetime.now(tz=timezone.utc).isoformat()}_",
        "",
        "| Line | Filed | Computed | Δ% | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for k, f_val, c_val, delta, is_oob in rows:
        status = "❌ OOB" if is_oob else "✅"
        lines.append(f"| {k} | ₹{f_val:,.2f} | ₹{c_val:,.2f} | {delta * 100:.2f}% | {status} |")
    lines.append("")
    if out_of_band:
        lines.append(f"**{len(out_of_band)} line(s) out of ±2% band**: {', '.join(out_of_band)}")
    else:
        lines.append("All lines within ±2% — engine matches filed ITR.")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("ITR calibration written to {}", out)

    severity = AlertSeverity.WARN if out_of_band else AlertSeverity.INFO
    await send_alert(
        kind=AlertKind.CALIBRATION_BREACH if out_of_band else AlertKind.SYSTEM_HEALTH,
        severity=severity,
        title_override=f"ITR calibration FY {fy}",
        body_override=(
            f"📋 *ITR calibration — FY {fy}*\n\n"
            f"{'⚠️ ' + str(len(out_of_band)) + ' line(s) out of ±2%: ' + ', '.join(out_of_band) if out_of_band else '✅ All lines within ±2%'}\n\n"
            f"Full report: `{out}`"
        ),
    )
    return {"fy": fy, "out_of_band": out_of_band, "report": str(out)}


if __name__ == "__main__":
    import asyncio

    asyncio.run(annual_itr_drill())
