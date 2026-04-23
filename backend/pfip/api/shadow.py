"""Shadow portfolio routes — paper-trading mirror, backed by the shadow engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import Holding
from pfip.models.shadow import ShadowHoldingRow
from pfip.shadow.engine import ShadowPortfolio

router = APIRouter(prefix="/shadow", tags=["shadow"])


@router.get("/holdings", response_model=list[Holding])
async def list_shadow_holdings(db: DbSession, _user: CurrentUser) -> list[Holding]:
    """List paper-trading holdings (open and closed)."""
    result = await db.execute(
        select(ShadowHoldingRow).order_by(ShadowHoldingRow.acquired_at.desc())
    )
    rows = result.scalars().all()
    return [Holding.model_validate(r) for r in rows]


@router.get("/vs-actual")
async def vs_actual(db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Diff shadow vs actual holdings (symbol sets + estimated value)."""
    portfolio = ShadowPortfolio(session=db)
    return await portfolio.vs_actual()
