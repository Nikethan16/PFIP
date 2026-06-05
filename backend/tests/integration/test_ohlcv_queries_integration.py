"""Real-DB tests for the OHLCV query layer.

These exercise the exact statements that broke before: the ``OHLCVRow.ts``
synonym used in projection/ordering, the ``DISTINCT ON`` latest-close query in
``fetch_latest_closes``, and the trailing-window query in ``fetch_return_series``.
A fake session returns ``[]`` for all of them, so a regression here was invisible
until production. We assert on real result *values*, not just "no exception".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from pfip.models.ohlcv import OHLCVRow
from pfip.portfolio.marking import fetch_latest_closes, fetch_return_series
from tests.integration._harness import require_db

pytestmark = pytest.mark.integration

# Skip the whole module cleanly when no Postgres (env URL or Docker) is available.
require_db()


def _bar(symbol: str, market: str, ts: datetime, close: float) -> OHLCVRow:
    c = Decimal(str(close))
    return OHLCVRow(
        time=ts,
        symbol=symbol,
        market=market,
        source="test",
        timeframe="1d",
        open=c,
        high=c,
        low=c,
        close=c,
        volume=Decimal("100"),
    )


async def _seed(db, rows: list[OHLCVRow]) -> None:
    for r in rows:
        db.add(r)
    await db.commit()


async def test_ts_synonym_projection_and_ordering(db_session) -> None:
    """``OHLCVRow.ts`` (synonym for ``time``) must project, filter and order in
    real SQL. This is the literal column the synonym bug broke."""
    base = datetime(2026, 3, 1, tzinfo=UTC)
    await _seed(
        db_session,
        [
            _bar("RELIANCE", "nse", base + timedelta(days=0), 100.0),
            _bar("RELIANCE", "nse", base + timedelta(days=1), 101.0),
            _bar("RELIANCE", "nse", base + timedelta(days=2), 102.0),
        ],
    )

    # Project + order by the SYNONYM, not the underlying column.
    stmt = (
        select(OHLCVRow.ts, OHLCVRow.close)
        .where(OHLCVRow.symbol == "RELIANCE")
        .order_by(OHLCVRow.ts.desc())
    )
    rows = (await db_session.execute(stmt)).all()

    assert [float(r.close) for r in rows] == [102.0, 101.0, 100.0]
    # Newest first; ts really maps to the time column.
    assert rows[0].ts == base + timedelta(days=2)


async def test_fetch_latest_closes_distinct_on(db_session) -> None:
    """``fetch_latest_closes`` uses Postgres ``DISTINCT ON (symbol)`` ordered by
    ``time DESC`` — must return exactly one (latest) row per symbol."""
    base = datetime(2026, 3, 1, tzinfo=UTC)
    await _seed(
        db_session,
        [
            _bar("RELIANCE", "nse", base, 100.0),
            _bar("RELIANCE", "nse", base + timedelta(days=1), 110.0),
            _bar("AAPL", "us_equity", base, 200.0),
            _bar("AAPL", "us_equity", base + timedelta(days=2), 220.0),
        ],
    )

    latest = await fetch_latest_closes(db_session, ["RELIANCE", "AAPL", "MISSING"])

    assert set(latest) == {"RELIANCE", "AAPL"}  # MISSING absent, not errored
    rel_close, rel_market, rel_ts = latest["RELIANCE"]
    aapl_close, aapl_market, aapl_ts = latest["AAPL"]
    assert rel_close == Decimal("110.00000000")
    assert rel_market == "nse"
    assert rel_ts == base + timedelta(days=1)
    assert aapl_close == Decimal("220.00000000")
    assert aapl_ts == base + timedelta(days=2)


async def test_fetch_return_series_window(db_session) -> None:
    """``fetch_return_series`` keeps only bars within the trailing window and
    returns N-1 log-returns for N in-window closes."""
    now = datetime.now(tz=UTC)
    rows = [
        # 4 recent daily bars -> 3 log-returns.
        _bar("RELIANCE", "nse", now - timedelta(days=3), 100.0),
        _bar("RELIANCE", "nse", now - timedelta(days=2), 102.0),
        _bar("RELIANCE", "nse", now - timedelta(days=1), 101.0),
        _bar("RELIANCE", "nse", now - timedelta(hours=1), 103.0),
        # An ancient bar far outside the window must be excluded by the SQL.
        _bar("RELIANCE", "nse", now - timedelta(days=400), 1.0),
    ]
    await _seed(db_session, rows)

    series = await fetch_return_series(db_session, ["RELIANCE"], window_days=90)

    assert "RELIANCE" in series
    # 4 in-window closes -> 3 returns; the 400-day-old bar is filtered out.
    assert len(series["RELIANCE"]) == 3
    # Sanity: first return is log(102/100) > 0.
    assert series["RELIANCE"][0] > 0
