"""Privacy classifier — decide if a prompt should stay local.

Per ``docs/LLM_ROUTING.md`` §5: portfolio holdings + tax data are sensitive
and must never leave the machine when ``LLM_PRIVACY_STRICT=true``. The
chat agent feeds every user message through :func:`classify_sensitivity`
before routing.

Design rule: **false positives are fine, false negatives are dangerous.**
- A public prompt mis-classified as sensitive is wasted local compute.
- A sensitive prompt mis-classified as public leaks holdings to the cloud.
So we err aggressive: any reasonable signal → sensitive.

Detection signals (additive — any single hit flips the verdict):
1. Personal pronouns ("my", "I", "i'm", "mine", "our").
2. Sensitive nouns (portfolio, holding, tax, P&L, broker, account, …).
3. Holdings tickers — exact match on the user's currently-owned symbols.
4. Account / broker references ("Zerodha", "INDmoney", …).

Limitations called out in the spec:
- "my morning brief" → sensitive (false positive). Acceptable; just costs
  one local-LLM call.
- "tax cuts" in macro context → sensitive (false positive). Acceptable.
- Common-English tickers like "ALL" or "BIG" matched as holdings only when
  user actually holds them (set membership), so no harm at empty-set start.
"""

from __future__ import annotations

import re

from pfip.agent.router import Sensitivity

# ---------------------------------------------------------------------------
# Lexicons (intentionally generous — see false-positive policy above)
# ---------------------------------------------------------------------------


# Personal pronouns. Word-boundary matched, case-insensitive.
# We deliberately skip "we/us" (could be impersonal "we are seeing X in the
# market…") but include "our" since it usually scopes to user data.
_PRONOUN_PATTERNS = [
    re.compile(r"\bmy\b", re.IGNORECASE),
    re.compile(r"\bi\b", re.IGNORECASE),
    re.compile(r"\bi['’]m\b", re.IGNORECASE),
    re.compile(r"\bi['’]ve\b", re.IGNORECASE),
    re.compile(r"\bi['’]d\b", re.IGNORECASE),
    re.compile(r"\bmine\b", re.IGNORECASE),
    re.compile(r"\bour\b", re.IGNORECASE),
]


# Lexicon of words that strongly imply personal-finance context.
_SENSITIVE_NOUNS = {
    # Portfolio / position vocabulary
    "portfolio", "portfolios",
    "holding", "holdings",
    "position", "positions",
    "allocation", "allocations",
    "exposure", "exposures",
    "concentration",
    "wealth", "networth", "net-worth", "net worth",
    "balance", "balances",
    # P&L / gains
    "p&l", "pnl", "p/l", "p&l.", "p&ls",
    "profit", "profits", "loss", "losses",
    "drawdown",
    "realised", "realized", "realised gain", "realised loss",
    "capital gain", "capital gains", "capital-gains",
    "stcg", "ltcg",
    # Tax
    "tax", "taxes", "taxable",
    "itr", "form 67", "form-67", "schedule fa", "schedule-fa",
    "tds", "indexation", "grandfathering",
    "80c", "80d", "80ccd", "section 80",
    # Indian instruments / accounts
    "fd", "epf", "ppf", "nps", "sgb", "gsec",
    # Account/broker words
    "account", "accounts", "broker", "brokerage",
    "demat",
}


# Specific Indian broker / aggregator names. Matched as whole words.
_BROKER_NAMES = {
    "zerodha", "indmoney", "ind money", "groww", "upstox",
    "icicidirect", "icici direct", "hdfc securities", "hdfcsec",
    "kotak securities", "5paisa", "angelone", "angel one",
    "interactive brokers", "ibkr", "robinhood", "fidelity",
    "vanguard", "schwab", "paytm money", "etoro",
    "coinbase", "kraken", "binance", "wazirx", "coindcx",
}


