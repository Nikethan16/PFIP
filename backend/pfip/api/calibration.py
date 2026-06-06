"""Calibration router — reads CalibrationReportRow for a trailing month."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter
from sqlalchemy import desc, select

from fastapi import Query

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.calibration_reports import CalibrationReportRow, ModelEventRow

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


@router.get("/history")
async def history(
    db: DbSession,
    _user: CurrentUser,
    limit: int = Query(180, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Per-model calibration history as a compact (brier, ece) time series.

    Groups ``calibration_reports`` by ``(model_name, model_version)`` and
    returns one entry per model with its points ordered oldest→newest (capped
    at ``limit`` most-recent rows overall before grouping). Each entry carries a
    ``suspended`` flag derived from the latest ``model_events`` row for that
    model (event_type containing "suspend" ⇒ suspended, "reinstate"/"resume"
    ⇒ active). Shapes to the frontend ``CalibrationHistorySchema``.
    """
    stmt = (
        select(CalibrationReportRow)
        .order_by(desc(CalibrationReportRow.created_at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    # Latest suspension state per model from model_events.
    ev_stmt = select(ModelEventRow).order_by(desc(ModelEventRow.at))
    ev_res = await db.execute(ev_stmt)
    suspended_by_model: dict[tuple[str, str], bool] = {}
    for ev in ev_res.scalars().all():
        key = (ev.model_name, ev.model_version)
        if key in suspended_by_model:
            continue  # only the most recent event wins
        et = (ev.event_type or "").lower()
        if "suspend" in et:
            suspended_by_model[key] = True
        elif "reinstate" in et or "resume" in et or "activate" in et:
            suspended_by_model[key] = False

    grouped: dict[tuple[str, str], list[CalibrationReportRow]] = {}
    order: list[tuple[str, str]] = []
    for r in rows:
        key = (r.model_name, r.model_version)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(r)

    out: list[dict[str, Any]] = []
    for key in order:
        model_name, model_version = key
        # rows came newest-first; emit points oldest→newest for charting.
        points = [
            {
                "evaluated_at": (
                    rr.created_at.isoformat() if rr.created_at else ""
                ),
                "brier": float(rr.brier),
                "ece": float(rr.ece),
            }
            for rr in reversed(grouped[key])
        ]
        out.append(
            {
                "model_name": model_name,
                "model_version": model_version,
                "points": points,
                "suspended": suspended_by_model.get(key, False),
            }
        )
    return out
