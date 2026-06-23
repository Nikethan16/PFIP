"""Tests for proactive alerts (pfip.alerts.proactive) + new templates."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pfip.alerts.dispatcher import AlertKind
from pfip.alerts.proactive import (
    CalendarEvent,
    rebalance_drift_contexts,
    run_event_calendar_check,
    run_rebalance_drift_check,
    upcoming_events,
)

_TEMPLATES = Path(__file__).resolve().parents[1] / "pfip" / "alerts" / "templates"


# ---------------------------------------------------------------------------
# Templates exist for the new kinds
# ---------------------------------------------------------------------------


def test_new_alert_kinds_have_templates():
    assert (_TEMPLATES / f"{AlertKind.REBALANCE_DRIFT.value}.md").exists()
    assert (_TEMPLATES / f"{AlertKind.EVENT_CALENDAR.value}.md").exists()


# ---------------------------------------------------------------------------
# Rebalance drift detection
# ---------------------------------------------------------------------------


def test_no_drift_contexts_when_on_target():
    current = {"equity": Decimal("50"), "debt": Decimal("50")}
    target = {"equity": 0.5, "debt": 0.5}
    assert rebalance_drift_contexts(current, target) == []


def test_drift_context_flags_overweight_bucket():
    current = {"equity": Decimal("80"), "debt": Decimal("20")}
    target = {"equity": 0.5, "debt": 0.5}
    ctxs = rebalance_drift_contexts(current, target, drift_threshold=0.05)
    eq = next(c for c in ctxs if c["bucket"] == "equity")
    assert eq["action"] == "SELL"
    assert "%" in eq["drift_pct"]


# ---------------------------------------------------------------------------
# Event calendar detection
# ---------------------------------------------------------------------------


def test_upcoming_events_filters_by_holding_and_horizon():
    events = [
        CalendarEvent("RELIANCE.NS", date(2026, 6, 25), "dividend"),
        CalendarEvent("TCS.NS", date(2026, 7, 30), "earnings"),  # out of horizon
        CalendarEvent("INFY.NS", date(2026, 6, 24), "earnings"),  # not held
    ]
    hits = upcoming_events(
        ["RELIANCE.NS", "TCS.NS"], events, horizon_days=7, as_of=date(2026, 6, 23)
    )
    assert len(hits) == 1
    assert hits[0].symbol == "RELIANCE.NS"


def test_upcoming_events_sorted_by_date():
    events = [
        CalendarEvent("A", date(2026, 6, 28), "dividend"),
        CalendarEvent("A", date(2026, 6, 24), "earnings"),
    ]
    hits = upcoming_events(["A"], events, horizon_days=10, as_of=date(2026, 6, 23))
    assert [e.when for e in hits] == sorted(e.when for e in hits)


# ---------------------------------------------------------------------------
# Dispatch wrappers (send_alert is a no-op without the kill-switch flag)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_rebalance_drift_check_counts_alerts():
    current = {"equity": Decimal("80"), "debt": Decimal("20")}
    target = {"equity": 0.5, "debt": 0.5}
    n = await run_rebalance_drift_check(current, target, drift_threshold=0.05)
    assert n >= 1


@pytest.mark.asyncio
async def test_run_event_calendar_check_no_events_sends_nothing():
    n = await run_event_calendar_check(["A"], [], horizon_days=7, as_of=date(2026, 6, 23))
    assert n == 0


@pytest.mark.asyncio
async def test_run_event_calendar_check_with_events():
    events = [CalendarEvent("A", date(2026, 6, 24), "dividend", "₹5/share")]
    n = await run_event_calendar_check(["A"], events, horizon_days=7, as_of=date(2026, 6, 23))
    assert n == 1
