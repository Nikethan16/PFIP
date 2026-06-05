"""Daily shadow reconciliation entry point.

Designed to be called from the Prefect flow ``shadow_reconcile_daily`` at
23:30 IST. Logic per spec:

1. Read today's signals from the ``signals`` table that are at-or-above the
   shadow confidence floor (default 65).
2. For each, look up the latest price for the asset.
3. Feed into :class:`pfip.shadow.engine.ShadowPortfolio.apply_signal` which
   enforces the risk rules (max position, drawdown, correlation, daily cap).
4. Return a summary of accepts vs rejects plus the post-run MtM equity.

The reconcile flow does **not** generate signals itself — it just consumes
the latest persisted ones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, select

from pfip.core.contracts import Driver, Regime, Signal, SignalDirection
from pfip.shadow.engine import ShadowPortfolio

log = logging.getLogger(__name__)


@dataclass
class ReconcileSummary:
    accepted: int
    rejected: int
    skipped_no_price: int
    equity_inr: float
    decisions: list[dict]


def _row_to_signal(row) -> Signal:
    return Signal(
        direction=SignalDirection(row.direction),
        confidence=int(row.confidence),
        horizon_hours=int(row.horizon_hours),
        drivers=[Driver(**d) for d in (row.drivers or [])],
        counter_arguments=[Driver(**d) for d in (row.counter_arguments or [])],
        regime=Regime(row.regime),
        model_name=row.model_name,
        model_version=row.model_version,
        asset=row.asset,
        generated_at=row.generated_at,
    )


async def _fetch_recent_signals(session, hours: int = 24, min_confidence: int = 65) -> list:
    from pfip.models.signals import SignalRow

    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    stmt = (
        select(SignalRow)
        .where(
            SignalRow.generated_at >= since,
            SignalRow.confidence >= min_confidence,
        )
        .order_by(desc(SignalRow.generated_at))
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def _latest_close(session, symbol: str) -> Decimal | None:
    try:
        from pfip.models.ohlcv import OHLCVRow
    except Exception:
        return None
    stmt = (
        select(OHLCVRow.close)
        .where(OHLCVRow.symbol == symbol)
        .order_by(desc(OHLCVRow.time))
        .limit(1)
    )
    res = await session.execute(stmt)
    val = res.scalars().first()
    return None if val is None else Decimal(str(val))


async def reconcile_daily(
    session, *, hours: int = 24, min_confidence: int = 65
) -> ReconcileSummary:
    """Run the daily reconcile pass and return a summary."""
    rows = await _fetch_recent_signals(session, hours=hours, min_confidence=min_confidence)
    portfolio = ShadowPortfolio(session=session)

    accepted = 0
    rejected = 0
    skipped = 0
    decisions: list[dict] = []

    for row in rows:
        price = await _latest_close(session, row.asset)
        if price is None:
            skipped += 1
            decisions.append({"asset": row.asset, "result": "skip-no-price"})
            continue
        try:
            sig = _row_to_signal(row)
            decision = await portfolio.apply_signal(sig, price)
        except Exception as exc:  # pragma: no cover
            log.warning("apply_signal failed for %s: %s", row.asset, exc)
            rejected += 1
            decisions.append({"asset": row.asset, "result": f"error:{exc}"})
            continue
        if decision.accepted:
            accepted += 1
            decisions.append(
                {
                    "asset": row.asset,
                    "result": "accepted",
                    "reason": decision.reason,
                    "holding_id": decision.holding_id,
                }
            )
        else:
            rejected += 1
            decisions.append(
                {"asset": row.asset, "result": "rejected", "reason": decision.reason}
            )

    mtm = await portfolio.mark_to_market()
    return ReconcileSummary(
        accepted=accepted,
        rejected=rejected,
        skipped_no_price=skipped,
        equity_inr=float(mtm.get("equity_inr", 0.0)),
        decisions=decisions,
    )
