"""Seed a realistic DUMMY *paper* portfolio for testing / learning.

This is the "test the whole app without real money" seed. It inserts holdings +
opening BUY transactions (tagged ``broker='PAPER'`` / ``note='paper-seed'``) so the
entire analytics surface — net-worth, benchmark, stress, tax (cost basis / cap
gains), goals — renders real numbers. It uses **real watchlist symbols** so
mark-to-market, FX, and benchmark all work against the live OHLCV.

Idempotent: clears prior PAPER rows, then re-inserts. Remove with
``DELETE FROM holdings WHERE broker='PAPER'`` (+ the tagged tx).

Run on the VM:
    cd ~/pfip/backend && PYTHONPATH=$PWD ./.venv/bin/python -m scripts.seed_paper_portfolio
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from pfip.db.session import get_sessionmaker
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow

_BROKER = "PAPER"

# A small, realistic India-centric learning portfolio (~₹6L).
# (symbol, category, qty, unit_cost, ccy, fx_rate, acquired_date)
LOTS: list[tuple] = [
    ("RELIANCE.NS", "equity", "12", "2450", "INR", None, "2025-01-15"),
    ("TCS.NS", "equity", "6", "3600", "INR", None, "2025-03-10"),
    ("HDFCBANK.NS", "equity", "18", "1550", "INR", None, "2025-02-20"),
    ("INFY.NS", "equity", "14", "1450", "INR", None, "2025-06-05"),
    ("NIFTYBEES.NS", "etf", "100", "235", "INR", None, "2024-11-01"),
    ("AAPL", "equity", "6", "190", "USD", "83", "2024-09-12"),
    ("NVDA", "equity", "4", "115", "USD", "84", "2025-04-22"),
    ("BTC-USD", "crypto_exchange", "0.03", "62000", "USD", "84", "2024-10-08"),
    ("ETH-USD", "crypto_exchange", "0.5", "2800", "USD", "84", "2025-01-30"),
]


async def main() -> None:
    factory = get_sessionmaker()
    async with factory() as s:
        # Idempotent clear of prior paper rows.
        await s.execute(text("DELETE FROM portfolio_tx WHERE note = 'paper-seed'"))
        await s.execute(text("DELETE FROM holdings WHERE broker = :b"), {"b": _BROKER})
        await s.commit()

        n = 0
        for sym, cat, qty, unit, ccy, fx, acq in LOTS:
            acq_dt = datetime.fromisoformat(acq).replace(tzinfo=UTC)
            qty_d = Decimal(qty)
            unit_d = Decimal(unit)
            fx_d = Decimal(fx) if fx else None
            cost_inr = (qty_d * unit_d * (fx_d or Decimal("1"))).quantize(Decimal("0.01"))
            hid = uuid.uuid4()
            s.add(
                HoldingRow(
                    id=hid,
                    category=cat,
                    symbol=sym,
                    broker=_BROKER,
                    acquired_at=acq_dt,
                    qty=qty_d,
                    cost_basis_inr=cost_inr,
                    cost_basis_ccy=ccy,
                    fx_rate=fx_d,
                    is_self_custody=False,
                    notes="paper-seed",
                )
            )
            s.add(
                PortfolioTxRow(
                    id=uuid.uuid4(),
                    holding_id=hid,
                    time=acq_dt,
                    kind="BUY",
                    qty=qty_d,
                    price=unit_d,
                    amount_inr=cost_inr,
                    fx_rate=fx_d,
                    note="paper-seed",
                )
            )
            n += 1
        await s.commit()

        row = (
            await s.execute(
                text(
                    "SELECT count(*), coalesce(sum(cost_basis_inr),0) "
                    "FROM holdings WHERE broker = :b"
                ),
                {"b": _BROKER},
            )
        ).fetchone()
        print(f"seeded {n} paper holdings | rows={row[0]} total_cost_inr={float(row[1]):,.0f}")


if __name__ == "__main__":
    asyncio.run(main())
