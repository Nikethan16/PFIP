"""Book → feature/rule translation layer.

When the KB has ingested a trading book (Wyckoff / Lefèvre / Graham /
Taleb / etc.) we want more than retrieval — we want the *rules* the
author advocates surfaced as machine-readable triggers we can show
alongside signals.

Output shape: ``ExtractedRule`` carrying:
- ``rule_text`` (verbatim or lightly normalized).
- ``preconditions`` (parsed structured form when possible; free-form otherwise).
- ``source`` (book title + chapter/page).
- ``confidence`` 0..1.

Two execution modes:

1. ``extract_rules_heuristic(text)`` — pattern matcher for sentences
   shaped like "If X then Y", "Never X", "When X, Y". Cheap; no LLM.
2. ``extract_rules_llm(text, llm)`` — sends the chunk to the LLM router
   with a strict prompt asking for JSON; falls back to the heuristic on
   bad output. Use this when the router has a cloud key configured.

Output is written to a small `extracted_rules` JSONL file under
``data/kb_rules/<book>.jsonl`` by the optional Prefect ingest step.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(slots=True)
class ExtractedRule:
    rule_text: str
    preconditions: list[str] = field(default_factory=list)
    source: str | None = None
    confidence: float = 0.5  # 0..1
    method: str = "heuristic"  # 'heuristic' | 'llm'


# Pattern catalogue. Each pattern has a regex + a confidence weight
# representing how rule-shaped that grammar is.
_PATTERNS: list[tuple[re.Pattern[str], float]] = [
    (
        re.compile(
            r"^\s*(?:if|when|whenever)\s+([^,.;]{8,160}),?\s+(?:then\s+)?([^.]{8,200})\.",
            re.IGNORECASE,
        ),
        0.85,
    ),
    (re.compile(r"^\s*never\s+([^.;]{8,180})\.", re.IGNORECASE), 0.80),
    (re.compile(r"^\s*always\s+([^.;]{8,180})\.", re.IGNORECASE), 0.80),
    (re.compile(r"^\s*do not\s+([^.;]{8,180})\.", re.IGNORECASE), 0.75),
    (
        re.compile(
            r"^\s*(?:cut|exit|sell)\s+(?:your\s+)?(?:losses?|position)s?\s+(?:when|if)\s+([^.;]{8,180})\.",
            re.IGNORECASE,
        ),
        0.85,
    ),
]


def _split_sentences(text: str) -> list[str]:
    """Light sentence splitter — period/exclam/question followed by space + cap."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def extract_rules_heuristic(text: str, *, source: str | None = None) -> list[ExtractedRule]:
    """Pattern-based rule extraction. No LLM required."""
    out: list[ExtractedRule] = []
    for sent in _split_sentences(text):
        for pat, conf in _PATTERNS:
            m = pat.search(sent)
            if not m:
                continue
            groups = [g.strip() for g in m.groups() if g]
            preconditions = groups[:-1] if len(groups) > 1 else []
            out.append(
                ExtractedRule(
                    rule_text=sent.strip(),
                    preconditions=preconditions,
                    source=source,
                    confidence=conf,
                    method="heuristic",
                )
            )
            break  # one rule per sentence
    return out


_LLM_PROMPT = """\
You are extracting trading rules from a book passage. Output ONLY a JSON
array of objects with these keys: rule_text (verbatim sentence), preconditions
(list of strings; conditions that trigger the rule), confidence (0..1).

If the passage does NOT contain rule-shaped guidance, output []. Do not
invent rules. Do not paraphrase advice into rules — only extract sentences
that are themselves clear directives.

Passage:
\"\"\"
{passage}
\"\"\"

JSON:"""


async def extract_rules_llm(
    text: str,
    llm: object,
    *,
    source: str | None = None,
    max_chars: int = 6000,
) -> list[ExtractedRule]:
    """LLM-based extraction. `llm` should have an async `generate(prompt)`.

    On any failure (network, malformed JSON, missing method) we fall
    back to the heuristic so the caller always gets a result list.
    """
    if not text or not text.strip():
        return []
    passage = text[:max_chars]
    prompt = _LLM_PROMPT.format(passage=passage)
    try:
        raw = await llm.generate(prompt)  # type: ignore[attr-defined]
    except Exception:
        return extract_rules_heuristic(text, source=source)
    if not raw:
        return extract_rules_heuristic(text, source=source)
    # Parse the JSON array; tolerate ```json fences.
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except Exception:
        return extract_rules_heuristic(text, source=source)
    if not isinstance(parsed, list):
        return extract_rules_heuristic(text, source=source)
    out: list[ExtractedRule] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        rule_text = str(item.get("rule_text", "")).strip()
        if not rule_text:
            continue
        out.append(
            ExtractedRule(
                rule_text=rule_text,
                preconditions=[str(p) for p in (item.get("preconditions") or [])],
                source=source,
                confidence=float(item.get("confidence") or 0.6),
                method="llm",
            )
        )
    if not out:
        return extract_rules_heuristic(text, source=source)
    return out


def rules_to_jsonl(rules: Iterable[ExtractedRule]) -> str:
    """Serialize for `data/kb_rules/<book>.jsonl`."""
    lines = []
    for r in rules:
        lines.append(
            json.dumps(
                {
                    "rule_text": r.rule_text,
                    "preconditions": r.preconditions,
                    "source": r.source,
                    "confidence": r.confidence,
                    "method": r.method,
                }
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")


__all__ = [
    "ExtractedRule",
    "extract_rules_heuristic",
    "extract_rules_llm",
    "rules_to_jsonl",
]