# Compile broker names into a single boundary-aware regex.
_BROKER_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in sorted(_BROKER_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# Compile sensitive-noun set into a single boundary-aware regex.
# We sort longest first so "schedule fa" matches before "schedule" would.
_NOUN_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in sorted(_SENSITIVE_NOUNS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _hit_pronoun(prompt: str) -> bool:
    return any(p.search(prompt) for p in _PRONOUN_PATTERNS)


def _hit_noun(prompt: str) -> bool:
    return bool(_NOUN_RE.search(prompt))


def _hit_broker(prompt: str) -> bool:
    return bool(_BROKER_RE.search(prompt))


def _hit_ticker(prompt: str, tickers: set[str] | None) -> bool:
    """Match any user-owned ticker as a whole word, case-insensitively.

    Tickers like "RELIANCE", "TCS", "BTC-USD" are checked verbatim. We strip
    common suffixes ("-USD", ".NS", ".BO") to widen matches but never broaden
    to substring (so "TAT" wouldn't match "STATE").
    """
    if not tickers:
        return False
    for raw in tickers:
        for variant in {raw, raw.split("-")[0], raw.split(".")[0]}:
            if not variant or len(variant) < 2:
                continue
            pat = re.compile(rf"\b{re.escape(variant)}\b", re.IGNORECASE)
            if pat.search(prompt):
                return True
    return False


def classify_sensitivity(
    prompt: str,
    user_holdings_symbols: set[str] | None = None,
) -> Sensitivity:
    """Return ``Sensitivity.SENSITIVE`` if the prompt touches user data.

    Args:
        prompt: The user-submitted natural-language prompt.
        user_holdings_symbols: Set of symbols the user currently owns,
            normally fetched from the holdings table. ``None`` = no holdings
            context available (which is fine; we still catch pronoun + noun
            signals).

    Returns:
        ``Sensitivity.SENSITIVE`` if any signal hits, else ``PUBLIC``.

    The function is intentionally conservative — a false positive (sending a
    public prompt to local LLM) costs one extra second of latency; a false
    negative (leaking holdings to a cloud provider) is the failure mode we
    cannot tolerate.
    """
    if not prompt or not prompt.strip():
        return Sensitivity.PUBLIC

    if _hit_ticker(prompt, user_holdings_symbols):
        return Sensitivity.SENSITIVE
    if _hit_broker(prompt):
        return Sensitivity.SENSITIVE
    if _hit_noun(prompt):
        return Sensitivity.SENSITIVE
    if _hit_pronoun(prompt):
        return Sensitivity.SENSITIVE
    return Sensitivity.PUBLIC


def explain(prompt: str, user_holdings_symbols: set[str] | None = None) -> dict[str, bool]:
    """Diagnostic helper — return per-signal hit map. Used in tests + logs."""
    return {
        "ticker": _hit_ticker(prompt, user_holdings_symbols),
        "broker": _hit_broker(prompt),
        "noun": _hit_noun(prompt),
        "pronoun": _hit_pronoun(prompt),
    }


# ---------------------------------------------------------------------------
# Smoke tests — runnable as ``python -m pfip.agent.privacy``
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    _cases = [
        # (prompt, holdings, expected)
        ("summarize today's BTC news", None, Sensitivity.PUBLIC),
        ("what's the latest on the Fed?", None, Sensitivity.PUBLIC),
        ("how is my portfolio doing?", None, Sensitivity.SENSITIVE),
        ("calculate my STCG for FY26", None, Sensitivity.SENSITIVE),
        ("should I rebalance?", None, Sensitivity.SENSITIVE),  # "I" hit
        ("what is the current Nifty regime?", None, Sensitivity.PUBLIC),
        ("RELIANCE quarterly earnings analysis", {"RELIANCE.NS"}, Sensitivity.SENSITIVE),
        ("tell me about TSLA fundamentals", {"AAPL"}, Sensitivity.PUBLIC),
        ("review my Zerodha statements", None, Sensitivity.SENSITIVE),
        ("explain LTCG for crypto", None, Sensitivity.SENSITIVE),
    ]
    for prompt, holdings, expected in _cases:
        actual = classify_sensitivity(prompt, holdings)
        ok = "OK" if actual == expected else "FAIL"
        print(f"[{ok}] {actual.value:9s} ← {prompt!r}  (expected {expected.value})")
        if actual != expected:
            print(f"         signals: {explain(prompt, holdings)}")


__all__ = ["classify_sensitivity", "explain"]
