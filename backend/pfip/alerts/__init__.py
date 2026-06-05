"""PFIP outbound alerting layer.

Two responsibilities:

1. **Templates** (``templates/*.md``) — markdown templates per alert kind.
2. **Delivery** (``telegram.py``) — sends rendered alerts to Telegram with
   severity tiers, digest mode, quiet hours, and rate caps.

Public surface:

    from pfip.alerts import send_alert, AlertSeverity, AlertKind

    await send_alert(
        AlertKind.RISK_BREACH,
        AlertSeverity.WARN,
        context={"asset": "BTC-USD", "drawdown_pct": 0.21},
    )

Severities (from `WHY_AND_WHAT.md` §5.6):

- ``INFO``: digest mode — accumulated and sent hourly. Quiet 23:00–07:00 IST.
- ``WARN``: instant, but rate-capped (≤ 10/hour). Quiet 23:00–07:00 IST.
- ``CRITICAL``: instant, never rate-capped, ignores quiet hours.
"""

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

__all__ = ["AlertKind", "AlertSeverity", "send_alert"]
