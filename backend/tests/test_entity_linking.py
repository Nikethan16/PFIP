"""News entity-linking precision (pfip.ingest.news._pipeline).

Regression: "Space Stock Rocket Lab (Nasdaq: RKLB) ... Space Industry Deal"
mis-tagged QQQ (via a bare "nasdaq" alias) and SPCE (via a generic word). The
linker must not fuzzy-bleed generic exchange/market words onto ETFs, and an
explicit mention of an UNtracked ticker must link to nothing tracked.
"""

from __future__ import annotations

from pfip.ingest.news import _pipeline as P


def _match(text: str, tickers: list[str]) -> set[str]:
    """Reimplement the linker's matching over an in-memory haystack."""
    import re

    pats = []
    for tk in tickers:
        for alias in P._aliases_for(tk):
            pats.append((tk, re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)))
    tracked_bases = {re.split(r"[.\-/]", tk.upper())[0]: tk for tk in tickers}
    matched = {sym for sym, pat in pats if pat.search(text)}
    matched |= P._explicit_tracked_tickers(text, tracked_bases)
    return matched


ROCKET_LAB = (
    "Space Stock Rocket Lab Corporation (Nasdaq: RKLB) Soars on $8 Billion "
    "Major Space Industry Deal"
)


def test_bare_nasdaq_no_longer_tags_qqq():
    assert "nasdaq" not in {a.lower() for a in P._aliases_for("QQQ")}
    # The Rocket Lab headline must NOT tag QQQ (RKLB is untracked → link nothing).
    assert _match(ROCKET_LAB, ["QQQ", "SPY", "NVDA"]) == set()


def test_explicit_tracked_ticker_links_precisely():
    # If the tracked universe includes NVDA, "(NASDAQ: NVDA)" links exactly NVDA.
    assert _match("Chipmaker (NASDAQ: NVDA) jumps on earnings", ["NVDA", "QQQ"]) == {"NVDA"}
    # A cashtag works too.
    assert _match("$AAPL announces buyback", ["AAPL", "MSFT"]) == {"AAPL"}


def test_real_company_name_still_links():
    # The precision fix must not break legitimate name aliases.
    assert _match("Reliance Industries posts record quarter", ["RELIANCE.NS"]) == {"RELIANCE.NS"}
    assert _match("Bitcoin rallies past resistance", ["BTC-USD"]) == {"BTC-USD"}


def test_stopword_base_token_dropped():
    # The derived BASE token is stopword-filtered: "NASDAQ.NS" keeps its exact
    # symbol but must NOT contribute the bare "NASDAQ" token (which would match
    # every "Nasdaq: X" headline).
    aliases = P._aliases_for("NASDAQ.NS")
    assert "NASDAQ.NS" in aliases
    assert "NASDAQ" not in aliases
