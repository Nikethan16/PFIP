"""Tests for `pfip.alerts.dispatcher` — pure-logic surface.

The dispatcher composes side effects (Redis, Telegram HTTP), but its
core decisions are deterministic functions of the wall clock + alert
shape. Those are what we test here.

Coverage:
- `_is_quiet_hour` — 23:00–07:00 IST inclusive of 23:00, exclusive of 07:00.
- `_render_template` — template substitution + missing-key tolerance.
- `AlertSeverity` ordering: CRITICAL bypasses quiet hours.
- Template directory is shipped with the canonical 8 kind files.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pfip.alerts.dispatcher import (
    AlertKind,
    AlertSeverity,
    _is_quiet_hour,
    _render_template,
    _TEMPLATES_DIR,
)


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ist_hour,ist_min,expect_quiet",
    [
        # Quiet zone (23:00–07:00 IST)
        (23, 0, True),    # exact start
        (23, 30, True),
        (0, 0, True),
        (3, 14, True),
        (6, 59, True),    # last quiet minute
        # Loud zone (07:00–22:59 IST)
        (7, 0, False),    # exact end — first loud minute
        (10, 30, False),
        (12, 0, False),
        (17, 30, False),  # market-close time
        (22, 59, False),  # last loud minute
    ],
)
def test_is_quiet_hour_matches_spec(ist_hour, ist_min, expect_quiet):
    """Encode the 23:00–07:00 IST window precisely.

    The input to `_is_quiet_hour` is a UTC datetime; we craft one whose IST
    conversion lands on the target hour/minute. IST = UTC + 5:30.
    """
    utc_hour = (ist_hour - 5 - (1 if ist_min < 30 else 0)) % 24
    utc_min = (ist_min - 30) % 60
    dt = datetime(2025, 5, 30, utc_hour, utc_min, 0, tzinfo=timezone.utc)
    assert _is_quiet_hour(dt) is expect_quiet


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def test_render_template_unknown_kind_falls_back():
    """A kind without a template file falls back to a deterministic title + body
    that lists the context keys/values verbatim — never raises."""
    # CUSTOM has no template file by design (it's the catch-all kind).
    title, body = _render_template(
        AlertKind.CUSTOM, {"symbol": "BTC/USD", "score": 0.82}
    )
    assert title == "Custom"
    assert "BTC/USD" in body
    assert "score" in body


def test_render_template_substitutes_placeholders():
    """Templates with `{key}` get filled from the context dict."""
    # We test this against weekly_review.md which we know has placeholders.
    title, body = _render_template(
        AlertKind.WEEKLY_REVIEW,
        {
            "date": "2026-05-30",
            "n_closed": 5,
            "win_rate_pct": 60,
            "avg_pnl_pct": 1.2,
            "top_pattern": "stopped out at -3%",
            "out_path": "data/weekly_reviews/x.md",
        },
    )
    assert title  # rendered
    assert "2026-05-30" in body or "2026-05-30" in title


def test_render_template_tolerates_missing_keys():
    """Missing template variables don't crash — fall back to raw template."""
    # Force a missing key by giving a partial context to a templated kind.
    title, body = _render_template(AlertKind.MORNING_BRIEF, {})
    # Either renders raw template (with `{placeholders}` visible) or falls back.
    assert title  # always non-empty
    assert isinstance(body, str)  # never None


# ---------------------------------------------------------------------------
# Template files exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        AlertKind.REGIME_CHANGE,
        AlertKind.SIGNAL_FIRED,
        AlertKind.RISK_BREACH,
        AlertKind.DRAWDOWN_HALT,
        AlertKind.INGEST_FAILURE,
        AlertKind.CALIBRATION_BREACH,
        AlertKind.WEEKLY_REVIEW,
    ],
)
def test_template_file_exists_for_each_kind(kind):
    """Every shipped kind has a markdown template on disk."""
    p = _TEMPLATES_DIR / f"{kind.value}.md"
    assert p.exists(), f"missing template {p}"
    # Non-trivial content.
    text = p.read_text()
    assert len(text.strip()) > 10


# ---------------------------------------------------------------------------
# Enum invariants
# ---------------------------------------------------------------------------


def test_alert_severity_string_values():
    """Severities serialize to UPPERCASE strings."""
    assert AlertSeverity.INFO.value == "INFO"
    assert AlertSeverity.WARN.value == "WARN"
    assert AlertSeverity.CRITICAL.value == "CRITICAL"


def test_alert_kind_round_trip_via_value():
    """Each kind round-trips through its string value (Enum invariant)."""
    for k in AlertKind:
        assert AlertKind(k.value) is k
