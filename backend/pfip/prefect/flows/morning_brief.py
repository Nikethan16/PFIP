"""Prefect flow: daily morning brief at 07:00 IST (01:30 UTC).

The composer lives in :func:`pfip.agent.morning_brief.build_morning_brief`.
This flow opens a DB session, drives the composer for today, persists the
rendered markdown to ``data/morning_brief/<date>.md`` and posts a Telegram INFO
with the path.

Run manually:

    python -m pfip.prefect.flows.morning_brief
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, get_run_logger

from pfip.agent.morning_brief import build_morning_brief
from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.db.session import get_sessionmaker

_OUT_DIR = Path("data/morning_brief")


@flow(name="morning-brief", log_prints=True)
async def morning_brief() -> str:
    """Compose + persist + alert the daily morning brief. Returns the file path."""
    logger = get_run_logger()
    target = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    factory = get_sessionmaker()
    async with factory() as db:
        md = await build_morning_brief(db, target)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / f"brief-{target.date().isoformat()}.md"
    out.write_text(md, encoding="utf-8")
    logger.info("morning brief written to {}", out)

    await send_alert(
        kind=AlertKind.SYSTEM_HEALTH,
        severity=AlertSeverity.INFO,
        title_override=f"Morning brief {target.date().isoformat()}",
        body_override=f"\U0001f4f0 Morning brief ready.\n\nFull markdown: `{out}`",
    )
    return str(out)


if __name__ == "__main__":
    asyncio.run(morning_brief())
