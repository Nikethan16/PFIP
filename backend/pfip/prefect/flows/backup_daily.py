"""Prefect flow: nightly disaster-recovery backup.

A thin wrapper that shells out to ``scripts/backup.py`` so the backup logic
lives in one place (runnable by hand, by a scheduled task, or by Prefect). The
spec is ``docs/BACKUP.md`` — TimescaleDB ``pg_dump -Fc``, Qdrant snapshots, an
encrypted ``.env`` copy, and retention pruning.

Scheduled for 01:00 IST daily (the parent registers the deployment in
``schedules/deploy.py`` — this module deliberately does not).

The flow is forgiving about *reaching* the script but strict about its result:
a non-zero exit (e.g. ``pg_dump`` failed) raises so the run is marked failed and
the skipped-task watchdog can page. A Telegram alert is emitted either way.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert


# backend/pfip/prefect/flows/backup_daily.py -> repo root is four parents up.
_ROOT = Path(__file__).resolve().parents[4]
_BACKUP_SCRIPT = _ROOT / "scripts" / "backup.py"


@flow(name="backup-daily", log_prints=True)
async def backup_daily(retention_days: int = 30, skip_qdrant: bool = False) -> dict[str, Any]:
    """Run ``scripts/backup.py`` and alert on the outcome."""
    logger = get_run_logger()

    if not _BACKUP_SCRIPT.is_file():
        logger.error("backup script missing at {}", _BACKUP_SCRIPT)
        await send_alert(
            kind=AlertKind.SYSTEM_HEALTH,
            severity=AlertSeverity.WARN,
            title_override="Nightly backup could not start",
            body_override=f"⚠️ backup.py not found at `{_BACKUP_SCRIPT}`.",
        )
        return {"status": "script-missing", "script": str(_BACKUP_SCRIPT)}

    cmd = [
        sys.executable,
        str(_BACKUP_SCRIPT),
        "--retention-days",
        str(retention_days),
    ]
    if skip_qdrant:
        cmd.append("--skip-qdrant")

    logger.info("running {}", " ".join(cmd))
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if proc.stdout:
        logger.info(proc.stdout.strip())
    if proc.stderr:
        logger.warning(proc.stderr.strip())

    if proc.returncode == 0:
        await send_alert(
            kind=AlertKind.SYSTEM_HEALTH,
            severity=AlertSeverity.INFO,
            title_override="Nightly backup OK",
            body_override="✅ PFIP nightly backup completed.",
        )
        return {"status": "ok", "returncode": 0}

    # Non-zero: surface it so the run fails and the watchdog notices.
    tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-5:]
    await send_alert(
        kind=AlertKind.SYSTEM_HEALTH,
        severity=AlertSeverity.WARN,
        title_override="Nightly backup FAILED",
        body_override=(
            f"❌ PFIP nightly backup exited {proc.returncode}.\n\n"
            + "\n".join(tail)
        ),
    )
    raise RuntimeError(f"backup.py exited {proc.returncode}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(backup_daily())
