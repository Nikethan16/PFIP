"""Drawdown math + nav_history derivation tests for PortfolioService.

Covers:
  * peak-to-current drawdown computed from a synthetic NAV series via
    ``portfolio_summary(nav_history=...)``.
  * ``nav_history`` empty-case (no ledger rows ⇒ empty list ⇒ drawdown 0).
  * ``nav_history`` deriving a cumulative-net-flow series from portfolio_tx.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.portfolio.service import PortfolioService


class _EmptyScalars:
    def all(self):
        return []

    def first(self):
        return None


class _RowsScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, scalars) -> None:  # noqa: ANN001
        self._scalars = scalars

    def scalars(self):
        return self._scalars


class _EmptySession:
    """execute() always yields no rows."""

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _Result(_EmptyScalars())


class _TxSession:
    """execute() yields the seeded portfolio_tx rows for any query."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _Result(_RowsScalars(self._rows))


# ---------------------------------------------------------------------------
# Drawdown math (via portfolio_summary)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drawdown_peak_to_current() -> None:
    svc = PortfolioService(_EmptySession())
    # NAV rises to a peak of 120, then falls to 90 ⇒ DD = 1 - 90/120 = 0.25.
    base = date(2026, 1, 1)
    nav = [
        (base, Decimal("100")),
        (base + timedelta(days=1), Decimal("120")),
        (base + timedelta(days=2), Decimal("110")),
        (base + timedelta(days=3), Decimal("90")),
    ]
    summary = await svc.portfolio_summary(nav_history=nav)
    assert summary.drawdown == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_drawdown_zero_when_at_new_high() -> None:
    svc = PortfolioService(_EmptySession())
    base = date(2026, 1, 1)
    nav = [
        (base, Decimal("100")),
        (base + timedelta(days=1), Decimal("130")),  # current is the peak
    ]
    summary = await svc.portfolio_summary(nav_history=nav)
    assert summary.drawdown == 0.0


@pytest.mark.asyncio
async def test_drawdown_zero_without_nav_history() -> None:
    svc = PortfolioService(_EmptySession())
    summary = await svc.portfolio_summary(nav_history=None)
    assert summary.drawdown == 0.0
    summary_empty = await svc.portfolio_summary(nav_history=[])
    assert summary_empty.drawdown == 0.0


# ---------------------------------------------------------------------------
# nav_history derivation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nav_history_empty_returns_empty_list() -> None:
    svc = PortfolioService(_EmptySession())
    assert await svc.nav_history() == []


@pytest.mark.asyncio
async def test_nav_history_cumulative_net_flow() -> None:
    now = datetime.now(tz=timezone.utc)
    rows = [
        PortfolioTxRow(
            time=now - timedelta(days=3),
            kind="BUY",
            amount_inr=Decimal("1000"),
        ),
        PortfolioTxRow(
            time=now - timedelta(days=2),
            kind="SELL",
            amount_inr=Decimal("400"),
        ),
        PortfolioTxRow(
            time=now - timedelta(days=1),
            kind="DIVIDEND",
            amount_inr=Decimal("50"),
        ),
    ]
    svc = PortfolioService(_TxSession(rows))
    series = await svc.nav_history(days=365)
    # Ascending by date; running net flow: -1000, then -600, then -550.
    assert [v for _, v in series] == [
        Decimal("-1000"),
        Decimal("-600"),
        Decimal("-550"),
    ]
    # Dates ascending.
    dates = [d for d, _ in series]
    assert dates == sorted(dates)
