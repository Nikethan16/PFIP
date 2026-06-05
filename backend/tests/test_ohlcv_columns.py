"""Regression guard for OHLCVRow timestamp column / ``ts`` synonym.

Several call sites reference ``OHLCVRow.ts`` (a synonym for the real ``time``
column). This test compiles a projection / filter / ordering query so the
``ts`` attribute can never silently disappear and raise AttributeError at
query-build time in production again.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from pfip.models.ohlcv import OHLCVRow


def test_ts_synonym_projection_compiles() -> None:
    stmt = select(OHLCVRow.ts)
    assert "time" in str(stmt.compile())


def test_ts_synonym_where_and_order_by_compile() -> None:
    cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
    stmt = (
        select(OHLCVRow.close, OHLCVRow.ts)
        .where(OHLCVRow.ts >= cutoff)
        .order_by(OHLCVRow.ts.desc())
    )
    compiled = str(stmt.compile())
    assert "ohlcv.time" in compiled
    assert "ORDER BY" in compiled


def test_time_and_ts_are_same_column() -> None:
    # Both attributes must resolve to the underlying ``time`` column.
    assert OHLCVRow.ts.property.columns[0] is OHLCVRow.time.property.columns[0]
