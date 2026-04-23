"""Trading journal: entries + post-mortem close."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.core.contracts import JournalEntry, JournalEntryCreate
from pfip.models.journal import JournalRow

router = APIRouter(prefix="/journal", tags=["journal"])


class CloseRequest(BaseModel):
    """Request body for closing a journal entry."""

    post_mortem: str


_REQUIRED_CHECKLIST_KEYS = (
    "regime_check",
    "risk_size_ok",
    "thesis_written",
    "exit_plan_defined",
)


@router.get("/entries", response_model=list[JournalEntry])
async def list_entries(db: DbSession, _user: CurrentUser) -> list[JournalEntry]:
    """List journal entries, newest first."""
    result = await db.execute(select(JournalRow).order_by(JournalRow.created_at.desc()))
    rows = result.scalars().all()
    return [JournalEntry.model_validate(r) for r in rows]


@router.post("/entries", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: JournalEntryCreate, db: DbSession, _user: CurrentUser
) -> JournalEntry:
    """Create a journal entry. Pre-trade checklist MUST contain all required keys."""
    missing = [k for k in _REQUIRED_CHECKLIST_KEYS if k not in body.pre_trade_checklist]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pre-trade checklist missing keys: {missing}",
        )
    if not all(body.pre_trade_checklist[k] for k in _REQUIRED_CHECKLIST_KEYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All required checklist items must be True before trade logging.",
        )
    row = JournalRow(
        symbol=body.symbol,
        direction=body.direction.value,
        thesis=body.thesis,
        pre_trade_checklist=body.pre_trade_checklist,
        notes=body.notes,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return JournalEntry.model_validate(row)


@router.post("/entries/{entry_id}/close", response_model=JournalEntry)
async def close_entry(
    entry_id: UUID, body: CloseRequest, db: DbSession, _user: CurrentUser
) -> JournalEntry:
    """Close a journal entry; requires a post-mortem."""
    if not body.post_mortem.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Post-mortem text is required to close a journal entry.",
        )
    row = await db.get(JournalRow, entry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    row.post_mortem = body.post_mortem
    row.closed_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(row)
    return JournalEntry.model_validate(row)
