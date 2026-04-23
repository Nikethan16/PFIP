"""Prompt-injection defenses per plan Section 5.5.

Every chunk of *retrieved* content (KB, news, RSS feeds, user-ingested text)
is assumed to be potentially adversarial. Before it ever reaches an LLM prompt
it is:

1. Scanned for instruction-like patterns common in prompt injection attempts.
2. Stripped of code-fence / heredoc markers that could break out of the
   data block.
3. Wrapped in an unambiguous ``<retrieved_content>`` delimiter the system
   prompt tells the LLM to treat as untrusted data, never instructions.

If a strong injection signature is detected the content is quarantined —
``sanitize_retrieved_content`` returns a short placeholder and ``was_flagged``
is ``True`` so the caller can log a ``model_events`` row.

The regex list is a layered defense, not a silver bullet: the only real
protection is (a) the delimiter contract with the LLM, (b) Pydantic-validated
typed outputs, and (c) the regex guard in ``agent.graph.cite_and_validate``
that rejects any attempt by the LLM to emit a typed ``Signal`` object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Injection signatures (ordered by severity) ---------------------------
# Each pattern is case-insensitive.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Classic "ignore previous instructions" family.
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all\s+previous|your\s+instructions?)", re.IGNORECASE),
    # Role / persona injection.
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(an?\s+)?(different|new|unfiltered)", re.IGNORECASE),
    re.compile(r"\bpretend\s+to\s+be\b", re.IGNORECASE),
    re.compile(r"\broleplay\s+as\b", re.IGNORECASE),
    re.compile(r"\bnew\s+persona\b", re.IGNORECASE),
    re.compile(r"\bDAN\b", re.IGNORECASE),  # "Do Anything Now"
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    # Fake system / role tags the LLM might follow.
    re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*assistant\s*>", re.IGNORECASE),
    re.compile(r"<\s*/?\s*user\s*>", re.IGNORECASE),
    re.compile(r"^\s*system\s*:\s*", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*assistant\s*:\s*", re.IGNORECASE | re.MULTILINE),
    # Direct instruction tokens.
    re.compile(r"\breveal\s+(your\s+)?(system\s+prompt|instructions?|rules?)", re.IGNORECASE),
    re.compile(r"\bprint\s+your\s+(system\s+prompt|rules|instructions?)", re.IGNORECASE),
    re.compile(r"\boutput\s+the\s+above\b", re.IGNORECASE),
    re.compile(r"\bexecute\s+the\s+following\b", re.IGNORECASE),
    # Forbidden output coercion: typed-signal attempts.
    re.compile(r"\bemit\s+a?\s*signal\b", re.IGNORECASE),
    re.compile(r"\b(direction\s*[:=]\s*(BUY|SELL))\b", re.IGNORECASE),
]

# Tokens that might let attacker escape a code-fenced data block.
_FENCE_PATTERN = re.compile(r"```")
_HEREDOC_PATTERN = re.compile(r"<<\s*['\"]?([A-Z_]+)['\"]?", re.IGNORECASE)

# Delimiter the system prompt references. Kept as one symbol so the
# LLM side and the Python side never drift.
RETRIEVED_OPEN = "<retrieved_content>"
RETRIEVED_CLOSE = "</retrieved_content>"

_QUARANTINE_PLACEHOLDER = (
    "[content redacted — prompt-injection signature detected; this chunk was "
    "not passed to the model]"
)


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """Output of :func:`sanitize_retrieved_content`."""

    text: str
    """Sanitized, delimiter-wrapped text safe for prompt insertion."""

    was_flagged: bool
    """True if a strong injection signature was found; caller should log."""

    matched_patterns: tuple[str, ...]
    """Regex pattern strings that matched (for observability)."""


def _strip_fences(text: str) -> str:
    """Replace ```` ``` ```` fences and heredoc markers with safe equivalents."""
    text = _FENCE_PATTERN.sub("\u2032\u2032\u2032", text)  # visually similar to ``` but inert
    text = _HEREDOC_PATTERN.sub(r"<<_SAFE_\1_", text)
    return text


def _scan(text: str) -> list[str]:
    """Return pattern strings that matched in ``text``."""
    return [p.pattern for p in _INJECTION_PATTERNS if p.search(text)]


def sanitize_retrieved_content(text: str, *, source: str | None = None) -> SanitizationResult:
    """Sanitize externally-ingested ``text`` before inserting into a prompt.

    Args:
        text: Raw text pulled from KB / news / RSS / social.
        source: Optional source identifier — used only in the debug wrapper
            so the LLM can tell chunks apart but cannot be steered by them.

    Returns:
        A :class:`SanitizationResult`. If it is flagged, ``text`` will be a
        short placeholder rather than the original content. Callers should
        write a ``model_events`` row so the quarantine is auditable.
    """
    if not text:
        return SanitizationResult(
            text=f"{RETRIEVED_OPEN}\n{RETRIEVED_CLOSE}",
            was_flagged=False,
            matched_patterns=(),
        )

    matched = _scan(text)
    if matched:
        # Strong signal → quarantine the content but keep the envelope
        # so downstream code doesn't have to special-case None.
        body = _QUARANTINE_PLACEHOLDER
        if source:
            body = f"{body} (source={source})"
        return SanitizationResult(
            text=f"{RETRIEVED_OPEN}\n{body}\n{RETRIEVED_CLOSE}",
            was_flagged=True,
            matched_patterns=tuple(matched),
        )

    # Light sanitization even for clean content: neutralize fences/heredocs
    # and strip our own delimiters if they appear in the source.
    cleaned = text.replace(RETRIEVED_OPEN, "[open]").replace(RETRIEVED_CLOSE, "[close]")
    cleaned = _strip_fences(cleaned)
    header = f"source={source}\n" if source else ""
    wrapped = f"{RETRIEVED_OPEN}\n{header}{cleaned}\n{RETRIEVED_CLOSE}"
    return SanitizationResult(text=wrapped, was_flagged=False, matched_patterns=())


def sanitize_many(chunks: list[tuple[str, str | None]]) -> tuple[str, list[str]]:
    """Sanitize and concatenate multiple ``(text, source)`` chunks.

    Returns the joined safe block plus a list of matched-pattern strings
    across all flagged chunks (for quarantine logging).
    """
    out: list[str] = []
    flagged: list[str] = []
    for text, source in chunks:
        result = sanitize_retrieved_content(text, source=source)
        out.append(result.text)
        if result.was_flagged:
            flagged.extend(result.matched_patterns)
    return "\n\n".join(out), flagged


__all__ = [
    "RETRIEVED_CLOSE",
    "RETRIEVED_OPEN",
    "SanitizationResult",
    "sanitize_many",
    "sanitize_retrieved_content",
]
