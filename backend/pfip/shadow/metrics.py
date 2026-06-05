"""Shadow-vs-actual performance metrics.

Computes Sharpe, max drawdown, hit rate, and win rate for both the shadow
portfolio and the live one, given their respective ledger tables. Pure
pandas/numpy; designed to be called either from a Prefect flow (post-MtM) or
from the FastAPI ``/shadow/vs-actual`` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

import numpy as np
import pandas as pd
from sqlalchemy import asc, select

from pfip.backtest.vectorbt_engine import _hit_rate, _max_drawdown, _sharpe


@dataclass
class ShadowMetrics:
    """Headline stats for either the shadow or the actual book."""

    sharpe: float
    max_drawdown: float
    hit_rate: float
    win_rate: float
    n_trades: int
    total_return: float
    final_equity_inr: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _trade_returns_from_lots(rows: Iterable) -> pd.Series:
    """Convert closed lots into a series of trade returns."""
    out: list[float] = []
    for r in rows:
        if r.cost_basis_inr is None or r.qty in (None, 0) or r.closed_at is None:
            continue
        exit_price = r.exit_price_inr
        if exit_price is None:
            continue
        cost = float(r.cost_basis_inr)
        exit_value = float(r.qty) * float(exit_price)
        if cost <= 0:
            continue
        out.append((exit_value - cost) / cost)
    return pd.Series(out, dtype=float)


def _equity_curve(tx_rows: list, mtm_value: Decimal) -> pd.Series:
    """Cumulative net flows + final mark-to-market = equity curve.

    For each tx we add (BUY -> cash_out, SELL -> cash_in). The final row is the
    current MtM equity so the curve ends at "today".
    """
    if not tx_rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(
        [
            {
                "time": t.time,
                "delta": (-1 if t.kind == "BUY" else 1) * float(t.amount_inr),
            }
            for t in tx_rows
        ]
    ).sort_values("time")
    df["equity"] = df["delta"].cumsum() + float(mtm_value)
    df = df.set_index("time")
    return df["equity"]


async def compute_shadow_metrics(session) -> ShadowMetrics:
    """Compute the shadow portfolio's headline stats."""
    from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow

    closed_stmt = select(ShadowHoldingRow).where(ShadowHoldingRow.closed_at.is_not(None))
    closed = list((await session.execute(closed_stmt)).scalars().all())

    tx_stmt = select(ShadowPortfolioTxRow).order_by(asc(ShadowPortfolioTxRow.time))
    txs = list((await session.execute(tx_stmt)).scalars().all())

    open_stmt = select(ShadowHoldingRow).where(ShadowHoldingRow.closed_at.is_(None))
    open_rows = list((await session.execute(open_stmt)).scalars().all())
    mtm = sum((h.cost_basis_inr or Decimal(0) for h in open_rows), Decimal(0))

    return _metrics_from(closed, txs, mtm)


async def compute_actual_metrics(session) -> ShadowMetrics:
    """Same shape, but for the live portfolio."""
    from pfip.models.holdings import HoldingRow
    from pfip.models.portfolio_tx import PortfolioTxRow

    closed_stmt = select(HoldingRow).where(HoldingRow.closed_at.is_not(None))
    closed = list((await session.execute(closed_stmt)).scalars().all())

    tx_stmt = select(PortfolioTxRow).order_by(asc(PortfolioTxRow.time))
    txs = list((await session.execute(tx_stmt)).scalars().all())

    open_stmt = select(HoldingRow).where(HoldingRow.closed_at.is_(None))
    open_rows = list((await session.execute(open_stmt)).scalars().all())
    mtm = sum((h.cost_basis_inr or Decimal(0) for h in open_rows), Decimal(0))

    return _metrics_from(closed, txs, mtm)


def _metrics_from(closed: list, txs: list, mtm: Decimal) -> ShadowMetrics:
    trade_returns = _trade_returns_from_lots(closed)
    equity = _equity_curve(txs, mtm)

    # Daily-ish returns from equity curve.
    if not equity.empty:
        eq_daily = equity.resample("D").last().ffill()
        daily_ret = eq_daily.pct_change().dropna()
    else:
        daily_ret = pd.Series(dtype=float)

    return ShadowMetrics(
        sharpe=_sharpe(daily_ret),
        max_drawdown=_max_drawdown(daily_ret),
        hit_rate=_hit_rate(trade_returns),
        win_rate=float((trade_returns > 0).mean()) if not trade_returns.empty else 0.0,
        n_trades=int(len(trade_returns)),
        total_return=float((1.0 + daily_ret).prod() - 1.0) if not daily_ret.empty else 0.0,
        final_equity_inr=float(equity.iloc[-1]) if not equity.empty else float(mtm),
    )


async def shadow_vs_actual(session) -> dict[str, object]:
    """Side-by-side dict comparing shadow and actual metrics."""
    shadow = await compute_shadow_metrics(session)
    actual = await compute_actual_metrics(session)
    return {
        "shadow": shadow.as_dict(),
        "actual": actual.as_dict(),
        "delta": {
            "sharpe": shadow.sharpe - actual.sharpe,
            "max_drawdown": shadow.max_drawdown - actual.max_drawdown,
            "hit_rate": shadow.hit_rate - actual.hit_rate,
            "total_return": shadow.total_return - actual.total_return,
            "equity_inr": shadow.final_equity_inr - actual.final_equity_inr,
        },
    }
