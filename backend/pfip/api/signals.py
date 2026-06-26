"""Signals router — reads persisted signals from the Stage-4 ML layer."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from pfip.api.deps import CurrentUser, DbSession, SettingsDep
from pfip.core.contracts import Driver, Regime, Signal, SignalDirection
from pfip.models.signals import SignalRow

router = APIRouter(prefix="/signals", tags=["signals"])


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


@router.get("", response_model=list[Signal])
async def list_signals(
    db: DbSession,
    _user: CurrentUser,
    settings: SettingsDep,
    asset: str | None = Query(None),
    since: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[Signal]:
    """List signals filtered by asset/since, newest first.

    Returns ``[]`` when ``FEATURE_ML_SIGNALS`` is off — the directional model
    has no demonstrated out-of-sample edge (see docs/SIGNAL_BACKTEST_2026-06-26),
    so signals are gated until that changes rather than shown stale/misleading.
    """
    if not settings.feature_ml_signals:
        return []
    stmt = select(SignalRow).order_by(desc(SignalRow.generated_at)).limit(limit)
    if asset is not None:
        stmt = stmt.where(SignalRow.asset == asset)
    if since is not None:
        stmt = stmt.where(SignalRow.generated_at >= since)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_signal(r) for r in rows]


@router.get("/latest", response_model=list[Signal])
async def latest_signals(db: DbSession, _user: CurrentUser, settings: SettingsDep) -> list[Signal]:
    """Return the most-recent signal per asset (``[]`` when signals are gated off)."""
    if not settings.feature_ml_signals:
        return []
    # Sub-select: for each asset, find max(generated_at). Then self-join.
    max_by_asset = (
        select(SignalRow.asset, func.max(SignalRow.generated_at).label("g"))
        .group_by(SignalRow.asset)
        .subquery()
    )
    stmt = select(SignalRow).join(
        max_by_asset,
        (SignalRow.asset == max_by_asset.c.asset) & (SignalRow.generated_at == max_by_asset.c.g),
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_signal(r) for r in rows]
