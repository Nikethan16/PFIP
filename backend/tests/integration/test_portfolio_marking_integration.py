"""Real-DB tests for portfolio mark-to-market + FX conversion.

Covers the FX-rate bug class: an INR holding marked directly from OHLCV, a USD
holding converted to INR via the ``fx_rates`` table, and a USD holding with NO
fx row that must *abstain* (land in ``unmarked`` with reason ``no_fx_rate``)
rather than silently use a wrong/stale rate. Also exercises
``correlation_matrix`` end-to-end through the service from a real return series.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from pfip.models.holdings import HoldingRow
from pfip.models.ohlcv import OHLCVRow
from pfip.portfolio.marking import build_marking, fetch_return_series
from pfip.portfolio.service import PortfolioService
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


def _holding(symbol: str, ccy: str, qty: float = 1.0) -> HoldingRow:
    return HoldingRow(
        id=uuid.uuid4(),
        category="equity",
        symbol=symbol,
        acquired_at=datetime(2025, 1, 1, tzinfo=UTC),
        qty=Decimal(str(qty)),
        cost_basis_inr=Decimal("1000"),
        cost_basis_ccy=ccy,
        is_self_custody=False,
    )


async def _insert_fx(db, base: str, on: date, rate: float) -> None:
    await db.execute(
        text(
            "INSERT INTO fx_rates (rate_date, base, quote, rate, source) "
            "VALUES (:d, :b, 'INR', :r, 'test')"
        ),
        {"d": on, "b": base, "r": Decimal(str(rate))},
    )
    await db.commit()


async def test_build_marking_inr_and_usd_with_fx(db_session) -> None:
    """INR holding marked directly; USD holding converted via fx_rates."""
    now = datetime.now(tz=UTC)
    # OHLCV: INR symbol (close in INR) + USD symbol (close in USD).
    db_session.add(_bar("RELIANCE", "nse", now, 2500.0))
    db_session.add(_bar("AAPL", "us_equity", now, 200.0))
    await db_session.commit()

    # USD->INR rate effective today.
    await _insert_fx(db_session, "USD", date.today(), 84.0)

    holdings = [_holding("RELIANCE", "INR"), _holding("AAPL", "USD")]
    result = await build_marking(db_session, holdings)

    assert set(result.marked) == {"RELIANCE", "AAPL"}
    assert result.unmarked == []
    # INR marked at face close.
    assert result.mark_prices["RELIANCE"] == Decimal("2500")
    # USD converted: 200 * 84 = 16800.
    assert result.mark_prices["AAPL"] == Decimal("16800.0000")
    assert result.usdinr == Decimal("84.00000000")


async def test_build_marking_usd_without_fx_abstains(db_session) -> None:
    """A USD holding with NO fx_rates row must abstain → unmarked/no_fx_rate."""
    now = datetime.now(tz=UTC)
    db_session.add(_bar("AAPL", "us_equity", now, 200.0))
    await db_session.commit()
    # Deliberately insert NO fx_rates row.

    holdings = [_holding("AAPL", "USD")]
    result = await build_marking(db_session, holdings)

    assert "AAPL" not in result.mark_prices
    assert result.marked == []
    reasons = {u["symbol"]: u["reason"] for u in result.unmarked}
    assert reasons == {"AAPL": "no_fx_rate"}
    assert result.usdinr is None


async def test_correlation_matrix_end_to_end(db_session) -> None:
    """fetch_return_series -> PortfolioService.correlation_matrix shape check."""
    now = datetime.now(tz=UTC)
    # Two symbols, several daily bars each so each has >= 2 returns.
    for i, (px_a, px_b) in enumerate([(100, 200), (101, 198), (102, 202), (103, 199), (104, 205)]):
        ts = now - timedelta(days=5 - i)
        db_session.add(_bar("RELIANCE", "nse", ts, float(px_a)))
        db_session.add(_bar("INFY", "nse", ts, float(px_b)))
    await db_session.commit()

    series = await fetch_return_series(db_session, ["RELIANCE", "INFY"], window_days=90)
    assert set(series) == {"RELIANCE", "INFY"}

    svc = PortfolioService(db_session)
    corr = await svc.correlation_matrix(series, window_days=90)

    # Square matrix over both symbols; diagonal == 1.0.
    assert set(corr) == {"RELIANCE", "INFY"}
    assert set(corr["RELIANCE"]) == {"RELIANCE", "INFY"}
    assert corr["RELIANCE"]["RELIANCE"] == pytest.approx(1.0)
    assert corr["INFY"]["INFY"] == pytest.approx(1.0)
    # Symmetric.
    assert corr["RELIANCE"]["INFY"] == pytest.approx(corr["INFY"]["RELIANCE"])
