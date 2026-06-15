"""Prefect flow: skipped-task alerter.

Runs hourly. Queries the Prefect API for every deployment, looks at the
last successful run, and emits a Telegram WARN if a deployment's last
success is older than 2× its expected cadence (e.g. an hourly flow that
hasn't succeeded in 2 hours, a daily flow that hasn't in 48 hours).

Why this exists: the value of an automated brief or a daily reconciliation
goes to zero the moment it silently stops firing. The single biggest
class of "I thought this was running" outage we want to catch.

The cadence per deployment is read from a small static map keyed by
deployment name (kept in this file so changes show up in code review).
If a deployment isn't in the map we default to "daily" (24h budget).

The flow itself is forgiving: any error talking to the Prefect API is
swallowed and logged — we don't want the watchdog to wake you up because
the watchdog couldn't run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from prefect import flow, get_run_logger
from prefect.client.orchestration import get_client

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

# Expected max staleness per deployment. Pad to 2× the cron cadence so a
# single late run doesn't page; that's what calibration is for.
_BUDGET_HOURS: dict[str, float] = {
    "ingest-btc-daily": 48,
    "compute-features-btc-daily": 48,
    "ingest-news-15min": 1,
    "anomaly-scan-daily": 48,
    "regime-detect-btc-daily": 48,
    "reconcile-daily": 48,
    "weekly-review": 24 * 8,
    "ragas-eval-monthly": 24 * 35,
    "market-close-summary": 48,
    "shadow-rollup-monthly": 24 * 35,
    "shadow-reconcile-daily": 48,
    "backtest-walk-forward-btc-weekly": 24 * 8,
    "train-lgbm-btc-weekly": 24 * 8,
    "annual-itr-drill": 24 * 400,
    "skipped-task-alerter": 4,
}
_DEFAULT_BUDGET_HOURS = 24.0


@flow(name="skipped-task-alerter", log_prints=True)
async def skipped_task_alerter() -> dict[str, int]:
    """Scan Prefect deployments; alert on stale ones."""
    logger = get_run_logger()
    now = datetime.now(tz=timezone.utc)

    try:
        async with get_client() as client:
            deployments = await client.read_deployments()
    except Exception as exc:
        logger.warning("could not reach Prefect API: {}", exc)
        return {"checked": 0, "stale": 0}

    stale: list[tuple[str, float, float]] = []  # (name, age_hours, budget_hours)
    for d in deployments:
        name = getattr(d, "name", None) or str(d)
        budget = _BUDGET_HOURS.get(name, _DEFAULT_BUDGET_HOURS)
        try:
            runs = await client.read_flow_runs(
                deployment_filter={"id": {"any_": [d.id]}},
                sort="START_TIME_DESC",
                limit=10,
            )
        except Exception:
            continue
        last_success = None
        for r in runs:
            state = getattr(r, "state", None)
            state_type = getattr(state, "type", None) if state else None
            if str(state_type).endswith("COMPLETED") and getattr(r, "end_time", None):
                last_success = r.end_time
                break
        if last_success is None:
            stale.append((name, float("inf"), budget))
            continue
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        age_hours = (now - last_success).total_seconds() / 3600.0
        if age_hours > budget:
            stale.append((name, age_hours, budget))

    if not stale:
        logger.info("no stale deployments ({} checked)", len(deployments))
        return {"checked": len(deployments), "stale": 0}

    lines = ["⚠️ *Skipped-task watchdog*", ""]
    for name, age, budget in stale:
        if age == float("inf"):
            lines.append(f"- `{name}`: never succeeded (budget {budget:.0f}h)")
        else:
            lines.append(f"- `{name}`: {age:.1f}h old (budget {budget:.0f}h)")
    lines.append("")
    lines.append("Inspect Prefect UI → Deployments → late-run logs.")

    await send_alert(
        kind=AlertKind.SYSTEM_HEALTH,
        severity=AlertSeverity.WARN,
        title_override=f"{len(stale)} stale deployment(s)",
        body_override="\n".join(lines),
    )
    return {"checked": len(deployments), "stale": len(stale)}


if __name__ == "__main__":
    import asyncio

    asyncio.run(skipped_task_alerter())
