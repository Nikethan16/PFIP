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
    # Only actionable signals get their own line: a nightly batch of sixteen
    # "HOLD · 1% confidence" items buried the one alert worth reading. HOLDs
    # and low-confidence rows collapse into a single digest entry.
    sig_rows = (
        (
            await db.execute(
                select(SignalRow)
                .where(SignalRow.generated_at >= cutoff)
                .order_by(SignalRow.generated_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    quiet_signals: list[SignalRow] = []
    for s in sig_rows:
        direction = str(s.direction).upper()
        conf = int(getattr(s, "confidence", 0) or 0)
        if direction in {"BUY", "SELL"} and conf >= 40:
            severity = "WARN" if conf >= 60 else "INFO"
            items.append(
                NotificationItem(
                    kind="signal",
                    severity=severity,
                    title=f"{direction} signal · {s.asset}",
                    body=(
                        f"{conf}% confidence ({s.regime}) — {s.model_name} "
                        f"{s.model_version} · experimental, not a trade instruction"
                    ),
                    at=s.generated_at,
                )
            )
        else:
            quiet_signals.append(s)
    if quiet_signals:
        max_conf = max(int(getattr(s, "confidence", 0) or 0) for s in quiet_signals)
        items.append(
            NotificationItem(
                kind="signal_digest",
                severity="INFO",
                title=f"{len(quiet_signals)} quiet signals (HOLD / low confidence)",
                body=f"Nightly batch — max confidence {max_conf}%. Nothing actionable.",
                at=max(s.generated_at for s in quiet_signals),
            )
        )

    # --- Data-source health -----------------------------------------------
    # A failing or stale source is exactly the kind of thing the bell exists
    # for — it silently degrades every number in the app. (The mf_amfi feed
    # once failed for four days without a single notification.)
    try:
        from sqlalchemy import text as sql_text

        src_rows = (
            await db.execute(
                sql_text(
                    """
                    SELECT source, last_success_at, last_error, consecutive_failures
                    FROM source_health
                    WHERE consecutive_failures > 0
                       OR last_success_at < :stale_cutoff
                    """
                ),
                {"stale_cutoff": datetime.now(tz=timezone.utc) - timedelta(days=2)},
            )
        ).all()
        for source, last_success_at, last_error, consec in src_rows:
            consec = int(consec or 0)
            if consec > 0:
                items.append(
                    NotificationItem(
                        kind="source_health",
                        severity="CRITICAL" if consec >= 3 else "WARN",
                        title=f"Data source failing · {source}",
                        body=(
                            f"{consec} consecutive failures — {(last_error or 'unknown error')[:160]}"
                        ),
                        at=datetime.now(tz=timezone.utc),
                    )
                )
            else:
                age_days = (
                    (datetime.now(tz=timezone.utc) - last_success_at).days
                    if last_success_at
                    else None
                )
                items.append(
                    NotificationItem(
                        kind="source_health",
                        severity="WARN",
                        title=f"Data source stale · {source}",
                        body=f"No successful run in {age_days} days.",
                        at=datetime.now(tz=timezone.utc),
                    )
                )
    except Exception:  # noqa: BLE001 — source_health may not exist on fresh installs
        pass

    # --- Regime transitions ----------------------------------------------
    regime_rows = (
        (
            await db.execute(
                select(RegimeTransitionRow)
                .where(RegimeTransitionRow.at >= cutoff)
                .order_by(RegimeTransitionRow.at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
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
        (
            await db.execute(
                select(ModelEventRow)
                .where(ModelEventRow.at >= cutoff)
                .order_by(ModelEventRow.at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
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

    # The badge counts things worth acting on (WARN/CRITICAL), not every INFO
    # row — a bell stuck at 19 because the model ran overnight teaches the
    # user to ignore it.
    unread = sum(1 for it in items if it.severity in ("WARN", "CRITICAL"))
    return RecentNotifications(unread=unread, window_hours=hours, items=items)
