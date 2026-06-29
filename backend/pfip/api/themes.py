"""Thematic insight API (Phase 4). Read-only theme → beneficiary discovery."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from pfip.api.deps import CurrentUser, DbSession
from pfip.themes.catalogue import list_themes
from pfip.themes.engine import score_theme

router = APIRouter(prefix="/themes", tags=["themes"])


@router.get("")
async def get_themes(_user: CurrentUser) -> dict[str, Any]:
    """List the curated themes (slug + label)."""
    return {"themes": [{"slug": t["slug"], "label": t["label"]} for t in list_themes()]}


@router.get("/{slug}")
async def get_theme_beneficiaries(
    slug: str,
    db: DbSession,
    _user: CurrentUser,
    days: int = Query(90, ge=7, le=365),
    top: int = Query(15, ge=1, le=50),
) -> dict[str, Any]:
    """Rank tracked companies by recent news exposure to the theme, with evidence."""
    result = await score_theme(db, slug, days=days, top=top)
    if result is None:
        raise HTTPException(status_code=404, detail=f"unknown theme: {slug}")
    return result
