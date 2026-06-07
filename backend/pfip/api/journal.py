"""Trading journal: entries + post-mortem close + failure-pattern aggregation.

The journal enforces the **Appendix B** 10-item pre-trade checklist at
``POST /journal/entries``: any of the ten boolean checks unticked → 422.
This is the architectural rule "no trade without a checklist" — it must
not be relaxable from the API surface.

On close (``POST /journal/entries/{id}/close``) a free-text post-mortem
is required. ``GET /journal/patterns`` aggregates closed entries' free
text into a "top-N failure patterns this month" view used by the journal
dashboard. The pattern key is a stemmed first-clause heuristic; replace
with a clustering pass once we have ≥50 closed entries.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
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


class FailurePattern(BaseModel):
    """One aggregated failure-pattern row."""

    pattern: str
    count: int
    examples: list[str]  # up to 3 example entry IDs


# Appendix B — all 10 must be True before the trade can be logged.
# Keep this list in lockstep with the UI in
# frontend/components/journal/pre-trade-checklist.tsx.
_REQUIRED_CHECKLIST_KEYS = (
    "regime_check",
    "risk_size_ok",
    "thesis_written",
    "exit_plan_defined",
    "invalidation_set",
    "correlation_check",
    "liquidity_check",
    "tax_impact_considered",
    "news_check",
    "regime_alignment",
)


@router.get("/entries", response_model=list[JournalEntry])
async def list_entries(db: DbSession, _user: CurrentUser) -> list[JournalEntry]:
    """List journal entries, newest first."""
    result = await db.execute(select(JournalRow).order_by(JournalRow.created_at.desc()))
    rows = result.scalars().all()
    return [JournalEntry.model_validate(r) for r in rows]


@router.post("/entries", response_model=JournalEntry, status_code=status.HTTP_201_CREATED)
async def create_entry(body: JournalEntryCreate, db: DbSession, _user: CurrentUser) -> JournalEntry:
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


class AutoDraftRequest(BaseModel):
    """Optional realized P&L for the close, supplied by the UI from
    portfolio analytics. If absent, the draft asks 'how was P&L?' in the
    template rather than pretending to know."""

    realized_pnl_pct: float | None = None
    extra_context: str | None = None  # free-form, e.g. "stopped out at -3%"


class AutoDraftResponse(BaseModel):
    draft_markdown: str
    used_llm: bool
    routed_to: str  # provider name for transparency


@router.post("/entries/{entry_id}/auto_draft_post_mortem", response_model=AutoDraftResponse)
async def auto_draft_post_mortem(
    entry_id: UUID,
    body: AutoDraftRequest,
    db: DbSession,
    _user: CurrentUser,
) -> AutoDraftResponse:
    """Generate a post-mortem draft from the original thesis + outcome.

    The draft is **never** committed automatically — the UI shows it in a
    dialog the user must edit/approve. Two reasons:

    1. The journal's value comes from honest self-reflection — accepting
       an LLM template uncritically defeats the point.
    2. The post-mortem text drives the failure-pattern aggregation; we
       don't want LLM phrasing to skew the clustering.

    Routes via :func:`pfip.agent.llm_client.get_llm_router` using the
    legacy ``generate()`` shim. The router internally chooses the
    sensitivity tier — for now the journal's thesis is treated as
    sensitive, but the shim defaults to PUBLIC routing; future work can
    switch to ``get_llm_client().complete(... CHAT_SENSITIVE, PERSONAL)``
    once the journal endpoint is hardened.
    """
    row = await db.get(JournalRow, entry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if row.closed_at is not None and row.post_mortem:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry already has a post-mortem — edit it directly.",
        )

    prompt = _build_post_mortem_prompt(
        symbol=row.symbol,
        direction=row.direction,
        thesis=row.thesis,
        checklist=dict(row.pre_trade_checklist or {}),
        notes=row.notes,
        realized_pnl_pct=body.realized_pnl_pct,
        extra_context=body.extra_context,
    )

    # Lazy import to keep the API module fast at boot.
    from pfip.agent.llm_client import LLMUnavailable, get_llm_router

    try:
        router_ = get_llm_router()
        draft = await router_.generate(
            prompt,
            system=_POST_MORTEM_SYSTEM,
        )
        return AutoDraftResponse(
            draft_markdown=draft.strip() or _fallback_template(row, body),
            used_llm=True,
            routed_to=router_.primary_model,
        )
    except LLMUnavailable:
        # Hard fallback — return the static template so the user can fill
        # it in offline. This is the same template the LLM is asked to
        # complete, so the resulting journal is structurally consistent.
        return AutoDraftResponse(
            draft_markdown=_fallback_template(row, body),
            used_llm=False,
            routed_to="static_template",
        )


_POST_MORTEM_SYSTEM = (
    "You help a trader reflect honestly on a closed position. "
    "Output is a markdown post-mortem in the exact section order: "
    "**Thesis result**, **What worked**, **What didn't**, **Pattern tag**, "
    "**Lesson for next time**. Be specific. Avoid platitudes. "
    "Do not predict the future. Do not give trading advice. "
    "If the outcome P&L isn't supplied, write '_TODO: enter P&L_' for "
    "that field rather than guessing."
)


def _build_post_mortem_prompt(
    *,
    symbol: str,
    direction: str,
    thesis: str,
    checklist: dict[str, bool],
    notes: str | None,
    realized_pnl_pct: float | None,
    extra_context: str | None,
) -> str:
    checklist_bullets = (
        "\n".join(f"- {k}: {'✓' if v else '✗'}" for k, v in sorted(checklist.items())) or "(none)"
    )
    pnl_line = (
        f"Realized P&L: **{realized_pnl_pct:+.2f}%**"
        if realized_pnl_pct is not None
        else "Realized P&L: _not supplied_"
    )
    extra_line = f"\nFree-form note from trader: {extra_context}" if extra_context else ""
    notes_line = f"\nOriginal entry notes: {notes}" if notes else ""

    return (
        f"Symbol: **{symbol}** ({direction})\n"
        f"{pnl_line}\n\n"
        f"Original thesis:\n> {thesis}\n\n"
        f"Pre-trade checklist:\n{checklist_bullets}"
        f"{notes_line}"
        f"{extra_line}\n\n"
        "Write the post-mortem in the five-section format. "
        "Pull a one-line 'Pattern tag' that could plausibly recur "
        "(e.g. 'stop too tight', 'thesis based on news, not price', "
        "'sized too large for conviction')."
    )


def _fallback_template(row: JournalRow, body: AutoDraftRequest) -> str:
    pnl = (
        f"{body.realized_pnl_pct:+.2f}%"
        if body.realized_pnl_pct is not None
        else "_TODO: enter P&L_"
    )
    return (
        f"# Post-mortem — {row.symbol} ({row.direction})\n\n"
        f"**Thesis result**: _TODO: was the thesis vindicated, partial, or wrong?_\n\n"
        f"**Realized P&L**: {pnl}\n\n"
        f"**What worked**: _TODO_\n\n"
        f"**What didn't**: _TODO_\n\n"
        f"**Pattern tag**: _TODO: one short label, e.g. 'stop too tight'_\n\n"
        f"**Lesson for next time**: _TODO_\n\n"
        f"_Original thesis:_ {row.thesis}\n"
    )


@router.get("/patterns", response_model=list[FailurePattern])
async def list_failure_patterns(
    db: DbSession,
    _user: CurrentUser,
    days: int = 30,
    top: int = 5,
) -> list[FailurePattern]:
    """Aggregate failure patterns from closed entries in the last `days` days.

    The pattern key is the first clause (up to 60 chars, terminator on
    `.`, `,`, `;`) of the lowercased post-mortem text. Cheap, but good
    enough for a "top-N this month" badge until volume justifies a real
    clustering pass.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max(1, days))
    stmt = (
        select(JournalRow)
        .where(JournalRow.closed_at.is_not(None))
        .where(JournalRow.closed_at >= cutoff)
        .where(JournalRow.post_mortem.is_not(None))
    )
    rows = (await db.execute(stmt)).scalars().all()

    pattern_counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for r in rows:
        if not r.post_mortem:
            continue
        raw = r.post_mortem.strip().lower()
        if not raw:
            continue
        # first clause = up to first sentence/clause terminator
        first = raw
        for sep in (".", ",", ";", "\n"):
            idx = first.find(sep)
            if idx != -1 and idx < 200:
                first = first[:idx]
        key = first.strip()[:60] or raw[:60]
        pattern_counter[key] += 1
        examples.setdefault(key, []).append(str(r.id))

    most = pattern_counter.most_common(top)
    return [FailurePattern(pattern=k, count=v, examples=examples[k][:3]) for k, v in most]
