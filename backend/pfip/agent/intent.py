"""Intent classification for the chat agent.

A v1 heuristic classifier that decides *how* to route a user prompt
without needing an LLM call. Three buckets:

- ``DB_QUERY`` — the user is asking for a specific number from the
  database. E.g. "how much BTC do I hold?", "what was my P&L yesterday?",
  "show my open positions". Answered by tool-calling the DB.
- ``RAG_LOOKUP`` — the user is asking what a book/concept says or what
  the news has been around X. E.g. "what does Wyckoff say about
  accumulation?", "what's the news on RELIANCE today?". Answered by
  retrieval + grounded LLM.
- ``REASONING`` — the user wants the agent to reason / synthesize /
  explain across the above. E.g. "is now a good time to add to ETH?",
  "explain why your last signal fired". Routed to the full agent graph.

The classifier is a transparent pattern-matcher: the rules below should
be readable by Suresh in 30 seconds and easy to extend. We deliberately
do *not* use an LLM for intent classification because (a) latency adds
up on every turn, (b) misclassification is silent, (c) the rules are
short and the signal is strong.

If multiple buckets match we use a fixed priority:
DB_QUERY > RAG_LOOKUP > REASONING.

The classifier returns a confidence in [0, 1] and the matched rule's
trigger, so the agent can fall back to REASONING when confidence is low.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    DB_QUERY = "db_query"
    RAG_LOOKUP = "rag_lookup"
    REASONING = "reasoning"


@dataclass(slots=True, frozen=True)
class IntentDecision:
    """Classifier output."""

    intent: Intent
    confidence: float
    trigger: str  # human-readable reason


# Patterns are ordered by specificity within each bucket. First match wins.
# Each tuple = (regex, weight 0-1). Final confidence is the max weight that matched.
_DB_QUERY_PATTERNS: list[tuple[str, float]] = [
    (r"\bhow (much|many) .* (do i (have|hold|own)|in my (portfolio|holdings|wallet))\b", 0.95),
    (r"\bshow (my|me)( me| my)? (open|current|all)? ?(positions|holdings|trades)\b", 0.95),
    (r"\bwhat (was|is) my .*(p\s?&\s?l|pnl|return|drawdown|exposure)\b", 0.90),
    (r"\blist (my|all) (positions|holdings|signals|trades|journal entries)\b", 0.90),
    (r"\bcurrent (price|close|nav|holdings) (of|for)\b", 0.85),
    (r"\bbalance (of|for) (my )?\b", 0.80),
    (r"\b(stcg|ltcg|vda|capital gain|tax (liability|payable|owed)) (for|in) (fy|2[0-9]{3})\b", 0.85),
]

_RAG_LOOKUP_PATTERNS: list[tuple[str, float]] = [
    (r"\bwhat does (wyckoff|graham|lefe?vre|taleb|dalio|tharp|ammous|lopez de prado)\b", 0.95),
    (r"\b(define|explain|what is|what's) (an? )?(.*)(regime|accumulation|distribution|drawdown|sharpe|sortino|calmar)\b", 0.85),
    (r"\b(what'?s|whats|any|recent|latest) (the )?news (on|about|for)\b", 0.90),
    (r"\bsummariz?e .* (article|paper|news|filing)\b", 0.85),
    (r"\bcite (a|the) (source|reference)\b", 0.90),
]

_REASONING_PATTERNS: list[tuple[str, float]] = [
    (r"\b(should i|do you think i should|is it a good time to) (buy|sell|hold|add|trim|exit)\b", 0.95),
    (r"\bwhy (did|does|is|are) .* (gap|spike|crash|fire|signal|recommend)\b", 0.90),
    (r"\b(walk me through|explain) (your|the) (last |latest )?(signal|recommendation|reasoning|analysis)\b", 0.90),
    (r"\b(compare|stack up|benchmark) .* (vs|versus|against)\b", 0.85),
    (r"\bif .* (then|would|happen)\b", 0.75),
]


def _best_match(text: str, patterns: list[tuple[str, float]]) -> tuple[float, str] | None:
    best: tuple[float, str] | None = None
    for pat, w in patterns:
        if re.search(pat, text, re.IGNORECASE):
            if best is None or w > best[0]:
                best = (w, pat)
    return best


def classify_intent(text: str) -> IntentDecision:
    """Run the heuristic classifier.

    Returns the highest-confidence match across the three buckets, with
    the priority DB_QUERY > RAG_LOOKUP > REASONING when buckets tie.

    For empty or one-word inputs we return REASONING with low confidence
    so the agent's full graph handles the ambiguity.
    """
    t = (text or "").strip()
    if len(t.split()) < 2:
        return IntentDecision(
            intent=Intent.REASONING,
            confidence=0.1,
            trigger="too_short",
        )

    db = _best_match(t, _DB_QUERY_PATTERNS)
    rag = _best_match(t, _RAG_LOOKUP_PATTERNS)
    reasoning = _best_match(t, _REASONING_PATTERNS)

    # Priority order on ties: DB > RAG > REASONING.
    candidates = []
    if db is not None:
        candidates.append((Intent.DB_QUERY, db[0], db[1]))
    if rag is not None:
        candidates.append((Intent.RAG_LOOKUP, rag[0], rag[1]))
    if reasoning is not None:
        candidates.append((Intent.REASONING, reasoning[0], reasoning[1]))

    if not candidates:
        return IntentDecision(
            intent=Intent.REASONING,
            confidence=0.3,
            trigger="no_pattern_matched",
        )

    # Sort by (weight desc, priority asc). Priority is intrinsic to enum order.
    priority = {Intent.DB_QUERY: 0, Intent.RAG_LOOKUP: 1, Intent.REASONING: 2}
    candidates.sort(key=lambda c: (-c[1], priority[c[0]]))
    intent, w, trigger = candidates[0]
    return IntentDecision(intent=intent, confidence=w, trigger=trigger)


__all__ = ["Intent", "IntentDecision", "classify_intent"]
