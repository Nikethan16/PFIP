"""Lightweight NL orchestrator (E2).

Maps a natural-language request to one of the registered tools
(:mod:`pfip.agent.tools`), extracts the arguments it can, runs the tool, and
returns a structured result. Selection is **deterministic-first** (regex /
keywords) so it works reliably regardless of the LLM's function-calling
support; an LLM can later refine selection + arg extraction.

This is intentionally a *separate* surface from the streaming chat graph — it
gives NL access to the newer engines (explain_asset, calendar, screener, …)
without destabilising the existing chat.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pfip.agent.tools import dispatch

# Common asset nicknames → canonical symbols.
_NAME_MAP = {
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "nifty": "^NSEI",
    "sensex": "^BSESN",
}

# Uppercase ticker-ish token (AAPL, BTC-USD, TCS.NS).
_TICKER_RE = re.compile(r"\b([A-Z]{2,10}(?:-USD)?(?:\.[A-Z]{2,3})?)\b")
_FY_RE = re.compile(r"\b(20\d{2}-\d{2})\b")

# Words that look like tickers but aren't.
_STOPWORDS = {"I", "A", "THE", "MY", "US", "AND", "FY", "P&L", "PNL", "ROCE", "PE"}


def extract_symbol(message: str) -> Optional[str]:
    low = message.lower()
    for name, sym in _NAME_MAP.items():
        if re.search(rf"\b{name}\b", low):
            return sym
    for tok in _TICKER_RE.findall(message):
        if tok.upper() not in _STOPWORDS:
            return tok
    return None


def select_tool(message: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Deterministically map a message to (tool_name, args). None if no match."""
    m = message.lower()
    sym = extract_symbol(message)

    # Order matters: most specific intents first.
    if re.search(r"\b(explain|teach|learn about|why did|what is|walk me through)\b", m) and sym:
        return "explain_asset", {"symbol": sym}
    if re.search(r"\b(calendar|earnings|announcement|corporate action|upcoming)\b", m):
        return "get_calendar", {}
    if re.search(r"\b(diligence|dossier|research|deep dive|tell me about)\b", m) and sym:
        return "get_diligence", {"symbol": sym}
    if re.search(r"\b(tax|capital gain|stcg|ltcg)\b", m):
        fy = _FY_RE.search(message)
        return "get_tax_summary", {"fy": fy.group(1) if fy else "2024-25"}
    if re.search(r"\b(p&l|pnl|profit|how did i do|returns?)\b", m):
        return "get_recent_pnl", {}
    if re.search(r"\b(price|quote|how much is|trading at)\b", m) and sym:
        return "get_current_price", {"symbol": sym}
    if re.search(r"\b(holdings?|portfolio|what do i (own|hold)|my positions?)\b", m):
        return "get_holdings", {}
    if re.search(r"\bsignals?\b", m):
        return "get_open_signals", {}
    # A bare symbol with no verb → treat as "explain this".
    if sym and re.search(r"\b(chart|move|moved|price action)\b", m):
        return "explain_asset", {"symbol": sym}
    return None


async def run_orchestration(session: Any, message: str) -> dict[str, Any]:
    """Select a tool for ``message``, run it, and return a structured result."""
    choice = select_tool(message)
    if choice is None:
        return {
            "matched": False,
            "tool": None,
            "args": {},
            "result": None,
            "note": "No tool matched — try the chat for open-ended questions.",
        }
    name, args = choice
    fn = dispatch(name)
    if fn is None:  # pragma: no cover — registry/selection drift
        return {"matched": False, "tool": name, "args": args, "result": None}
    result = await fn(session, **args)
    return {"matched": True, "tool": name, "args": args, "result": result}
