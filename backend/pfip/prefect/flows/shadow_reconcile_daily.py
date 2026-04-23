"""Prefect flow: daily shadow-portfolio reconciliation.

Runs daily (23:30 IST / 18:00 UTC). Reads signals generated today above the
confidence floor and feeds each into the shadow engine.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from prefect import flow, get_run_logger, task
from sqlalchemy import desc, select

from pfip.core.contracts import Driver, Regime, Signal, SignalDirection
from pfip.db.session import get_sessionmaker
from pfip.models.ohlcv import OHLCVRow
from pfip.models.signals import SignalRow
from pfip.shadow.engine import ShadowPortfolio


def _row_to_signal(row: SignalRow) -> Signal:
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


@task(name="fetch-today-signals")
async def _fetch_today_signals() -> list[SignalRow]:
    since = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(SignalRow)
            .where(SignalRow.generated_at >= since)
            .order_by(desc(SignalRow.generated_at))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


@task(name="latest-close")
async def _latest_close(symbol: str) -> Decimal | None:
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(OHLCVRow.close)
            .where(OHLCVRow.symbol == symbol)
            .order_by(desc(OHLCVRow.time))
            .limit(1)
        )
        res = await session.execute(stmt)
        val = res.scalars().first()
    return None if val is None else Decimal(str(val))


@flow(name="shadow-reconcile-daily", log_prints=True)
async def shadow_reconcile_daily_flow() -> dict[str, int]:
    """Apply today's signals to the shadow portfolio + emit MtM summary."""
    log = get_run_logger()
    signal_rows = await _fetch_today_signals()
    if not signal_rows:
        log.info("shadow: no signals in the last 24h")

    accepted = 0
    rejected = 0
    factory = get_sessionmaker()
    async with factory() as session:
        portfolio = ShadowPortfolio(session=session)
        for row in signal_rows:
            price = await _latest_close(row.asset)
            if price is None:
                rejected += 1
                continue
            sig = _row_to_signal(row)
            try:
                decision = await portfolio.apply_signal(sig, price)
            except Exception as exc:  # pragma: no cover
                log.warning(f"shadow apply failed for {row.asset}: {exc}")
                rejected += 1
                continue
            if decision.accepted:
                accepted += 1
                log.info(f"shadow: {row.asset} accepted ({decision.reason})")
            else:
                rejected += 1
                log.info(f"shadow: {row.asset} rejected ({decision.reason})")

        mtm = await portfolio.mark_to_market()
        log.info(f"shadow MtM equity: {mtm['equity_inr']}")

    return {"accepted": accepted, "rejected": rejected}


if __name__ == "__main__":
    asyncio.run(shadow_reconcile_daily_flow())
