"""Read-only API: the platform's scheduled jobs + best-effort last-run.

Scheduling moved off Prefect to **host systemd timers** (on the Oracle VM) for
the daily/backup jobs and **GitHub Actions** for the weekly job. This endpoint
reports that real, configured schedule so the Operations · Schedules page shows
what's scheduled and roughly when it last ran. Live per-run history lives in
``journalctl -u <unit>`` (systemd) and the Actions tab (weekly) — not here.

Shape is unchanged for the frontend: ``{deployments: [...], error: null}`` where
each row is ``{name, tags, cron, last_run_at, last_success_at, age_hours}``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from pfip.api.deps import CurrentUser, DbSession

router = APIRouter(prefix="/schedules", tags=["schedules"])

# The configured schedule (cron in UTC). Mirrors the systemd units on the VM
# (pfip-pipeline.timer @ 02:30, pfip-backup.timer @ 03:30) and weekly.yml.
_JOBS: list[dict[str, Any]] = [
    {
        "name": "daily-pipeline",
        "tags": ["systemd", "pfip-pipeline.timer"],
        "cron": "30 2 * * *",  # 02:30 UTC daily
    },
    {
        "name": "neon-backup",
        "tags": ["systemd", "pfip-backup.timer"],
        "cron": "30 3 * * *",  # 03:30 UTC daily
    },
    {
        "name": "weekly-review-train",
        "tags": ["github-actions", "weekly.yml"],
        "cron": "30 3 * * 0",  # 03:30 UTC Sundays
    },
]


async def _pipeline_last_success(db: DbSession) -> datetime | None:
    """Best-effort last daily-pipeline run = newest ``regime.since`` (the regime
    stage writes a row every run). Returns None if unavailable."""
    try:
        from sqlalchemy import func, select

        from pfip.models.regime import RegimeRow

        return (await db.execute(select(func.max(RegimeRow.since)))).scalar()
    except Exception:  # — read-only, never 500 the ops page
        return None


@router.get("/")
async def list_schedules(_user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Return the configured scheduled jobs with a best-effort last-run."""
    now = datetime.now(tz=UTC)
    pipeline_last = await _pipeline_last_success(db)

    out: list[dict[str, Any]] = []
    for job in _JOBS:
        last_success = pipeline_last if job["name"] == "daily-pipeline" else None
        age_hours: float | None = None
        if last_success is not None:
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=UTC)
            age_hours = round((now - last_success).total_seconds() / 3600.0, 2)
        out.append(
            {
                "name": job["name"],
                "tags": job["tags"],
                "cron": job["cron"],
                "last_run_at": last_success.isoformat() if last_success else None,
                "last_success_at": last_success.isoformat() if last_success else None,
                "age_hours": age_hours,
            }
        )
    return {"deployments": out, "error": None}
