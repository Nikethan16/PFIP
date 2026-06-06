"""`/api/v1/notifications/recent` — backend mirror for the frontend bell.

The frontend ``NotificationBell`` (``components/nav/topbar.tsx``) polls this
endpoint once a minute and reads ``{ unread: number }`` to render the badge.

PFIP has **no dedicated "sent notifications" store** — the outbound alert
dispatcher (``pfip.alerts.dispatcher``) pushes to Telegram and queues INFO
digests in Redis (transient), neither of which is queryable per-user with a
read/unread state. Rather than fabricate notifications, this endpoint surfaces
the *real persisted system events* that the alert layer is built on:

- new ML **signals** (``signals`` table),
- **regime transitions** (``regime_transitions`` table),
- **model lifecycle events** — suspensions / reinstatements (``model_events``).

These are exactly the events that drive WARN/CRITICAL Telegram alerts, so the
bell mirrors them honestly. ``unread`` is the count of such events in the
trailing window (default 24h): PFIP is single-user and there is no per-event
read receipt, so "unread" is defined as "occurred recently". When nothing has
happened (or the DB is empty) the shape is a correct, non-fake
``{"unread": 0, "items": []}``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.calibration_reports import ModelEventRow, RegimeTransitionRow
from pfip.models.signals import SignalRow

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationItem(BaseModel):
    """A single surfaced system event, newest-first in the response."""

    kind: str  # "signal" | "regime_transition" | "model_event"
    severity: str  # "INFO" | "WARN" | "CRITICAL"
    title: str
    body: str
    at: datetime


class RecentNotifications(BaseModel):
    """Bell payload. ``unread`` is read by the frontend badge."""

    unread: int
    window_hours: int
    items: list[NotificationItem]


@router.get("/recent", response_model=RecentNotifications)
async def recent_notifications(
    db: DbSession,
    _user: CurrentUser,
    hours: int = 24,
    limit: int = 20,
) -> RecentNotifications:
    """Return recent system events as notifications + an ``unread`` count.

    Read-only and side-effect free. Aggregates from the persisted event
    sources the alert layer uses; returns ``{"unread": 0, "items": []}`` when
    nothing recent exists. ``unread`` counts events in the trailing ``hours``
    window (there is no per-event read receipt in single-user mode).
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    items: list[NotificationItem] = []

    # --- New ML signals ---------------------------------------------------
    sig_rows = (
        await db.execute(
            select(SignalRow)
            .where(SignalRow.generated_at >= cutoff)
            .order_by(SignalRow.generated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for s in sig_rows:
        direction = str(s.direction).upper()
        conf = int(getattr(s, "confidence", 0) or 0)
        # A high-confidence BUY/SELL is WARN-worthy; HOLD/low-conf is INFO.
        severity = "WARN" if direction in {"BUY", "SELL"} and conf >= 60 else "INFO"
        items.append(
            NotificationItem(
                kind="signal",
                severity=severity,
                title=f"{direction} signal · {s.asset}",
                body=f"{conf}% confidence ({s.regime}) — {s.model_name} {s.model_version}",
                at=s.generated_at,
            )
        )

    # --- Regime transitions ----------------------------------------------
    regime_rows = (
        await db.execute(
            select(RegimeTransitionRow)
            .where(RegimeTransitionRow.at >= cutoff)
            .order_by(RegimeTransitionRow.at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for r in regime_rows:
        frm = r.from_regime or "?"
        items.append(
            NotificationItem(
                kind="regime_transition",
                severity="WARN",
                title=f"Regime change · {r.symbol}",
                body=f"{frm} → {r.to_regime} ({float(r.confidence) * 100:.0f}% conf)",
                at=r.at,
            )
        )

    # --- Model lifecycle events ------------------------------------------
    event_rows = (
        await db.execute(
            select(ModelEventRow)
            .where(ModelEventRow.at >= cutoff)
            .order_by(ModelEventRow.at.desc())
            .limit(limit)
        )
    ).scalars().all()
    for e in event_rows:
        etype = str(e.event_type)
        severity = "CRITICAL" if "suspend" in etype.lower() else "INFO"
        items.append(
            NotificationItem(
                kind="model_event",
                severity=severity,
                title=f"Model {etype} · {e.model_name}",
                body=e.reason or f"{e.model_name} {e.model_version}",
                at=e.at,
            )
        )

    # Newest-first across all sources, capped at `limit`.
    items.sort(key=lambda it: it.at, reverse=True)
    items = items[:limit]

    return RecentNotifications(unread=len(items), window_hours=hours, items=items)
