"""Prompt-injection guard with quarantine queue.

This is the **pre-embed** stage: every chunk of news / social / RSS / book
content is run through :func:`sanitize_for_embed` *before* it enters Qdrant.
If it trips any injection signature, the chunk is dropped into the local
quarantine directory (``pfip/agent/quarantine/``) for human review and is
NOT inserted into the vector store.

This is distinct from ``pfip.agent.sanitizer.sanitize_retrieved_content``,
which is the **pre-prompt** stage applied to already-stored content as it's
being injected into the LLM message. Both layers must hold: a hostile chunk
that slips past the embed stage still gets caught at the prompt-injection
stage before the model sees it.

Rules
-----
- Strict delimiters: retrieved content is wrapped in ``<retrieved>...</retrieved>``
  tags. The system prompt tells the model to treat anything inside as data
  and refuse to follow instructions there.
- High regex-hit count (≥ 2 patterns matched) → quarantine. We choose 2 to
  keep noise low; a single phrase like "you are now" can appear in benign
  news articles, but two distinct signatures together is a strong signal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Reuse the regex list from the existing sanitizer module rather than
# duplicating it — keeps the two stages consistent.
from pfip.agent.sanitizer import (
    RETRIEVED_CLOSE,
    RETRIEVED_OPEN,
    _INJECTION_PATTERNS,  # type: ignore[attr-defined]
    sanitize_retrieved_content,
)

# Quarantine directory — created lazily on first quarantine.
_QUARANTINE_DIR = Path(__file__).parent / "quarantine"

# Threshold: how many distinct injection signatures before we quarantine.
QUARANTINE_THRESHOLD = 2


# Additional patterns specific to pre-embed (these are slower but precise).
_EXTRA_PATTERNS: list[re.Pattern[str]] = [
    # Markdown-link override attempts.
    re.compile(r"\[click here\]\(javascript:", re.IGNORECASE),
    # Hidden HTML.
    re.compile(r"<!--\s*system\s*:", re.IGNORECASE),
    # Multi-language "ignore" attempts.
    re.compile(r"无视|忽略.*指令", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SanitizeForEmbedResult:
    """Result of pre-embed sanitization."""

    text: str
    """Sanitized text safe to embed. Empty string if quarantined."""

    quarantined: bool
    """True if the chunk was diverted to the quarantine queue."""

    matched_patterns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _scan_all(text: str) -> list[str]:
    """Return all matching pattern strings across both lexicons."""
    hits: list[str] = []
    for p in _INJECTION_PATTERNS:
        if p.search(text):
            hits.append(p.pattern)
    for p in _EXTRA_PATTERNS:
        if p.search(text):
            hits.append(p.pattern)
    return hits


def quarantine_chunk(text: str, source: str | None, matched: list[str]) -> Path:
    """Write a flagged chunk to the quarantine queue.

    Returns the path of the quarantine file (for logging / Slack alerts).
    The file format is JSON: ``{ts, source, matched, text}``.
    """
    _QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    safe_source = re.sub(r"[^a-zA-Z0-9._-]", "_", source or "unknown")[:64]
    path = _QUARANTINE_DIR / f"{ts}_{safe_source}.json"
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "source": source,
        "matched_patterns": matched,
        "text": text,
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.warning(f"prompt_injection quarantined source={source} path={path.name} matched={matched[:3]}")
    except OSError as exc:  # pragma: no cover
        logger.error(f"quarantine write failed: {exc}")
    return path


def sanitize_for_embed(text: str, *, source: str | None = None) -> SanitizeForEmbedResult:
    """Sanitize a content chunk before it enters Qdrant.

    - If ≥ ``QUARANTINE_THRESHOLD`` distinct injection patterns match,
      write the chunk to the quarantine directory and return an empty
      sanitized text (caller should skip the embed).
    - Otherwise return a lightly-cleaned version: strip our own delimiter
      tags if they appear, collapse runaway whitespace.
    """
    if not text or not text.strip():
        return SanitizeForEmbedResult(text="", quarantined=False, matched_patterns=[])
    matched = _scan_all(text)
    if len(matched) >= QUARANTINE_THRESHOLD:
        quarantine_chunk(text, source, matched)
        return SanitizeForEmbedResult(text="", quarantined=True, matched_patterns=matched)
    # Light cleanup. Drop our own delimiters so attackers can't smuggle them in.
    cleaned = text.replace(RETRIEVED_OPEN, "[open]").replace(RETRIEVED_CLOSE, "[close]")
    cleaned = re.sub(r"\s+\n", "\n", cleaned)
    return SanitizeForEmbedResult(text=cleaned, quarantined=False, matched_patterns=matched)


def wrap_for_prompt(text: str, *, source: str | None = None) -> str:
    """Wrap a stored chunk in the canonical ``<retrieved>...</retrieved>`` tag.

    This is the cheap pre-prompt stage that just labels the content. For
    aggressive scanning + quarantine equivalents at prompt time, use
    :func:`pfip.agent.sanitizer.sanitize_retrieved_content`.
    """
    result = sanitize_retrieved_content(text, source=source)
    return result.text


__all__ = [
    "QUARANTINE_THRESHOLD",
    "SanitizeForEmbedResult",
    "quarantine_chunk",
    "sanitize_for_embed",
    "wrap_for_prompt",
]
