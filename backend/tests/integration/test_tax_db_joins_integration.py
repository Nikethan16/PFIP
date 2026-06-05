"""Real-DB test for the tax summary join + FY date filter.

``_fetch_enriched_tx(db, fy)`` joins ``holdings`` to ``portfolio_tx`` and pushes
the FY date bounds into the ``portfolio_tx.time`` WHERE clause. With a fake
session this filter was never executed, so an off-by-one / wrong-column FY bound
would slip through. Here we seed tx across two financial years and assert the SQL
filter actually limits rows to the requested FY.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pfip.api.tax import _fetch_enriched_tx
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow
from tests.integration._harness import require_db

pytestmark = pytest.mark.integration

# Skip the whole module cleanly when no Postgres (env URL or Docker) is available.
require_db()


async def _seed_two_fys(db) -> uuid.UUID:
    """One holding with a BUY in FY 2025-26 and a SELL in FY 2026-27."""
    hid = uuid.uuid4()
    db.add(
        HoldingRow(
            id=hid,
            category="equity",
            symbol="RELIANCE",
            acquired_at=datetime(2025, 6, 1, tzinfo=UTC),
            qty=Decimal("10"),
            cost_basis_inr=Decimal("10000"),
            cost_basis_ccy="INR",
            is_self_custody=False,
        )
    )
    # FY 2025-26 (Apr 2025 - Mar 2026): a BUY in Jun 2025.
    db.add(
        PortfolioTxRow(
            id=uuid.uuid4(),
            holding_id=hid,
            time=datetime(2025, 6, 1, tzinfo=UTC),
            kind="BUY",
            qty=Decimal("10"),
            price=Decimal("1000"),
            amount_inr=Decimal("10000"),
            tax_withheld=Decimal("0"),
        )
    )
    # FY 2026-27 (Apr 2026 - Mar 2027): a SELL in Jun 2026.
    db.add(
        PortfolioTxRow(
            id=uuid.uuid4(),
            holding_id=hid,
            time=datetime(2026, 6, 1, tzinfo=UTC),
            kind="SELL",
            qty=Decimal("10"),
            price=Decimal("1200"),
            amount_inr=Decimal("12000"),
            tax_withheld=Decimal("0"),
        )
    )
    await db.commit()
    return hid


async def test_fy_filter_limits_rows_in_sql(db_session) -> None:
    await _seed_two_fys(db_session)

    # No FY filter -> both tx come back.
    all_tx = await _fetch_enriched_tx(db_session, None)
    kinds_all = sorted(t["kind"] for t in all_tx)
    assert kinds_all == ["BUY", "SELL"]

    # FY 2025-26 -> only the BUY (Jun 2025) survives the SQL WHERE.
    fy_2526 = await _fetch_enriched_tx(db_session, "2025-26")
    assert [t["kind"] for t in fy_2526] == ["BUY"]
    assert fy_2526[0]["time"].year == 2025

    # FY 2026-27 -> only the SELL (Jun 2026) survives.
    fy_2627 = await _fetch_enriched_tx(db_session, "2026-27")
    assert [t["kind"] for t in fy_2627] == ["SELL"]
    assert fy_2627[0]["time"].year == 2026


async def test_fy_filter_excludes_boundary_neighbours(db_session) -> None:
    """A tx on 2026-03-31 is FY2025-26; on 2026-04-01 is FY2026-27. The SQL
    bounds must place each on the correct side of the Apr-1 boundary."""
    hid = uuid.uuid4()
    db_session.add(
        HoldingRow(
            id=hid,
            category="equity",
            symbol="INFY",
            acquired_at=datetime(2026, 3, 31, tzinfo=UTC),
            qty=Decimal("5"),
            cost_basis_inr=Decimal("5000"),
            cost_basis_ccy="INR",
            is_self_custody=False,
        )
    )
    db_session.add(
        PortfolioTxRow(
            id=uuid.uuid4(),
            holding_id=hid,
            time=datetime(2026, 3, 31, 12, 0, tzinfo=UTC),
            kind="BUY",
            qty=Decimal("5"),
            price=Decimal("1000"),
            amount_inr=Decimal("5000"),
            tax_withheld=Decimal("0"),
        )
    )
    db_session.add(
        PortfolioTxRow(
            id=uuid.uuid4(),
            holding_id=hid,
            time=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            kind="SELL",
            qty=Decimal("5"),
            price=Decimal("1100"),
            amount_inr=Decimal("5500"),
            tax_withheld=Decimal("0"),
        )
    )
    await db_session.commit()

    fy_2526 = await _fetch_enriched_tx(db_session, "2025-26")
    assert [t["kind"] for t in fy_2526] == ["BUY"]

    fy_2627 = await _fetch_enriched_tx(db_session, "2026-27")
    assert [t["kind"] for t in fy_2627] == ["SELL"]
