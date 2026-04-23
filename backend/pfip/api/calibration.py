"""Calibration router — reads CalibrationReportRow for a trailing month."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import desc, select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.calibration_reports import CalibrationReportRow

router = APIRouter(prefix="/calibration", tags=["calibration"])


@router.get("/latest")
async def latest(db: DbSession, _user: CurrentUser) -> list[dict[str, Any]]:
    """Return every calibration report whose ``created_at`` is in the trailing month."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=31)
    stmt = (
        select(CalibrationReportRow)
        .where(CalibrationReportRow.created_at >= cutoff)
        .order_by(desc(CalibrationReportRow.created_at))
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [
        {
            "id": str(r.id),
            "model_name": r.model_name,
            "model_version": r.model_version,
            "market": r.market,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "brier": r.brier,
            "ece": r.ece,
            "sharpness": r.sharpness,
            "n_samples": r.n_samples,
            "reliability": r.reliability,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
