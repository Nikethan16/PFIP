"""Real-DB test for the OHLCV ``ON CONFLICT`` upsert idempotency.

``upsert_ohlcv_rows`` issues ``INSERT ... ON CONFLICT (time, symbol, source,
timeframe) DO NOTHING``. The conflict target must match the real composite PK on
the ``ohlcv`` table — a fake session can't verify that. Here we run the upsert
twice and assert the second run inserts no duplicates (idempotent re-ingest).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from pfip.ingest._common.upsert import upsert_ohlcv_rows
from pfip.models.ohlcv import OHLCVRow
from tests.integration._harness import require_db

pytestmark = pytest.mark.integration

# Skip the whole module cleanly when no Postgres (env URL or Docker) is available.
require_db()


def _rows():
    base = datetime(2026, 3, 1, tzinfo=UTC)
    return [
        {
            "time": base.replace(day=d),
            "symbol": "RELIANCE",
            "market": "nse",
            "source": "test",
            "timeframe": "1d",
            "open": 100 + d,
            "high": 105 + d,
            "low": 99 + d,
            "close": 102 + d,
            "volume": 1000 * d,
        }
        for d in (1, 2, 3)
    ]


async def _count(db) -> int:
    return (await db.execute(select(func.count()).select_from(OHLCVRow))).scalar_one()


async def test_ohlcv_upsert_is_idempotent(db_session) -> None:
    rows = _rows()

    # First ingest inserts all 3.
    n1 = await upsert_ohlcv_rows(db_session, rows)
    assert n1 == 3
    assert await _count(db_session) == 3

    # Second ingest of the SAME rows: ON CONFLICT DO NOTHING -> no new rows.
    n2 = await upsert_ohlcv_rows(db_session, rows)
    # The helper counts attempted rows (3) but the table must not grow.
    assert n2 == 3
    assert await _count(db_session) == 3


async def test_ohlcv_upsert_does_not_overwrite_existing(db_session) -> None:
    """DO NOTHING (not DO UPDATE): a conflicting re-ingest keeps the original
    close, even if the new payload carries a different value."""
    rows = _rows()
    await upsert_ohlcv_rows(db_session, rows)

    # Re-ingest the first key with a mutated close.
    mutated = dict(rows[0])
    mutated["close"] = 999.0
    await upsert_ohlcv_rows(db_session, [mutated])

    stmt = select(OHLCVRow.close).where(
        OHLCVRow.symbol == "RELIANCE",
        OHLCVRow.time == rows[0]["time"],
        OHLCVRow.source == "test",
        OHLCVRow.timeframe == "1d",
    )
    close = (await db_session.execute(stmt)).scalar_one()
    # Original 103 (= 102 + day 1) preserved; the 999 update was ignored.
    assert float(close) == 103.0
    assert await _count(db_session) == 3
