"""Tests for `pfip.portfolio.precommitment` — pure-logic surface.

Coverage:
- Template renders all placeholders.
- Parser reads back what the renderer wrote (round-trip).
- LadderTier enum has the expected 5 tiers in order.
- Renderer constants encode the right capital-ladder caps (5/10/25/100%).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from pfip.portfolio.precommitment import (
    LADDER_TIERS,
    LadderTier,
    PRECOMMITMENT_TEMPLATE,
    parse_signed,
    render_template,
    write_template_if_missing,
)

# ---------------------------------------------------------------------------
# Enum invariants
# ---------------------------------------------------------------------------


def test_ladder_tier_enum_has_all_five_values():
    assert {t.value for t in LadderTier} == {"paper", "5%", "10%", "25%", "full"}


def test_ladder_tier_order_matches_capital_ladder():
    """LADDER_TIERS must encode the documented progression."""
    labels = [name for name, _ in LADDER_TIERS]
    assert labels == ["5%", "10%", "25%", "full"]


def test_ladder_tier_caps_match_documentation():
    """The numeric caps must match the docs (5% / 10% / 25% / 100%)."""
    caps = dict(LADDER_TIERS)
    assert caps["5%"] == pytest.approx(0.05)
    assert caps["10%"] == pytest.approx(0.10)
    assert caps["25%"] == pytest.approx(0.25)
    assert caps["full"] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def test_render_template_substitutes_every_placeholder():
    """Every {placeholder} in the template gets a value when render_template
    is called with the canonical dict."""
    out = render_template(
        minimum_capital_inr=100000,
        drawdown_halt_pct=20.0,
        cooling_off_hours=24,
        sharpe_floor=0.7,
        max_consecutive_losing_months=2,
    )
    # Capital is formatted with thousands separator.
    assert "100,000" in out
    assert "20" in out
    assert "24 hours" in out
    assert "0.7" in out
    assert "{minimum_capital_inr}" not in out  # all placeholders filled
    assert "{drawdown_halt_pct}" not in out
    assert "{cooling_off_hours}" not in out
    assert "{sharpe_floor}" not in out
    assert "{max_consecutive_losing_months}" not in out


def test_template_contains_binding_self_contract_warning():
    """The template must include the binding-self-contract warning."""
    assert "binding self-contract" in PRECOMMITMENT_TEMPLATE


def test_template_lists_capital_ladder():
    """The four ladder tiers (5/10/25/100%) must appear in the template."""
    for tier_label in ("5%", "10%", "25%", "100%"):
        assert tier_label in PRECOMMITMENT_TEMPLATE


def test_template_lists_halt_conditions():
    """The halt-conditions section must be in the template."""
    assert "Halt conditions" in PRECOMMITMENT_TEMPLATE
    assert "drawdown" in PRECOMMITMENT_TEMPLATE.lower()
    assert "sharpe" in PRECOMMITMENT_TEMPLATE.lower()
    assert "losing months" in PRECOMMITMENT_TEMPLATE.lower()


# ---------------------------------------------------------------------------
# Write-if-missing + parse round-trip
# ---------------------------------------------------------------------------


def test_write_template_if_missing_creates_then_skips(tmp_path):
    """First call writes the template; second call is a no-op."""
    p = tmp_path / "pre_commitment.md"
    assert write_template_if_missing(p) is True
    assert p.exists()
    # Second call returns False (already exists).
    assert write_template_if_missing(p) is False


def test_parse_signed_returns_none_for_unsigned_template(tmp_path):
    """A freshly-written (unsigned) template parses as None — placeholder values."""
    p = tmp_path / "pre_commitment.md"
    write_template_if_missing(p)
    # Unsigned: minimum_capital_inr placeholder still present.
    parsed = parse_signed(p)
    assert parsed is None


def test_parse_signed_extracts_filled_values(tmp_path):
    """When a user fills in real values, parse_signed extracts them.

    `parse_signed` looks at the *first* `Signed by:` / `Date:` lines, so
    we must replace the placeholder block in the rendered template — not
    append a new signature section.
    """
    p = tmp_path / "pre_commitment.md"
    raw = render_template(
        minimum_capital_inr=250000,
        drawdown_halt_pct=15.0,
        cooling_off_hours=72,
        sharpe_floor=0.8,
        max_consecutive_losing_months=2,
    )
    raw = raw.replace("Signed by: <YOUR NAME>", "Signed by: Suresh")
    raw = raw.replace("Date:      <YYYY-MM-DD>", "Date:      2026-05-30")
    p.write_text(raw, encoding="utf-8")

    parsed = parse_signed(p)
    assert parsed is not None
    assert parsed.signed_by == "Suresh"
    assert parsed.cooling_off_hours == 72
    assert parsed.max_consecutive_losing_months == 2


def test_parse_signed_missing_file_returns_none(tmp_path):
    """No file → None, not an exception."""
    p = tmp_path / "does_not_exist.md"
    assert parse_signed(p) is None
