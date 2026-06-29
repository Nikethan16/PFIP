"""Unit tests for the deterministic catalyst classifier (Phase 3)."""

from __future__ import annotations

import pytest

from pfip.events.extractor import _dedup_key, classify_headline


@pytest.mark.parametrize(
    "headline,expected_kind",
    [
        ("Reliance wins Rs 5,000 cr defence order", "contract_win"),
        ("L&T bags new metro tender worth 8000 crore", "contract_win"),
        ("NVIDIA Q3 profit beats estimates", "earnings_surprise"),
        ("HDFC Bank net profit rises 18%", "earnings_surprise"),
        ("Adani to acquire stake in cement maker", "m_and_a"),
        ("SEBI probe into insider trading widens", "regulatory"),
        ("Morgan Stanley upgrades Infosys to overweight", "upgrade"),
        ("Goldman downgrades TCS to underperform", "downgrade"),
        ("Board approves Rs 2000 cr share buyback", "buyback"),
        ("Company cuts FY26 guidance amid weak demand", "guidance"),
        ("CEO steps down after five years", "management"),
        ("Markets open flat ahead of data", None),
        ("Gold prices steady in early trade", None),
    ],
)
def test_classify_headline(headline: str, expected_kind: str | None) -> None:
    result = classify_headline(headline)
    if expected_kind is None:
        assert result is None
    else:
        assert result is not None and result[0] == expected_kind
        assert 0.0 <= result[1] <= 1.0


def test_dedup_key_stable_and_distinct() -> None:
    a = _dedup_key("RELIANCE.NS", "contract_win", "Reliance wins big order")
    a2 = _dedup_key("reliance.ns", "contract_win", "Reliance wins big order")
    b = _dedup_key("RELIANCE.NS", "earnings_surprise", "Reliance wins big order")
    assert a == a2  # ticker case-insensitive, deterministic
    assert a != b  # different kind → different key
