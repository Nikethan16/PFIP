"""Agent/chat router — real SSE streaming backed by :mod:`pfip.agent.graph`.

Endpoints (plan Section 12.1 + CONTRACTS.md §7):

- ``POST /agent/chat``              → SSE: ``source``, ``token``, ``done``.
- ``GET  /agent/morning-brief``     → Markdown string.
- ``POST /agent/post-mortem``       → JSON with the draft + metadata.
- ``GET  /agent/weekly-review``     → JSON with markdown.
- ``GET  /agent/arxiv-digest``      → JSON with markdown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from pfip.agent.arxiv_digest import build_arxiv_digest
from pfip.agent.graph import run_agent_stream
from pfip.agent.morning_brief import build_morning_brief
from pfip.agent.orchestrator import run_orchestration
from pfip.agent.post_mortem import draft_post_mortem
from pfip.agent.tools import TOOL_SPECS
from pfip.agent.weekly_review import build_weekly_review
from pfip.api.deps import CurrentUser, DbSession

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Tool layer + NL orchestrator (E1/E2)
# ---------------------------------------------------------------------------


class ToolInfo(BaseModel):
    name: str
    description: str
    params: dict[str, str]


class OrchestrateRequest(BaseModel):
    message: str


class OrchestrateResponse(BaseModel):
    matched: bool
    tool: str | None = None
    args: dict[str, Any] = {}
    result: Any = None
    note: str | None = None


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(_user: CurrentUser) -> list[ToolInfo]:
    """The typed capability catalogue the orchestrator can call."""
    return [ToolInfo(**spec.as_dict()) for spec in TOOL_SPECS]


@router.post("/orchestrate", response_model=OrchestrateResponse)
async def orchestrate(
    body: OrchestrateRequest, db: DbSession, _user: CurrentUser
) -> OrchestrateResponse:
    """Route a natural-language request to a tool, run it, return the result."""
    out = await run_orchestration(db, body.message)
    return OrchestrateResponse(**out)


# ---------------------------------------------------------------------------
# POST /agent/chat
# ---------------------------------------------------------------------------


class ChatMessageIn(BaseModel):
    """One chat message as the client sends it."""

    role: str = Field(pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    """POST body for ``/agent/chat``.

    Accepts both the old single-message form (``{"message": "..."}``) and
    the richer multi-turn form (``{"messages": [...]}``). ``session_id`` is
    optional; callers that want conversation persistence should pass one.
    """

    message: str | None = None
    messages: list[ChatMessageIn] | None = None
    session_id: str | None = None


async def _chat_event_stream(
    db,  # noqa: ANN001 — DbSession type comes from FastAPI layer
    body: ChatRequest,
) -> AsyncIterator[dict[str, str]]:
    if body.messages:
        history = [m.model_dump() for m in body.messages[:-1]]
        user_query = body.messages[-1].content
    elif body.message:
        history = []
        user_query = body.message
    else:
        user_query = ""
        history = []
    if not user_query.strip():
        yield {
            "event": "done",
            "data": '{"error":"empty_query"}',
        }
        return
    async for ev in run_agent_stream(db, user_query=user_query, history=history):
        yield ev


@router.post("/chat")
async def chat(
    body: ChatRequest,
    db: DbSession,
    _user: CurrentUser,
) -> EventSourceResponse:
    """Stream tokens for the agent response.

    Events (per CONTRACTS.md §7):
      - ``source`` — one per retrieved doc, emitted before tokens begin.
      - ``token``  — streamed LLM deltas.
      - ``done``   — final frame with summary metadata.
    """
    return EventSourceResponse(_chat_event_stream(db, body))


# ---------------------------------------------------------------------------
# POST /agent/perspectives — multi-persona reasoning (Phase 5)
# ---------------------------------------------------------------------------

# Distinct analytical lenses, surfaced as *perspectives* (not a single verdict).
_PERSONAS: dict[str, str] = {
    "value": (
        "You are a value investor in the Buffett/Graham tradition. Assess the "
        "question through fundamentals, durable competitive advantage, margin of "
        "safety, and long-term ownership. Be concise (2-3 sentences). Advisory only."
    ),
    "macro": (
        "You are a global-macro strategist in the Druckenmiller tradition. Assess "
        "the question through rates, liquidity, the cycle/regime, currencies and "
        "positioning. Be concise (2-3 sentences). Advisory only."
    ),
    "risk": (
        "You are a risk manager. Assess the question purely through downside: what "
        "could go wrong, position sizing, correlation, and invalidation. Be concise "
        "(2-3 sentences). Advisory only."
    ),
}


class PerspectivesRequest(BaseModel):
    """Body for ``POST /agent/perspectives``."""

    question: str = Field(min_length=1)


@router.post("/perspectives")
async def perspectives(body: PerspectivesRequest, _user: CurrentUser) -> dict[str, Any]:
    """Answer one question through several expert lenses at once.

    Runs the value / macro / risk personas in parallel and returns each view as a
    distinct perspective (deliberately NOT a single merged verdict). Each is an
    independent LLM call via the router's chat path (cloud fallback applies).
    Degrades per-persona: a failed lens returns an error string, never a 500.
    """
    import asyncio

    from pfip.agent.llm_client import ChatMessage, get_llm_client
    from pfip.agent.router import Sensitivity, TaskType

    client = get_llm_client()

    async def _one(persona: str, system: str) -> dict[str, str]:
        try:
            view = await client.complete(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=body.question),
                ],
                task=TaskType.CHAT_PUBLIC,
                sensitivity=Sensitivity.PUBLIC,
                max_tokens=220,
                temperature=0.4,
            )
            return {"persona": persona, "view": view.strip()}
        except Exception as exc:  # noqa: BLE001 — one lens failing must not 500
            return {"persona": persona, "view": f"(unavailable: {type(exc).__name__})"}

    results = await asyncio.gather(*(_one(p, s) for p, s in _PERSONAS.items()))
    return {
        "question": body.question,
        "perspectives": list(results),
        "disclaimer": "Independent analytical lenses for your own judgement — not advice.",
    }


# ---------------------------------------------------------------------------
# GET /agent/morning-brief
# ---------------------------------------------------------------------------


@router.get("/morning-brief", response_class=PlainTextResponse)
async def morning_brief(
    db: DbSession,
    _user: CurrentUser,
    date_: date | None = Query(None, alias="date"),
) -> str:
    """Render the daily morning brief as Markdown."""
    target = datetime.combine(date_ or date.today(), datetime.min.time())
    return await build_morning_brief(db, target)


# ---------------------------------------------------------------------------
# POST /agent/post-mortem
# ---------------------------------------------------------------------------


class PostMortemRequest(BaseModel):
    """POST body for ``/agent/post-mortem``."""

    holding_id: UUID


class PostMortemResponse(BaseModel):
    """Response envelope for the post-mortem draft."""

    holding_id: UUID
    markdown: str
    used_llm: bool
    warnings: list[str]


@router.post("/post-mortem", response_model=PostMortemResponse)
async def post_mortem(
    body: PostMortemRequest,
    db: DbSession,
    _user: CurrentUser,
) -> PostMortemResponse:
    """Draft a post-mortem for ``holding_id``. The user confirms in UI."""
    try:
        draft = await draft_post_mortem(db, body.holding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PostMortemResponse(
        holding_id=draft.holding_id,
        markdown=draft.markdown,
        used_llm=draft.used_llm,
        warnings=draft.warnings,
    )


# ---------------------------------------------------------------------------
# GET /agent/weekly-review
# ---------------------------------------------------------------------------


class WeeklyReviewResponse(BaseModel):
    """Weekly review envelope."""

    week: str
    markdown: str
    used_llm: bool
    closed_count: int
    signal_count: int


@router.get("/weekly-review", response_model=WeeklyReviewResponse)
async def weekly_review(
    db: DbSession,
    _user: CurrentUser,
    week: str | None = Query(None, description="YYYY-WW"),
) -> WeeklyReviewResponse:
    """Build (but do NOT persist) the weekly review."""
    as_of = _week_to_datetime(week)
    review = await build_weekly_review(db, as_of=as_of)
    return WeeklyReviewResponse(
        week=review.week,
        markdown=review.markdown,
        used_llm=review.used_llm,
        closed_count=review.closed_count,
        signal_count=review.signal_count,
    )


# ---------------------------------------------------------------------------
# GET /agent/arxiv-digest
# ---------------------------------------------------------------------------


class ArxivDigestResponse(BaseModel):
    """arXiv digest envelope."""

    week: str
    markdown: str
    used_llm: bool
    papers_count: int


@router.get("/arxiv-digest", response_model=ArxivDigestResponse)
async def arxiv_digest(
    db: DbSession,
    _user: CurrentUser,
    week: str | None = Query(None, description="YYYY-WW"),
) -> ArxivDigestResponse:
    """Build the weekly arXiv digest."""
    as_of = _week_to_datetime(week)
    d = await build_arxiv_digest(db, as_of=as_of)
    return ArxivDigestResponse(
        week=d.week,
        markdown=d.markdown,
        used_llm=d.used_llm,
        papers_count=d.papers_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _week_to_datetime(week: str | None) -> datetime | None:
    """Parse ``'YYYY-WW'`` into a UTC datetime at Sunday of that week."""
    if not week:
        return None
    try:
        year_str, w_str = week.split("-W") if "-W" in week else week.split("-")
        year = int(year_str)
        w = int(w_str)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=f"bad week format: {week!r}") from exc
    # ISO week -> a reference datetime near the end of that week.
    return datetime.fromisocalendar(year, w, 7)


__all__: list[Any] = ["router"]
