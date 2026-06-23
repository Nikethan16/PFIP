"""Proactive, scheduled portfolio alerts.

Turns two recurring checks into push alerts via the existing dispatcher:

  1. **Rebalance drift** — when any allocation bucket has drifted past the
     threshold, fire a ``REBALANCE_DRIFT`` alert with the realigning trade.
  2. **Event calendar** — dividends / earnings on held names landing within a
     short horizon fire an ``EVENT_CALENDAR`` alert.

The detection functions are pure (no DB / no network) so they're unit-testable;
the ``run_*`` wrappers compute the context and hand it to ``send_alert``, which
already handles severity, quiet hours, rate-capping, and the kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Sequence

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.portfolio.allocation import rebalance_suggestions


# ---------------------------------------------------------------------------
# Rebalance drift
# ---------------------------------------------------------------------------


def rebalance_drift_contexts(
    current_allocation: dict[str, Decimal | float],
    target_allocation: dict[str, float],
    *,
    drift_threshold: float = 0.05,
) -> list[dict[str, Any]]:
    """Return one alert-context dict per bucket that has drifted past threshold.

    Empty list ⇒ nothing to alert. Reuses the portfolio's rebalance engine so
    the numbers match the Portfolio → Rebalance view exactly.
    """
    current = {k: Decimal(str(v)) for k, v in current_allocation.items()}
    suggestions = rebalance_suggestions(current, target_allocation, drift_threshold)
    contexts: list[dict[str, Any]] = []
    for s in suggestions:
        contexts.append(
            {
                "bucket": s.bucket,
                "current_pct": f"{s.current_pct:.1%}",
                "target_pct": f"{s.target_pct:.1%}",
                "drift_pct": f"{s.drift:+.1%}",
                "threshold_pct": f"{drift_threshold:.0%}",
                "action": s.action,
                "notional_inr": str(s.notional_inr),
            }
        )
    return contexts


async def run_rebalance_drift_check(
    current_allocation: dict[str, Decimal | float],
    target_allocation: dict[str, float],
    *,
    drift_threshold: float = 0.05,
) -> int:
    """Dispatch a drift alert per drifted bucket. Returns the number sent."""
    contexts = rebalance_drift_contexts(
        current_allocation, target_allocation, drift_threshold=drift_threshold
    )
    for ctx in contexts:
        await send_alert(
            kind=AlertKind.REBALANCE_DRIFT,
            severity=AlertSeverity.WARN,
            context=ctx,
        )
    return len(contexts)


# ---------------------------------------------------------------------------
# Event calendar (dividends / earnings)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalendarEvent:
    """A scheduled corporate event on a symbol."""

    symbol: str
    when: date
    kind: str  # "dividend" | "earnings"
    detail: str = ""


def upcoming_events(
    held_symbols: Sequence[str],
    events: Sequence[CalendarEvent],
    *,
    horizon_days: int = 7,
    as_of: date | None = None,
) -> list[CalendarEvent]:
    """Events on held symbols falling within ``[as_of, as_of + horizon]``."""
    as_of = as_of or date.today()
    end = as_of + timedelta(days=horizon_days)
    held = set(held_symbols)
    hits = [e for e in events if e.symbol in held and as_of <= e.when <= end]
    return sorted(hits, key=lambda e: (e.when, e.symbol))


def _events_block(events: Sequence[CalendarEvent]) -> str:
    return "\n".join(
        f"- {e.when.isoformat()} · {e.symbol} · {e.kind}"
        + (f" — {e.detail}" if e.detail else "")
        for e in events
    )


async def run_event_calendar_check(
    held_symbols: Sequence[str],
    events: Sequence[CalendarEvent],
    *,
    horizon_days: int = 7,
    as_of: date | None = None,
) -> int:
    """Dispatch one event-calendar alert if any held name has an event soon.

    Returns the number of events surfaced (0 ⇒ no alert sent).
    """
    hits = upcoming_events(held_symbols, events, horizon_days=horizon_days, as_of=as_of)
    if not hits:
        return 0
    await send_alert(
        kind=AlertKind.EVENT_CALENDAR,
        severity=AlertSeverity.INFO,
        context={
            "horizon_days": horizon_days,
            "n_events": len(hits),
            "events_block": _events_block(hits),
        },
    )
    return len(hits)


__all__ = [
    "CalendarEvent",
    "rebalance_drift_contexts",
    "run_rebalance_drift_check",
    "upcoming_events",
    "run_event_calendar_check",
]
