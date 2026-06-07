"""Prefect flow: promote unacknowledged WARN alerts to CRITICAL after 2h.

Drains the `alerts:pending_ack:*` Redis keys, re-sends anything older
than the escalation threshold at CRITICAL severity (which bypasses
quiet hours + rate cap). Runs every 30 minutes.
"""

from __future__ import annotations

from prefect import flow, get_run_logger

from pfip.alerts.dispatcher import escalate_unacked_warns


@flow(name="escalate-unacked", log_prints=True)
async def escalate_unacked(escalation_after_minutes: int = 120) -> dict[str, int]:
    logger = get_run_logger()
    result = await escalate_unacked_warns(escalation_after_minutes=escalation_after_minutes)
    logger.info(
        "escalation: checked={} escalated={}",
        result.get("checked", 0),
        result.get("escalated", 0),
    )
    return result


if __name__ == "__main__":
    import asyncio

    asyncio.run(escalate_unacked())
