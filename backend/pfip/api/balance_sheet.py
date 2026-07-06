"""Balance-sheet insights API.

Upload a balance sheet (CSV or PDF) — or type the line items in — and get
deterministic ratios + an Altman Z-score, plus a grounded LLM narrative that
explains what the numbers mean. The math lives in
:mod:`pfip.research.balance_sheet` (pure, unit-tested); this router handles
extraction, the LLM narrative, and transport.

Endpoints
    POST /balance-sheet/analyze   JSON line items      → metrics + insight
    POST /balance-sheet/upload    multipart file (csv/pdf) → parsed + metrics + insight

The narrative is explicitly educational, cites only the computed numbers, and
carries a not-advice disclaimer. If the LLM is unavailable it degrades to a
deterministic summary built from the same numbers.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from pfip.api.deps import CurrentUser
from pfip.research.balance_sheet import (
    BalanceSheetInput,
    BalanceSheetMetrics,
    compute_metrics,
    parse_csv_bytes,
    parse_text,
)

router = APIRouter(prefix="/balance-sheet", tags=["balance-sheet"])

_MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB — plenty for a statement


class AnalyzeResponse(BaseModel):
    metrics: BalanceSheetMetrics
    insight_markdown: str
    used_llm: bool
    disclaimer: str = (
        "Educational analysis of the figures you supplied. Ratios are only as "
        "good as the inputs; this is not investment advice."
    )


class UploadResponse(AnalyzeResponse):
    parsed_fields: list[str]  # canonical fields we managed to extract


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(body: BalanceSheetInput, _user: CurrentUser) -> AnalyzeResponse:
    """Compute ratios + Altman Z from supplied line items, then narrate."""
    metrics = compute_metrics(body)
    insight, used_llm = await _narrate(metrics)
    return AnalyzeResponse(metrics=metrics, insight_markdown=insight, used_llm=used_llm)


@router.post("/upload", response_model=UploadResponse)
async def upload(
    _user: CurrentUser,
    file: UploadFile = File(...),
) -> UploadResponse:
    """Extract line items from an uploaded CSV/PDF, then analyze.

    Extraction is best-effort — the response echoes exactly which fields were
    found so the UI can let the user review/correct before trusting the ratios.
    """
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 8 MB).",
        )

    name = (file.filename or "").lower()
    if name.endswith(".csv") or (file.content_type or "").startswith("text/csv"):
        fields = parse_csv_bytes(raw)
    elif name.endswith(".pdf") or (file.content_type or "") == "application/pdf":
        fields = parse_text(_pdf_to_text(raw))
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Upload a CSV or PDF, or enter values manually.",
        )

    parsed = BalanceSheetInput(company=None, **fields)
    metrics = compute_metrics(parsed)
    insight, used_llm = await _narrate(metrics)
    return UploadResponse(
        metrics=metrics,
        insight_markdown=insight,
        used_llm=used_llm,
        parsed_fields=sorted(fields.keys()),
    )


def _pdf_to_text(data: bytes) -> str:
    """Extract text from a PDF's pages (best-effort; empty on failure)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 — malformed/scanned PDFs are expected
        return ""


# --- narrative --------------------------------------------------------------

_SYSTEM = (
    "You are a careful financial analyst explaining a company's balance sheet "
    "to a non-expert. You are given already-computed ratios and an Altman "
    "Z-score. Explain what they imply about liquidity, leverage, profitability "
    "and solvency in plain English. Cite ONLY the numbers provided — never "
    "invent figures. Be balanced (strengths and risks). Do not give buy/sell "
    "advice. 4-6 short paragraphs or bullets. End with one line on the biggest "
    "thing to watch."
)


def _facts_block(metrics: BalanceSheetMetrics) -> str:
    lines = [f"Company: {metrics.input.company or 'n/a'} ({metrics.input.currency})"]
    for r in metrics.ratios:
        if r.value is None:
            lines.append(f"- {r.label}: not computable ({r.interpretation})")
        else:
            lines.append(f"- {r.label}: {r.value:.2f} [{r.health}] — {r.interpretation}")
    z = metrics.altman_z
    if z.score is not None:
        lines.append(f"- Altman Z-score: {z.score:.2f} [{z.zone}] — {z.interpretation}")
    else:
        lines.append(f"- Altman Z-score: not computable — {z.interpretation}")
    if metrics.missing_fields:
        lines.append(f"- Missing inputs: {', '.join(metrics.missing_fields)}")
    return "\n".join(lines)


async def _narrate(metrics: BalanceSheetMetrics) -> tuple[str, bool]:
    """Return (markdown, used_llm). Falls back to a deterministic summary."""
    facts = _facts_block(metrics)
    prompt = (
        "Here are the computed metrics for a single balance sheet. Explain them "
        "for the owner of this analysis:\n\n" + facts
    )
    from pfip.agent.llm_client import LLMUnavailable, get_llm_router

    try:
        router_ = get_llm_router()
        text = await router_.generate(prompt, system=_SYSTEM)
        text = (text or "").strip()
        if text:
            return text, True
    except LLMUnavailable:
        pass
    except Exception:  # noqa: BLE001 — never fail the request on the narrative
        pass
    return _fallback_summary(metrics), False


def _fallback_summary(metrics: BalanceSheetMetrics) -> str:
    """Deterministic markdown when the LLM is unavailable."""
    parts = ["### Balance-sheet summary", "", "**Ratios**"]
    for r in metrics.ratios:
        val = f"{r.value:.2f}" if r.value is not None else "—"
        parts.append(f"- **{r.label}**: {val} ({r.health}) — {r.interpretation}")
    z = metrics.altman_z
    parts.append("")
    parts.append("**Solvency (Altman Z)**")
    if z.score is not None:
        parts.append(f"- Z = **{z.score:.2f}** → _{z.zone}_ zone. {z.interpretation}")
    else:
        parts.append(f"- {z.interpretation}")
    if metrics.missing_fields:
        parts.append("")
        parts.append(
            "_Add these line items for a fuller picture: "
            + ", ".join(metrics.missing_fields)
            + "._"
        )
    return "\n".join(parts)
