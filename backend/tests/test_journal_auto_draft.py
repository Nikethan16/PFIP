"""Tests for the post-mortem auto-draft path on the journal endpoint.

We don't spin up the FastAPI app here — we call the lower-level helpers
directly. Those are the pure-logic surface the API endpoint composes:

- `_build_post_mortem_prompt` — prompt assembly is deterministic.
- `_fallback_template` — kicks in when the LLM router is unavailable
  and writes a useful TODO-stub markdown for the user to fill.

The router-success path is exercised in `tests/test_agent.py`; this
file only guards the deterministic helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pfip.api.journal import (
    AutoDraftRequest,
    _build_post_mortem_prompt,
    _fallback_template,
    _POST_MORTEM_SYSTEM,
    _REQUIRED_CHECKLIST_KEYS,
)


def _fake_row(**overrides):
    base = SimpleNamespace(
        id=uuid4(),
        symbol="BTC/USD",
        direction="BUY",
        thesis="Wyckoff accumulation reaching phase D markup.",
        pre_trade_checklist={k: True for k in _REQUIRED_CHECKLIST_KEYS},
        notes="Bought at 65k, target 80k.",
        post_mortem=None,
        closed_at=None,
        created_at=datetime.now(tz=timezone.utc),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_required_checklist_keys_is_exactly_ten():
    """Appendix B locks the checklist at 10 items. Any change is a bug."""
    assert len(_REQUIRED_CHECKLIST_KEYS) == 10
    assert "regime_check" in _REQUIRED_CHECKLIST_KEYS
    assert "tax_impact_considered" in _REQUIRED_CHECKLIST_KEYS


def test_build_prompt_includes_symbol_direction_pnl():
    prompt = _build_post_mortem_prompt(
        symbol="ETH/USD",
        direction="SELL",
        thesis="Topping pattern after parabolic.",
        checklist={k: True for k in _REQUIRED_CHECKLIST_KEYS},
        notes=None,
        realized_pnl_pct=8.5,
        extra_context=None,
    )
    assert "ETH/USD" in prompt
    assert "SELL" in prompt
    assert "+8.50%" in prompt
    assert "Topping pattern" in prompt
    # All 10 checklist keys are surfaced in the prompt.
    for k in _REQUIRED_CHECKLIST_KEYS:
        assert k in prompt


def test_build_prompt_marks_missing_pnl_explicitly():
    prompt = _build_post_mortem_prompt(
        symbol="NVDA",
        direction="BUY",
        thesis="Earnings beat tailwind",
        checklist={k: False for k in _REQUIRED_CHECKLIST_KEYS},
        notes=None,
        realized_pnl_pct=None,
        extra_context=None,
    )
    assert "not supplied" in prompt
    assert "+0.00%" not in prompt


def test_build_prompt_includes_extra_context_when_supplied():
    prompt = _build_post_mortem_prompt(
        symbol="X",
        direction="HOLD",
        thesis="t",
        checklist={},
        notes="quick note",
        realized_pnl_pct=-2.0,
        extra_context="stopped out at -3%",
    )
    assert "quick note" in prompt
    assert "stopped out" in prompt


def test_system_prompt_forbids_invention():
    """The system prompt must instruct the LLM not to fabricate P&L."""
    # The system prompt steers the LLM toward honesty in three ways: it
    # forbids predictions of the future, forbids trading advice, and
    # requires a TODO placeholder when P&L is missing rather than a guess.
    lowered = _POST_MORTEM_SYSTEM.lower()
    assert "do not predict" in lowered
    assert "do not give trading advice" in lowered
    assert "TODO" in _POST_MORTEM_SYSTEM


def test_fallback_template_renders_five_sections():
    row = _fake_row()
    body = AutoDraftRequest(realized_pnl_pct=3.2)
    md = _fallback_template(row, body)
    # All five Appendix-C sections must be present so the user can fill them in.
    for section in (
        "**Thesis result**",
        "**What worked**",
        "**What didn't**",
        "**Pattern tag**",
        "**Lesson for next time**",
    ):
        assert section in md
    # P&L is rendered when supplied.
    assert "+3.20%" in md


def test_fallback_template_marks_missing_pnl_as_todo():
    row = _fake_row()
    body = AutoDraftRequest(realized_pnl_pct=None)
    md = _fallback_template(row, body)
    assert "TODO: enter P&L" in md


def test_fallback_template_includes_original_thesis():
    row = _fake_row(thesis="Phase D markup at 65k floor")
    md = _fallback_template(row, AutoDraftRequest())
    assert "Phase D markup at 65k floor" in md


def test_auto_draft_request_defaults():
    """The Pydantic model is permissive — both fields optional."""
    req = AutoDraftRequest()
    assert req.realized_pnl_pct is None
    assert req.extra_context is None


def test_auto_draft_request_accepts_floats_and_strings():
    req = AutoDraftRequest(realized_pnl_pct=-1.5, extra_context="manual close")
    assert req.realized_pnl_pct == -1.5
    assert req.extra_context == "manual close"
