"""Privacy classifier tests — see ``pfip.agent.privacy``.

Critical edge cases per the spec:
- Personal pronouns should flip (false positives OK).
- Sensitive nouns should flip.
- User holdings tickers should flip — but NOT if user doesn't own them.
- Common-English-word tickers ("ALL", "BIG") only match when user owns them.
"""

from __future__ import annotations

import pytest

from pfip.agent.privacy import classify_sensitivity, explain
from pfip.agent.router import Sensitivity

# ---------------------------------------------------------------------------
# True positives (should be SENSITIVE)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "how is my portfolio doing?",
        "what's my P&L this month",
        "calculate STCG for my Zerodha trades",
        "review my LTCG for FY26",
        "should I rebalance my holdings?",
        "show me my open positions",
        "how much exposure do I have to IT?",
        "my drawdown breached the limit",
        "what's the tax on my crypto gains",
        "my allocation across asset classes",
        "explain ITR Schedule FA for me",
        "my PPF + EPF + NPS allocation summary",
        "I'm down 12% YTD on my account",
        "I've lost ₹50k on this trade",
        "what would my tax outflow be under indexation",
    ],
)
def test_sensitive_positive_cases(prompt: str) -> None:
    assert (
        classify_sensitivity(prompt) == Sensitivity.SENSITIVE
    ), f"Should be SENSITIVE: {prompt!r} signals={explain(prompt)}"


def test_holdings_ticker_match_flips_sensitive() -> None:
    holdings = {"RELIANCE.NS", "TCS.NS", "BTC-USD"}
    assert (
        classify_sensitivity("RELIANCE quarterly earnings analysis", holdings)
        == Sensitivity.SENSITIVE
    )
    assert classify_sensitivity("BTC technical setup this week", holdings) == Sensitivity.SENSITIVE


def test_broker_name_flips_sensitive() -> None:
    assert classify_sensitivity("export Zerodha trades") == Sensitivity.SENSITIVE
    assert classify_sensitivity("connect to INDmoney") == Sensitivity.SENSITIVE


# ---------------------------------------------------------------------------
# True negatives (should be PUBLIC)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "summarize today's BTC news",
        "what's happening with the Fed today?",
        "Nifty closed above 24000",
        "explain MACD divergence",
        "compare Ethereum vs Solana ecosystems",
        "weekly summary of crypto markets",
        "geopolitical risk in Asia",
        "RBI policy commentary",
        "FOMC minutes interpretation",
    ],
)
def test_public_negative_cases(prompt: str) -> None:
    assert (
        classify_sensitivity(prompt) == Sensitivity.PUBLIC
    ), f"Should be PUBLIC: {prompt!r} signals={explain(prompt)}"


# ---------------------------------------------------------------------------
# Edge cases called out in the spec
# ---------------------------------------------------------------------------


def test_edge_my_in_non_portfolio_context_acceptable_false_positive() -> None:
    """'my morning brief' has 'my' so flips sensitive — accepted false positive."""
    # The spec says false positives are acceptable; we just verify the
    # behaviour is consistent and document it here.
    assert classify_sensitivity("my morning brief please") == Sensitivity.SENSITIVE


def test_edge_tax_cuts_macro_context_is_false_positive() -> None:
    """'tax cuts' in macro discussion still flips — false positive accepted."""
    assert classify_sensitivity("the tax cuts will spur growth") == Sensitivity.SENSITIVE


def test_edge_common_word_ticker_not_matched_when_not_owned() -> None:
    """'ALL', 'BIG' as common English don't flip if user doesn't hold them."""
    # No holdings set → these go through the noun/pronoun gates only.
    assert classify_sensitivity("ALL signals are bullish today") == Sensitivity.PUBLIC
    assert classify_sensitivity("BIG move on the S&P 500 today") == Sensitivity.PUBLIC


def test_edge_common_word_ticker_does_match_when_owned() -> None:
    """If user holds ticker 'ALL', then the word 'ALL' flips sensitive."""
    holdings = {"ALL", "BIG"}
    assert classify_sensitivity("ALL signals are bullish today", holdings) == Sensitivity.SENSITIVE


def test_empty_prompt_is_public() -> None:
    assert classify_sensitivity("") == Sensitivity.PUBLIC
    assert classify_sensitivity("   ") == Sensitivity.PUBLIC


def test_holdings_none_still_catches_pronoun() -> None:
    """No holdings set provided, but pronoun + noun still flip."""
    assert classify_sensitivity("my account balance please") == Sensitivity.SENSITIVE


def test_holdings_normalises_suffixes() -> None:
    """Tickers stored as RELIANCE.NS still match the bare word RELIANCE."""
    assert classify_sensitivity("RELIANCE earnings beat", {"RELIANCE.NS"}) == Sensitivity.SENSITIVE


def test_explain_returns_per_signal_map() -> None:
    out = explain("review my Zerodha STCG", {"RELIANCE.NS"})
    assert isinstance(out, dict)
    assert out["pronoun"] is True
    assert out["broker"] is True
    assert out["noun"] is True
    # No holdings match in this prompt
    assert out["ticker"] is False
