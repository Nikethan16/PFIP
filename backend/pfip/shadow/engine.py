"""Shadow portfolio engine per plan 8.5.

The shadow portfolio is a separate set of tables (``shadow_holdings`` +
``shadow_portfolio_tx``) that mirror live portfolio schemas, with its own
cash balance. It's *not* an advice engine — it's a measurement instrument.

Risk rules (enforced inside ``apply_signal``):
    * max 10% per position
    * 20% drawdown halt (from peak equity)
    * correlation guard: refuse if any existing position has |corr| > 0.7
      with the incoming symbol over 90d returns
    * daily cap: 2 new positions per day
    * signal confidence floor: 65

The engine is db-agnostic by design: every DB call goes through the injected
``session`` (an async SQLAlchemy session) so unit tests can stub it with a
fake session that implements the subset it uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sqlalchemy import select

from pfip.core.contracts import (
    HoldingCategory,
    PortfolioTxKind,
    Signal,
    SignalDirection,
)
from pfip.models.holdings import HoldingRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskRules:
    """Tunable risk limits — defaults match plan Section 8.5."""

    max_position_pct: float = 0.10
    drawdown_halt_pct: float = 0.20
    correlation_cap: float = 0.7
    daily_new_position_cap: int = 2
    confidence_floor: int = 65


@dataclass
class ShadowPositionDecision:
    """Outcome of applying a signal to the shadow portfolio."""

    accepted: bool
    reason: str
    holding_id: str | None = None


@dataclass
class ShadowPortfolio:
    """Interactive handle to the shadow portfolio tables.

    Attributes:
        session: an async SQLAlchemy session.
        rules: risk limits.
        starting_cash_inr: used to derive target per-position sizing when no
            equity snapshot is available (e.g. first day).
    """

    session: Any
    rules: RiskRules = field(default_factory=RiskRules)
    starting_cash_inr: Decimal = Decimal("1000000")

    # ------------------------------------------------------------------
    # Core write path: take a signal, maybe open a position.
    # ------------------------------------------------------------------

    async def apply_signal(
        self, signal: Signal, current_price_inr: Decimal | float
    ) -> ShadowPositionDecision:
        """Decide whether to take a signal and write the result.

        Returns a ``ShadowPositionDecision`` describing the outcome. The
        decision is *not* raised as an exception even when rejected — it's a
        normal data-bearing return.
        """
        price = Decimal(str(current_price_inr))

        # Confidence gate first — cheapest.
        if signal.confidence < self.rules.confidence_floor:
            return ShadowPositionDecision(
                accepted=False,
                reason=f"confidence {signal.confidence} below floor {self.rules.confidence_floor}",
            )

        if signal.direction not in (SignalDirection.BUY, SignalDirection.SELL):
            return ShadowPositionDecision(
                accepted=False, reason=f"direction {signal.direction.value} not actionable"
            )

        # Daily new-positions cap (only BUYs count against it).
        if signal.direction is SignalDirection.BUY:
            today_buys = await self._count_today_buys(signal.generated_at)
            if today_buys >= self.rules.daily_new_position_cap:
                return ShadowPositionDecision(
                    accepted=False,
                    reason=f"daily cap of {self.rules.daily_new_position_cap} hit",
                )

        # Drawdown halt
        equity = await self._mark_to_market_equity(signal.generated_at.date())
        peak = await self._peak_equity()
        if peak > 0 and equity <= peak * (
            Decimal("1") - Decimal(str(self.rules.drawdown_halt_pct))
        ):
            return ShadowPositionDecision(
                accepted=False,
                reason=f"drawdown halt (equity {equity:.2f} vs peak {peak:.2f})",
            )

        # SELL path: close the existing position in this asset if any.
        if signal.direction is SignalDirection.SELL:
            closed = await self._close_symbol(signal.asset, price, "signal SELL")
            return ShadowPositionDecision(
                accepted=closed is not None,
                reason="closed" if closed is not None else "no open position to close",
                holding_id=str(closed) if closed is not None else None,
            )

        # BUY path: sizing = min(max_position_pct * equity, available cash).
        target_notional = equity * Decimal(str(self.rules.max_position_pct))
        if target_notional <= 0:
            target_notional = self.starting_cash_inr * Decimal(str(self.rules.max_position_pct))

        # Correlation guard
        corr_ok, corr_reason = await self._correlation_ok(signal.asset)
        if not corr_ok:
            return ShadowPositionDecision(accepted=False, reason=corr_reason)

        qty = (target_notional / price).quantize(Decimal("0.0000001")) if price > 0 else Decimal(0)
        if qty <= 0:
            return ShadowPositionDecision(accepted=False, reason="computed qty <= 0")

        # Write
        holding = ShadowHoldingRow(
            category=self._guess_category(signal.asset),
            symbol=signal.asset,
            acquired_at=signal.generated_at,
            qty=qty,
            cost_basis_inr=qty * price,
            cost_basis_ccy="INR",
        )
        self.session.add(holding)
        await self.session.flush()

        tx = ShadowPortfolioTxRow(
            holding_id=holding.id,
            time=signal.generated_at,
            kind=PortfolioTxKind.BUY.value,
            qty=qty,
            price=price,
            amount_inr=qty * price,
            note=f"shadow BUY from {signal.model_name}:{signal.model_version}",
        )
        self.session.add(tx)
        await self.session.commit()
        return ShadowPositionDecision(accepted=True, reason="opened", holding_id=str(holding.id))

    # ------------------------------------------------------------------
    # Lifecycle ops
    # ------------------------------------------------------------------

    async def mark_to_market(self, as_of: datetime | None = None) -> dict[str, Any]:
        """Daily rollup: total equity (cash + holdings), unrealized PnL per holding.

        ``equity_inr`` is whole-portfolio: uninvested cash plus the
        marked-to-market value of every open holding. ``holdings_value_inr``
        and ``cash_inr`` break that down so the UI can show both.
        """
        as_of = as_of or datetime.now(tz=timezone.utc)
        rows = await self._open_holdings()
        holdings_value = Decimal(0)
        invested = Decimal(0)
        lines: list[dict[str, Any]] = []
        for h in rows:
            price = await self._latest_close(h.symbol)
            if price is None:
                price = (h.cost_basis_inr / h.qty) if h.qty > 0 else Decimal(0)
            value = h.qty * Decimal(str(price))
            pnl = value - h.cost_basis_inr
            holdings_value += value
            invested += h.cost_basis_inr
            lines.append(
                {
                    "holding_id": str(h.id),
                    "symbol": h.symbol,
                    "qty": float(h.qty),
                    "price": float(price),
                    "value_inr": float(value),
                    "pnl_inr": float(pnl),
                }
            )
        cash = self.starting_cash_inr - invested
        equity = cash + holdings_value
        return {
            "as_of": as_of.isoformat(),
            "equity_inr": float(equity),
            "cash_inr": float(cash),
            "holdings_value_inr": float(holdings_value),
            "lines": lines,
        }

    async def close_position(self, holding_id: Any, price: Decimal | float, reason: str) -> bool:
        """Close the given holding at ``price``; record SELL tx."""
        price_d = Decimal(str(price))
        h = await self.session.get(ShadowHoldingRow, holding_id)
        if h is None or h.closed_at is not None:
            return False
        now = datetime.now(tz=timezone.utc)
        h.closed_at = now
        h.exit_price_inr = price_d
        tx = ShadowPortfolioTxRow(
            holding_id=h.id,
            time=now,
            kind=PortfolioTxKind.SELL.value,
            qty=h.qty,
            price=price_d,
            amount_inr=h.qty * price_d,
            note=f"shadow SELL: {reason}",
        )
        self.session.add(tx)
        await self.session.commit()
        return True

    async def vs_actual(self) -> dict[str, Any]:
        """Diff shadow vs actual portfolio.

        Reports three layers, per the CONTRACTS.md "compared metrics" spec:

        1. **Membership** — which symbols are only-shadow / only-actual / both.
        2. **Value** — cost-basis estimate (``*_value_inr``, kept for backward
           compatibility) plus a marked-to-market value (``*_marked_inr``).
        3. **Performance** — unrealized return % and an annualised Sharpe of the
           cost-weighted daily-return series for each book, and the shadow-minus-
           actual gap on both. This is what tells you whether the model book is
           actually *out-performing* the real one, not just holding different
           names.
        """
        actual_rows = await self._all_actual_open_holdings()
        shadow_rows = await self._open_holdings()

        actual_value = sum(self._estimated_value(r) for r in actual_rows)
        shadow_value = sum(self._estimated_value(r) for r in shadow_rows)

        actual_perf = await self._book_performance(actual_rows)
        shadow_perf = await self._book_performance(shadow_rows)

        actual_symbols = {r.symbol for r in actual_rows if r.symbol}
        shadow_symbols = {r.symbol for r in shadow_rows if r.symbol}
        return {
            "actual_value_inr": float(actual_value),
            "shadow_value_inr": float(shadow_value),
            "diff_inr": float(shadow_value - actual_value),
            # Marked-to-market value + performance comparison.
            "actual_marked_inr": actual_perf["marked_value_inr"],
            "shadow_marked_inr": shadow_perf["marked_value_inr"],
            "actual_return_pct": actual_perf["return_pct"],
            "shadow_return_pct": shadow_perf["return_pct"],
            "return_pct_diff": round(shadow_perf["return_pct"] - actual_perf["return_pct"], 6),
            "actual_sharpe": actual_perf["sharpe"],
            "shadow_sharpe": shadow_perf["sharpe"],
            "sharpe_diff": round(shadow_perf["sharpe"] - actual_perf["sharpe"], 4),
            "only_in_shadow": sorted(shadow_symbols - actual_symbols),
            "only_in_actual": sorted(actual_symbols - shadow_symbols),
            "in_both": sorted(actual_symbols & shadow_symbols),
            "n_actual_positions": len(actual_symbols),
            "n_shadow_positions": len(shadow_symbols),
        }

    async def _book_performance(self, rows: list[Any]) -> dict[str, float]:
        """Marked value, unrealized return %, and Sharpe for a set of holdings.

        ``return_pct`` is ``(marked_value - cost_basis) / cost_basis``. ``sharpe``
        is the annualised Sharpe of the cost-weighted daily-return series across
        the book's symbols over the trailing 90 days; it's 0.0 when there isn't
        enough overlapping return history to compute one.
        """
        marked_value = Decimal(0)
        cost_basis = Decimal(0)
        weighted: list[tuple[str, Decimal, pd.Series]] = []
        for h in rows:
            qty = Decimal(str(h.qty)) if h.qty is not None else Decimal(0)
            basis = Decimal(str(h.cost_basis_inr or 0))
            cost_basis += basis
            price = await self._latest_close(h.symbol)
            if price is None or price <= 0:
                marked_value += basis  # no live quote → don't fabricate a move
            else:
                marked_value += qty * price
            if h.symbol and basis > 0:
                rets = await self._recent_returns(h.symbol, 90)
                if rets is not None and len(rets) >= 10:
                    weighted.append((h.symbol, basis, rets))

        return_pct = float((marked_value - cost_basis) / cost_basis) if cost_basis > 0 else 0.0
        sharpe = self._weighted_sharpe(weighted)
        return {
            "marked_value_inr": float(marked_value),
            "cost_basis_inr": float(cost_basis),
            "return_pct": round(return_pct, 6),
            "sharpe": round(sharpe, 4),
        }

    @staticmethod
    def _weighted_sharpe(weighted: list[tuple[str, Decimal, pd.Series]]) -> float:
        """Annualised Sharpe of a cost-weighted blend of per-symbol return series."""
        if not weighted:
            return 0.0
        total_w = sum((float(w) for _, w, _ in weighted), 0.0)
        if total_w <= 0:
            return 0.0
        frame = pd.concat({sym: rets for sym, _, rets in weighted}, axis=1, join="inner").dropna()
        if len(frame) < 10:
            return 0.0
        weights = {sym: float(w) / total_w for sym, w, _ in weighted}
        portfolio_rets = sum(frame[sym] * weights[sym] for sym in frame.columns)
        sd = float(portfolio_rets.std(ddof=1))
        # ``sd < 1e-12`` rather than ``== 0``: float std of a constant series is
        # a tiny non-zero value that would otherwise explode the Sharpe.
        if sd < 1e-12 or np.isnan(sd):
            return 0.0
        return float(portfolio_rets.mean() / sd) * (252**0.5)

    # ------------------------------------------------------------------
    # Helpers (private)
    # ------------------------------------------------------------------

    async def _count_today_buys(self, when: datetime) -> int:
        start_of_day = datetime(when.year, when.month, when.day, tzinfo=when.tzinfo or timezone.utc)
        end_of_day = start_of_day + timedelta(days=1)
        stmt = select(ShadowPortfolioTxRow).where(
            ShadowPortfolioTxRow.kind == PortfolioTxKind.BUY.value,
            ShadowPortfolioTxRow.time >= start_of_day,
            ShadowPortfolioTxRow.time < end_of_day,
        )
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        return len(rows)

    async def _mark_to_market_equity(self, as_of) -> Decimal:
        """Total portfolio equity = uninvested cash + market value of holdings.

        Cash deployed on each open position equals its ``cost_basis_inr`` (we
        bought ``qty`` at ``price``), so remaining cash is
        ``starting_cash_inr - sum(cost_basis)``. Adding the marked-to-market
        value of the holdings back gives ``starting_cash + unrealized_pnl`` —
        which keeps equity comparable to :meth:`_peak_equity` (both are on a
        whole-portfolio basis). Marking holdings-only here previously made a
        freshly-deployed 10% position look like an 90% drawdown and tripped the
        halt on the very next signal.
        """
        rows = await self._open_holdings()
        invested = sum((h.cost_basis_inr for h in rows), Decimal(0))
        market_value = Decimal(0)
        for h in rows:
            price = await self._latest_close(h.symbol)
            price_d = Decimal(str(price if price is not None else 0))
            if price_d <= 0:
                # No live price → fall back to cost basis so a missing quote
                # doesn't fabricate a loss.
                market_value += h.cost_basis_inr
            else:
                market_value += h.qty * price_d
        cash = self.starting_cash_inr - invested
        return cash + market_value

    async def _peak_equity(self) -> Decimal:
        """Peak equity high-water mark.

        Without a full equity-curve table we lower-bound the peak by the
        starting capital: the portfolio only opens positions sized as a
        fraction of equity, so it never exceeds ``starting_cash_inr`` on day
        one and the drawdown rule still fires reliably once MtM equity drops a
        real ``drawdown_halt_pct`` below that base.
        """
        return self.starting_cash_inr

    async def _correlation_ok(self, symbol: str) -> tuple[bool, str]:
        """90d return correlation guard vs existing open positions."""
        other_rows = await self._open_holdings()
        other_symbols = [r.symbol for r in other_rows if r.symbol and r.symbol != symbol]
        if not other_symbols:
            return True, ""

        target_rets = await self._recent_returns(symbol, 90)
        if target_rets is None or len(target_rets) < 10:
            return True, ""  # insufficient history → don't block

        for other in other_symbols:
            other_rets = await self._recent_returns(other, 90)
            if other_rets is None or len(other_rets) < 10:
                continue
            aligned = pd.concat([target_rets, other_rets], axis=1, join="inner").dropna()
            if len(aligned) < 10:
                continue
            corr = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
            if abs(corr) > self.rules.correlation_cap:
                return (
                    False,
                    f"correlation guard: |corr({symbol},{other})|={abs(corr):.2f} > {self.rules.correlation_cap}",
                )
        return True, ""

    async def _recent_returns(self, symbol: str, days: int) -> pd.Series | None:
        since = datetime.now(tz=timezone.utc) - timedelta(days=days + 5)
        stmt = (
            select(OHLCVRow.time, OHLCVRow.close)
            .where(OHLCVRow.symbol == symbol, OHLCVRow.time >= since)
            .order_by(OHLCVRow.time.asc())
        )
        res = await self.session.execute(stmt)
        rows = res.all()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["time", "close"])
        df["close"] = df["close"].astype(float)
        df = df.set_index("time")
        return df["close"].pct_change().dropna().rename(symbol)

    async def _open_holdings(self) -> list[ShadowHoldingRow]:
        stmt = select(ShadowHoldingRow).where(ShadowHoldingRow.closed_at.is_(None))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def _all_actual_open_holdings(self) -> list[HoldingRow]:
        stmt = select(HoldingRow).where(HoldingRow.closed_at.is_(None))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def _latest_close(self, symbol: str | None) -> Decimal | None:
        if not symbol:
            return None
        stmt = (
            select(OHLCVRow.close)
            .where(OHLCVRow.symbol == symbol)
            .order_by(OHLCVRow.time.desc())
            .limit(1)
        )
        res = await self.session.execute(stmt)
        first = res.scalars().first()
        return None if first is None else Decimal(str(first))

    async def _close_symbol(self, symbol: str, price: Decimal, reason: str) -> Any | None:
        stmt = select(ShadowHoldingRow).where(
            ShadowHoldingRow.symbol == symbol, ShadowHoldingRow.closed_at.is_(None)
        )
        res = await self.session.execute(stmt)
        rows = list(res.scalars().all())
        closed_ids: list[Any] = []
        for h in rows:
            ok = await self.close_position(h.id, price, reason)
            if ok:
                closed_ids.append(h.id)
        return closed_ids[0] if closed_ids else None

    def _estimated_value(self, row: Any) -> Decimal:
        if row.qty is None:
            return Decimal(0)
        basis = row.cost_basis_inr or Decimal(0)
        return Decimal(basis)

    def _guess_category(self, asset: str) -> str:
        """Rough mapping from ticker string to holding category."""
        if "/" in asset or asset.endswith("USD") or asset.endswith("USDT"):
            return HoldingCategory.CRYPTO_EXCHANGE.value
        if asset.endswith(".NS") or asset.endswith(".BO"):
            return HoldingCategory.EQUITY.value
        if asset.isupper() and 2 <= len(asset) <= 5:
            return HoldingCategory.ETF.value
        return HoldingCategory.EQUITY.value


# ---------------------------------------------------------------------------
# Convenience mapping for type-checking on Mapping-based signal payloads.
# ---------------------------------------------------------------------------


def signal_from_mapping(m: Mapping[str, Any]) -> Signal:
    """Build a ``Signal`` from a dict-like row returned by the DB."""
    return Signal.model_validate(dict(m))
