"""Severity-aware alert dispatcher.

Routes alerts to the configured channels (currently Telegram) based on
severity and current time. Implements:

- **Severity tiers**: INFO / WARN / CRITICAL
- **Digest mode** for INFO: accumulated in Redis, flushed hourly by a
  Prefect scheduled flow (or by the next dispatch call after the digest
  window closes)
- **Quiet hours**: 23:00–07:00 IST suppresses INFO + WARN (not CRITICAL)
- **Rate cap**: ≤ 10 outbound msgs/hour, escalating overflow to a digest
- **Kill switch**: `FEATURE_TELEGRAM_ALERTS=false` short-circuits all sends

Failure handling: any send failure is logged + swallowed; an alert
dropped is never worse than the entire calling flow crashing.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from redis.asyncio import Redis

from pfip.core.config import get_settings

if TYPE_CHECKING:
    from pfip.core.user_prefs import UserPrefs


IST = ZoneInfo("Asia/Kolkata")

QUIET_HOURS_START = time(23, 0)
QUIET_HOURS_END = time(7, 0)
RATE_CAP_PER_HOUR = 10
REDIS_KEY_RATE = "pfip:alerts:rate"
REDIS_KEY_DIGEST = "pfip:alerts:digest"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


# Ordinal ranking so an alert's severity can be compared against the operator's
# ``alert_severity_threshold`` preference — anything strictly below the
# threshold is suppressed (digested), never delivered live.
_SEVERITY_RANK: dict[str, int] = {
    AlertSeverity.INFO.value: 0,
    AlertSeverity.WARN.value: 1,
    AlertSeverity.CRITICAL.value: 2,
}


class AlertKind(str, Enum):
    MORNING_BRIEF = "morning_brief"
    REGIME_CHANGE = "regime_change"
    SIGNAL_FIRED = "signal_fired"
    RISK_BREACH = "risk_breach"
    DRAWDOWN_HALT = "drawdown_halt"
    INGEST_FAILURE = "ingest_failure"
    CATALYST = "catalyst"
    CALIBRATION_BREACH = "calibration_breach"
    PAPER_TRADE_REPORT = "paper_trade_report"
    POST_MORTEM_REQUIRED = "post_mortem_required"
    SYSTEM_HEALTH = "system_health"
    WEEKLY_REVIEW = "weekly_review"
    REBALANCE_DRIFT = "rebalance_drift"
    EVENT_CALENDAR = "event_calendar"
    CUSTOM = "custom"


@dataclass
class Alert:
    kind: AlertKind
    severity: AlertSeverity
    title: str
    body: str
    context: dict[str, Any]
    timestamp: datetime


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _render_template(kind: AlertKind, context: dict[str, Any]) -> tuple[str, str]:
    """Load templates/{kind}.md and substitute ``{key}`` placeholders.

    Returns (title, body). First non-empty line is the title.
    Falls back to a generic "{kind}: {context}" message if template missing.
    """
    template_path = _TEMPLATES_DIR / f"{kind.value}.md"
    if not template_path.exists():
        title = kind.value.replace("_", " ").title()
        body = "\n".join(f"- **{k}**: {v}" for k, v in context.items())
        return title, body
    raw = template_path.read_text(encoding="utf-8")
    try:
        rendered = raw.format(**context)
    except KeyError as exc:
        logger.warning(f"alert template {kind.value}.md missing context key: {exc}")
        rendered = raw  # render unsubstituted; user sees the placeholders
    lines = rendered.strip().split("\n", 1)
    title = lines[0].lstrip("# ").strip()
    body = lines[1].strip() if len(lines) > 1 else ""
    return title, body


# ---------------------------------------------------------------------------
# Quiet hours + rate cap helpers
# ---------------------------------------------------------------------------


def _is_quiet_hour(
    now_utc: datetime,
    start: time | None = None,
    end: time | None = None,
) -> bool:
    """True if ``now_utc`` (converted to IST) is inside the quiet window.

    ``start``/``end`` default to the module constants (23:00–07:00 IST) but the
    dispatcher passes the operator's persisted ``quiet_hours_start/end`` so the
    window is editable from the settings page. Handles a window that wraps
    midnight (start > end, e.g. 23:00→07:00) as well as a same-day window
    (start < end, e.g. 09:00→17:00).
    """
    start = start if start is not None else QUIET_HOURS_START
    end = end if end is not None else QUIET_HOURS_END
    now_ist = now_utc.astimezone(IST).time()
    if start == end:
        return False  # zero-width window ⇒ never quiet
    if start > end:  # wraps midnight
        return now_ist >= start or now_ist < end
    return start <= now_ist < end


async def _get_redis() -> Redis | None:
    settings = get_settings()
    url = getattr(settings, "redis_url", None) or "redis://redis:6379/0"
    try:
        return Redis.from_url(url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"redis unavailable for rate cap: {exc}")
        return None


async def _check_rate_cap(redis: Redis | None) -> bool:
    """Return True if we're under the cap. Increments the counter on success.

    Sliding window: counter is per-hour bucket, expires after 1 hour.
    """
    if redis is None:
        return True  # fail open if redis unavailable
    bucket = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H")
    key = f"{REDIS_KEY_RATE}:{bucket}"
    try:
        n = await redis.incr(key)
        await redis.expire(key, 3700)
        return int(n) <= RATE_CAP_PER_HOUR
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"rate cap check failed: {exc}")
        return True


async def _queue_digest(redis: Redis | None, alert: Alert) -> None:
    if redis is None:
        return
    try:
        line = f"[{alert.severity.value}] {alert.title}"
        await redis.lpush(REDIS_KEY_DIGEST, line)
        await redis.expire(REDIS_KEY_DIGEST, 7300)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"digest queue push failed: {exc}")


async def flush_digest() -> dict[str, Any]:
    """Drain the digest queue and send a single consolidated message.

    Called by the scheduled Prefect flow ``flush_alert_digest`` (cron hourly).
    Safe to call manually for testing.
    """
    redis = await _get_redis()
    if redis is None:
        return {"flushed": 0, "reason": "redis_unavailable"}
    items: list[str] = []
    try:
        while True:
            item = await redis.rpop(REDIS_KEY_DIGEST)
            if item is None:
                break
            items.append(item)
    finally:
        await redis.close()
    if not items:
        return {"flushed": 0}
    body = "## Hourly digest\n\n" + "\n".join(f"- {line}" for line in items)
    await _send_telegram(
        Alert(
            kind=AlertKind.CUSTOM,
            severity=AlertSeverity.INFO,
            title=f"PFIP digest — {len(items)} items",
            body=body,
            context={"count": len(items)},
            timestamp=datetime.now(tz=timezone.utc),
        ),
        force=True,
    )
    return {"flushed": len(items)}


# ---------------------------------------------------------------------------
# Telegram transport
# ---------------------------------------------------------------------------


async def _send_telegram(
    alert: Alert, *, force: bool = False, enabled: bool | None = None
) -> dict[str, Any]:
    settings = get_settings()
    token = getattr(settings, "telegram_bot_token", None)
    chat_id = getattr(settings, "telegram_bot_chat_id", None)
    if not token or not chat_id:
        return {"ok": False, "reason": "telegram_unconfigured"}
    # Enablement gate: the operator's persisted ``telegram_alerts_enabled``
    # pref (passed as ``enabled``) is authoritative when provided; otherwise we
    # fall back to the legacy env/config ``feature_telegram_alerts`` flag.
    # ``force`` (digest flush, CRITICAL) always bypasses the gate.
    is_enabled = (
        enabled
        if enabled is not None
        else bool(getattr(settings, "feature_telegram_alerts", False))
    )
    if not force and not is_enabled:
        return {"ok": False, "reason": "feature_disabled"}
    severity_emoji = {
        AlertSeverity.INFO: "🟢",
        AlertSeverity.WARN: "🟡",
        AlertSeverity.CRITICAL: "🔴",
    }[alert.severity]
    text = (
        f"{severity_emoji} *{alert.title}*\n\n{alert.body}\n\n"
        f"_PFIP · {alert.timestamp.astimezone(IST).strftime('%Y-%m-%d %H:%M IST')}_"
    )
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_notification": alert.severity == AlertSeverity.INFO,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
            )
        return {"ok": resp.status_code == 200, "code": resp.status_code}
    except httpx.HTTPError as exc:
        logger.warning(f"telegram send failed: {exc}")
        return {"ok": False, "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Operator preferences (best-effort)
# ---------------------------------------------------------------------------


async def _load_prefs_safe() -> "UserPrefs":
    """Load the operator's persisted alert prefs, never raising.

    Opens its own short-lived DB session. Any failure (DB down, no row,
    import error) degrades gracefully to the config-default snapshot so an
    alert is never lost to a settings-lookup hiccup.
    """
    from pfip.core.user_prefs import UserPrefs, load_user_prefs

    try:
        return await load_user_prefs()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"alert prefs lookup failed; using config defaults: {exc}")
        return UserPrefs.from_config()


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def send_alert(
    kind: AlertKind,
    severity: AlertSeverity,
    *,
    context: dict[str, Any] | None = None,
    title_override: str | None = None,
    body_override: str | None = None,
) -> dict[str, Any]:
    """Dispatch an alert. Routes based on severity + current time + rate cap.

    Returns a status dict for caller inspection. Never raises — alert delivery
    failure shouldn't break the calling flow.

    Args:
        kind: alert kind (drives template selection).
        severity: INFO / WARN / CRITICAL.
        context: dict for template substitution.
        title_override: skip template title, use this string.
        body_override: skip template body, use this string.
    """
    context = context or {}
    now = datetime.now(tz=timezone.utc)
    if title_override or body_override:
        title = title_override or kind.value
        body = body_override or ""
    else:
        title, body = _render_template(kind, context)
    alert = Alert(
        kind=kind, severity=severity, title=title, body=body, context=context, timestamp=now
    )

    # Operator-editable knobs (severity threshold, quiet window, telegram gate).
    # Best-effort: a DB hiccup must never block an alert, so fall back to the
    # config-default snapshot.
    prefs = await _load_prefs_safe()
    enabled = prefs.telegram_alerts_enabled
    threshold_rank = _SEVERITY_RANK.get(prefs.alert_severity_threshold, 1)

    redis = await _get_redis()
    try:
        # CRITICAL always sends — bypasses quiet hours + rate cap + threshold.
        if severity == AlertSeverity.CRITICAL:
            return await _send_telegram(alert, force=True)

        # Below the operator's minimum severity ⇒ suppress (digest, don't send).
        if _SEVERITY_RANK.get(severity.value, 0) < threshold_rank:
            await _queue_digest(redis, alert)
            return {"ok": True, "deferred": "below_threshold"}

        # INFO + WARN: respect the operator's quiet window.
        if _is_quiet_hour(now, prefs.quiet_hours_start, prefs.quiet_hours_end):
            await _queue_digest(redis, alert)
            return {"ok": True, "deferred": "quiet_hours"}

        # INFO: always digested
        if severity == AlertSeverity.INFO:
            await _queue_digest(redis, alert)
            return {"ok": True, "deferred": "digest"}

        # WARN: rate-capped
        if not await _check_rate_cap(redis):
            await _queue_digest(redis, alert)
            return {"ok": True, "deferred": "rate_cap_exceeded"}

        return await _send_telegram(alert, enabled=enabled)
    finally:
        if redis is not None:
            try:
                await redis.close()
            except Exception:  # noqa: BLE001
                pass


async def escalate_unacked_warns(*, escalation_after_minutes: int = 120) -> dict[str, int]:
    """Promote unacknowledged WARN alerts to CRITICAL after `escalation_after_minutes`.

    Implementation:
      * Every dispatched WARN is recorded in Redis under
        `alerts:pending_ack:<id>` with the original payload + timestamp.
      * This function scans those keys, finds entries older than the
        threshold, re-dispatches them at CRITICAL severity (which bypasses
        quiet hours + rate cap), and clears the original pending entry.
      * Acknowledgement is recorded via :func:`ack_alert` which the
        Telegram callback handler can call.

    Returns ``{"checked": n, "escalated": k}``.
    """
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    try:
        redis = await _get_redis()
    except Exception as exc:  # pragma: no cover — best effort
        logger.warning(f"escalation: redis unavailable: {exc}")
        return {"checked": 0, "escalated": 0}
    if redis is None:
        return {"checked": 0, "escalated": 0}

    try:
        keys = await redis.keys("alerts:pending_ack:*")
    except Exception as exc:
        logger.warning(f"escalation: keys scan failed: {exc}")
        return {"checked": 0, "escalated": 0}

    escalated = 0
    for k in keys:
        try:
            raw = await redis.get(k)
            if not raw:
                continue
            payload = json.loads(raw)
            ts = float(payload.get("ts", 0))
            if now_ts - ts < escalation_after_minutes * 60:
                continue
            # Re-send at CRITICAL.
            await send_alert(
                kind=AlertKind(payload.get("kind", "system_health")),
                severity=AlertSeverity.CRITICAL,
                title_override=f"ESCALATED · {payload.get('title', '')}",
                body_override=(
                    f"{payload.get('body', '')}\n\n"
                    f"_Auto-escalated after {escalation_after_minutes}m without ack._"
                ),
            )
            await redis.delete(k)
            escalated += 1
        except Exception as exc:
            logger.warning(f"escalation: handler failed for {k}: {exc}")
            continue

    return {"checked": len(keys), "escalated": escalated}


async def ack_alert(alert_id: str) -> bool:
    """Clear a pending-ack record so escalation skips it.

    Called by the Telegram bot callback handler when the user taps the
    'Ack' inline-keyboard button. Returns True if a record existed.
    """
    try:
        redis = await _get_redis()
        if redis is None:
            return False
        deleted = await redis.delete(f"alerts:pending_ack:{alert_id}")
        return bool(deleted)
    except Exception:  # pragma: no cover
        return False


__all__ = [
    "Alert",
    "AlertKind",
    "AlertSeverity",
    "ack_alert",
    "escalate_unacked_warns",
    "flush_digest",
    "send_alert",
]
