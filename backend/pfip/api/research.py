"""Deep company-research endpoint (Phase 6).

``POST /research`` — resolve a company name → ticker, gather the diligence
aggregate + price + news, and return an LLM-synthesised decision-support dossier.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from pfip.api.deps import CurrentUser, DbSession

router = APIRouter(prefix="/research", tags=["research"])


class ResearchRequest(BaseModel):
    query: str


@router.post("")
async def research(body: ResearchRequest, db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Build a research dossier for a company name or ticker (a few seconds; 2 LLM calls)."""
    q = (body.query or "").strip()
    if not q:
        return {"error": "empty_query", "dossier_markdown": "Enter a company name or ticker."}
    from pfip.research.agent import build_research_dossier

    return await build_research_dossier(db, q)
