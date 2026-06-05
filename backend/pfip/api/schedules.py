"""Read-only API: list registered Prefect deployments + their last/next run.

Used by the Operations · Schedules UI to surface what's scheduled and
whether anything is overdue. The skipped-task watchdog flow uses the
same data internally; this endpoint just exposes it.

If the Prefect API is unreachable (cold start before the server is up)
we return ``{"deployments": [], "error": "prefect_unreachable"}`` rather
than 500-ing — the page renders a useful "Prefect not running" empty state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from pfip.api.deps import CurrentUser

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("/")
async def list_schedules(_user: CurrentUser) -> dict[str, Any]:
    """Return every Prefect deployment with last/next run + lateness."""
    try:
        from prefect.client.orchestration import get_client  # local import
    except Exception as exc:  # pragma: no cover
        return {"deployments": [], "error": f"prefect_import_failed: {exc}"}

    try:
        async with get_client() as client:
            deployments = await client.read_deployments()
    except Exception as exc:
        return {"deployments": [], "error": f"prefect_unreachable: {exc}"}

    now = datetime.now(tz=timezone.utc)
    out: list[dict[str, Any]] = []
    for d in deployments:
        name = getattr(d, "name", str(d))
        tags = list(getattr(d, "tags", []) or [])
        schedule = getattr(d, "schedule", None)
        cron = getattr(schedule, "cron", None) if schedule else None
        try:
            runs = await client.read_flow_runs(
                deployment_filter={"id": {"any_": [d.id]}},
                sort="START_TIME_DESC",
                limit=5,
            )
        except Exception:
            runs = []
        last_success = None
        last_run = None
        for r in runs:
            if last_run is None and getattr(r, "end_time", None):
                last_run = r.end_time
            state = getattr(r, "state", None)
            if state and str(getattr(state, "type", "")).endswith("COMPLETED"):
                last_success = getattr(r, "end_time", None)
                if last_success:
                    break
        age_hours: float | None = None
        if last_success:
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=timezone.utc)
            age_hours = (now - last_success).total_seconds() / 3600.0
        out.append(
            {
                "name": name,
                "tags": tags,
                "cron": cron,
                "last_run_at": last_run.isoformat() if last_run else None,
                "last_success_at": last_success.isoformat() if last_success else None,
                "age_hours": age_hours,
            }
        )

    out.sort(key=lambda x: x["name"])
    return {"deployments": out, "error": None}
