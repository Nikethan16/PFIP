"""Fundamentals screener API.

``POST /screener/run`` filters the stored-fundamentals universe by numeric
criteria (e.g. ROCE > 20 AND P/E < 25 AND D/E < 0.5). ``GET /screener/fields``
lists the fields + operators the UI can build a query from.

Screens are stateless here — the frontend persists saved screens locally.
Server-side saved screens are a logged follow-up (needs a table + migration).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from pfip.api.deps import CurrentUser, DbSession
from pfip.diligence.peers import load_key_metrics
from pfip.research.screener import (
    FIELD_LABELS,
    Criterion,
    ScreenResult,
    apply_screen,
    validate_criteria,
)

router = APIRouter(prefix="/screener", tags=["screener"])


class FieldInfo(BaseModel):
    key: str
    label: str


class FieldsResponse(BaseModel):
    fields: list[FieldInfo]
    operators: list[str]


class RunRequest(BaseModel):
    criteria: list[Criterion]


@router.get("/fields", response_model=FieldsResponse)
async def fields(_user: CurrentUser) -> FieldsResponse:
    """Fields + operators available for building a screen."""
    return FieldsResponse(
        fields=[FieldInfo(key=k, label=v) for k, v in FIELD_LABELS.items()],
        operators=["gt", "gte", "lt", "lte", "eq"],
    )


@router.post("/run", response_model=ScreenResult)
async def run(body: RunRequest, db: DbSession, _user: CurrentUser) -> ScreenResult:
    """Run a screen over every symbol that has stored fundamentals."""
    errors = validate_criteria(body.criteria)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=" ".join(errors)
        )

    symbols = await _universe_symbols(db)
    metrics_by_symbol = await load_key_metrics(db, symbols)
    return apply_screen(metrics_by_symbol, body.criteria)


async def _universe_symbols(db: DbSession) -> list[str]:
    """Distinct symbols present in the fundamentals table. Best-effort."""
    try:
        rows = (await db.execute(text("SELECT DISTINCT symbol FROM fundamentals"))).all()
    except Exception:  # noqa: BLE001
        return []
    return [r[0] for r in rows if r[0]]
