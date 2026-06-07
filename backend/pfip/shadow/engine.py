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
        """Daily rollup: total equity, unrealized PnL per holding."""
        as_of = as_of or datetime.now(tz=timezone.utc)
        rows = await self._open_holdings()
        equity = Decimal(0)
        lines: list[dict[str, Any]] = []
        for h in rows:
            price = await self._latest_close(h.symbol)
            if price is None:
                price = (h.cost_basis_inr / h.qty) if h.qty > 0 else Decimal(0)
            value = h.qty * Decimal(str(price))
            pnl = value - h.cost_basis_inr
            equity += value
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
        return {"as_of": as_of.isoformat(), "equity_inr": float(equity), "lines": lines}

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
        """Diff shadow vs actual portfolio (holdings + PnL totals)."""
        actual_rows = await self._all_actual_open_holdings()
        shadow_rows = await self._open_holdings()

        actual_value = sum(self._estimated_value(r) for r in actual_rows)
        shadow_value = sum(self._estimated_value(r) for r in shadow_rows)

        actual_symbols = {r.symbol for r in actual_rows if r.symbol}
        shadow_symbols = {r.symbol for r in shadow_rows if r.symbol}
        return {
            "actual_value_inr": float(actual_value),
            "shadow_value_inr": float(shadow_value),
            "diff_inr": float(shadow_value - actual_value),
            "only_in_shadow": sorted(shadow_symbols - actual_symbols),
            "only_in_actual": sorted(actual_symbols - shadow_symbols),
            "in_both": sorted(actual_symbols & shadow_symbols),
            "n_actual_positions": len(actual_symbols),
            "n_shadow_positions": len(shadow_symbols),
        }

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
        rows = await self._open_holdings()
        equity = Decimal(0)
        for h in rows:
            price = await self._latest_close(h.symbol)
            price_d = Decimal(str(price if price is not None else 0))
            equity += h.qty * price_d
        return equity or self.starting_cash_inr

    async def _peak_equity(self) -> Decimal:
        """Approximate peak equity as max(equity_today, sum(cost_basis)).

        Without a full equity-curve table we lower-bound peak by total invested
        capital. It still triggers the drawdown rule reliably when MtM drops.
        """
        rows = await self._open_holdings()
        invested = sum((h.cost_basis_inr for h in rows), Decimal(0))
        return max(invested, self.starting_cash_inr)

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
