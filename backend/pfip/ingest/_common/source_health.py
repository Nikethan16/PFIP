"""Per-adapter health reporting — writes to ``source_health`` table.

Each ingest run should call ``record_run`` once at the end (success or failure).
The table is created by migration 0006. If the table does not exist (older DB)
we log a warning and silently skip — the rest of the ingest must still work.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Awaitable, Callable, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker

log = get_logger("pfip.ingest._common.source_health")

T = TypeVar("T")


async def record_run(
    source: str,
    *,
    rows: int,
    error: str | None = None,
    session: AsyncSession | None = None,
) -> None:
    """Upsert a row in ``source_health`` for the given source.

    On success: bumps last_success_at, resets consecutive_failures to 0.
    On failure: increments consecutive_failures, stores last_error.
    """
    now = datetime.now(timezone.utc)
    # Explicit ::text cast on the `err` parameter — psycopg3 cannot infer its
    # data type from the surrounding CASE WHEN ... IS NULL alone (every column
    # branch is NULL or compared to NULL), which yields "AmbiguousParameter".
    # Casting once at first use propagates the type to every subsequent
    # reference of the named parameter.
    stmt = text("""
        INSERT INTO source_health (
            source, last_run_at, last_success_at, last_rows, last_error,
            consecutive_failures, updated_at
        )
        VALUES (
            :source, :now,
            CASE WHEN CAST(:err AS text) IS NULL THEN :now ELSE NULL END,
            :rows, CAST(:err AS text),
            CASE WHEN CAST(:err AS text) IS NULL THEN 0 ELSE 1 END,
            :now
        )
        ON CONFLICT (source) DO UPDATE SET
            last_run_at = EXCLUDED.last_run_at,
            last_success_at = CASE
                WHEN EXCLUDED.last_error IS NULL THEN EXCLUDED.last_run_at
                ELSE source_health.last_success_at
            END,
            last_rows = EXCLUDED.last_rows,
            last_error = EXCLUDED.last_error,
            consecutive_failures = CASE
                WHEN EXCLUDED.last_error IS NULL THEN 0
                ELSE source_health.consecutive_failures + 1
            END,
            updated_at = EXCLUDED.updated_at
        """)
    params = {"source": source, "now": now, "rows": int(rows), "err": error}
    try:
        if session is None:
            factory = get_sessionmaker()
            async with factory() as s:
                await s.execute(stmt, params)
                await s.commit()
        else:
            await session.execute(stmt, params)
            await session.commit()
    except Exception as e:  # noqa: BLE001 — table may not exist on older DB
        log.warning(f"source_health record_run({source}) failed: {type(e).__name__}: {e}")


@contextlib.asynccontextmanager
async def track(source: str):
    """Context manager that records source_health regardless of outcome.

    Usage::

        async with track("amfi") as ctx:
            ctx.rows = await ingest_amfi_nav()
    """

    class _Ctx:
        rows: int = 0

    ctx = _Ctx()
    err: str | None = None
    try:
        yield ctx
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        await record_run(source, rows=int(getattr(ctx, "rows", 0) or 0), error=err)
