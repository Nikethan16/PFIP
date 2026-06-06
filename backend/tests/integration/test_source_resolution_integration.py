"""Real-DB tests for OHLCV source resolution and the feature write that depends on it.

The bug: scheduled compute-features / regime flows guessed the OHLCV ``source``
from a static heuristic (US -> ``yfinance``), but US equities are ingested under
``tiingo`` — so the reads matched 0 rows and SPY/NVDA got no features/regime.

These exercise the *real* SQL of :func:`pfip.db.sources.resolve_ohlcv_source`
(its ``GROUP BY source ORDER BY count(*) DESC`` is invisible to a fake session)
and prove that, with the resolved source, the feature pipeline actually writes
rows for a US equity — while the old heuristic source writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from pfip.db.sources import resolve_ohlcv_source
from pfip.features.runner import FeatureRunRequest, compute_and_persist
from pfip.models.features import FeatureRow
from pfip.models.ohlcv import OHLCVRow
from tests.integration._harness import require_db

pytestmark = pytest.mark.integration

# Skip the whole module cleanly when no Postgres (env URL or Docker) is available.
require_db()


def _bar(symbol: str, source: str, ts: datetime, close: float) -> OHLCVRow:
    c = Decimal(str(close))
    return OHLCVRow(
        time=ts,
        symbol=symbol,
        market="us_equity",
        source=source,
        timeframe="1d",
        open=c,
        high=c + Decimal("1"),
        low=c - Decimal("1"),
        close=c,
        volume=Decimal("1000"),
    )


async def _seed(db, rows: list[OHLCVRow]) -> None:
    for r in rows:
        db.add(r)
    await db.commit()


async def test_resolve_prefers_source_with_most_rows(db_session) -> None:
    """SPY has a full 'tiingo' history plus a single, *more recent* 'yfinance'
    stray. The resolver must pick 'tiingo' (most rows) — not the newest bar."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _seed(
        db_session,
        [_bar("SPY", "tiingo", base + timedelta(days=i), 400.0 + i) for i in range(5)]
        # one stray yfinance bar that is the most recent of all:
        + [_bar("SPY", "yfinance", base + timedelta(days=10), 410.0)],
    )

    src = await resolve_ohlcv_source(db_session, "SPY", "1d")
    assert src == "tiingo"


async def test_resolve_tiebreak_is_most_recent(db_session) -> None:
    """Equal row counts -> the source with the most recent bar wins."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _seed(
        db_session,
        [
            _bar("FOO", "older_src", base + timedelta(days=0), 10.0),
            _bar("FOO", "older_src", base + timedelta(days=1), 11.0),
            _bar("FOO", "newer_src", base + timedelta(days=2), 12.0),
            _bar("FOO", "newer_src", base + timedelta(days=3), 13.0),
        ],
    )

    src = await resolve_ohlcv_source(db_session, "FOO", "1d")
    assert src == "newer_src"


async def test_resolve_none_for_unknown_symbol(db_session) -> None:
    src = await resolve_ohlcv_source(db_session, "NO_SUCH_SYMBOL", "1d")
    assert src is None


async def test_features_written_under_resolved_source_not_heuristic(db_session) -> None:
    """End-to-end: with the OLD heuristic source ('yfinance') the feature run
    reads 0 rows and writes nothing; with the RESOLVED source ('tiingo') it
    writes a full set. This is the exact SPY/NVDA failure and its fix."""
    await db_session.execute(text("TRUNCATE TABLE features"))
    await db_session.commit()

    base = datetime(2026, 1, 1, tzinfo=UTC)
    n_bars = 60
    await _seed(
        db_session,
        [_bar("SPY", "tiingo", base + timedelta(days=i), 400.0 + i) for i in range(n_bars)],
    )

    # 1) The buggy heuristic source has no rows -> nothing written.
    buggy = await compute_and_persist(
        db_session,
        FeatureRunRequest(symbol="SPY", source="yfinance", timeframe="1d", write_extras=False),
    )
    assert buggy.rows_read == 0
    assert buggy.rows_written == 0

    # 2) The resolver finds the real source...
    resolved = await resolve_ohlcv_source(db_session, "SPY", "1d")
    assert resolved == "tiingo"

    # 3) ...and computing against it writes the full feature set.
    fixed = await compute_and_persist(
        db_session,
        FeatureRunRequest(symbol="SPY", source=resolved, timeframe="1d", write_extras=False),
    )
    assert fixed.rows_read == n_bars
    assert fixed.rows_written == n_bars

    # The persisted feature rows are all under 'tiingo', none under 'yfinance'.
    persisted = (
        await db_session.execute(
            select(FeatureRow.source).where(FeatureRow.symbol == "SPY").distinct()
        )
    ).scalars().all()
    assert persisted == ["tiingo"]
