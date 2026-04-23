"""Holdings + portfolio computations.

Reads/writes ``holdings`` and ``portfolio_tx`` tables. All monetary columns
are INR-denominated (cost_basis_inr, exit_price_inr, price). Foreign-currency
cost bases are captured with ``cost_basis_ccy`` + ``fx_rate`` at the
transaction time.

Designed to work with both:
    - A real SQLAlchemy ``AsyncSession`` (production path).
    - The ``_FakeSession`` stub used in smoke tests (no DB hit).

The service never talks to the network; mark-to-market prices are injected
as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

try:
    import numpy as np
    import pandas as pd

    _HAS_PANDAS = True
except Exception:  # pragma: no cover
    _HAS_PANDAS = False

from sqlalchemy import select

from pfip.core.contracts import Holding, HoldingCategory, PortfolioSummary
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HoldingValidationError(ValueError):
    """Raised when an inbound holding fails a sanity check."""


class HoldingNotFoundError(LookupError):
    """Raised when a holding_id doesn't exist."""


# ---------------------------------------------------------------------------
# PnL
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PnL:
    """Realized + unrealized P&L for a holding."""

    holding_id: UUID | None
    symbol: str | None
    realized_inr: Decimal
    unrealized_inr: Decimal
    total_inr: Decimal
    cost_basis_inr: Decimal
    current_value_inr: Decimal
    qty_open: Decimal


@dataclass(slots=True)
class RebalanceSuggestion:
    """Advisory trade suggestion (never auto-executed)."""

    asset_class: str
    action: str  # BUY or SELL
    drift_pct: float
    target_pct: float
    current_pct: float
    notional_inr: Decimal
    rationale: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PortfolioService:
    """Thin service wrapping the holdings + portfolio_tx tables."""

    def __init__(self, db: Any) -> None:
        self.db = db

    # --- Read ---

    async def list_holdings(
        self,
        *,
        category: HoldingCategory | str | None = None,
        active: bool | None = True,
    ) -> list[Holding]:
        """List holdings with optional filters."""
        stmt = select(HoldingRow)
        if category is not None:
            cat_val = category.value if isinstance(category, HoldingCategory) else category
            stmt = stmt.where(HoldingRow.category == cat_val)
        if active is True:
            stmt = stmt.where(HoldingRow.closed_at.is_(None))
        elif active is False:
            stmt = stmt.where(HoldingRow.closed_at.is_not(None))
        stmt = stmt.order_by(HoldingRow.acquired_at.desc())
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [Holding.model_validate(r) for r in rows]

    async def get_holding(self, holding_id: UUID) -> Holding | None:
        stmt = select(HoldingRow).where(HoldingRow.id == holding_id)
        result = await self.db.execute(stmt)
        row = result.scalars().first()
        return None if row is None else Holding.model_validate(row)

    async def list_transactions(
        self, *, holding_id: UUID | None = None
    ) -> list[dict]:
        stmt = select(PortfolioTxRow)
        if holding_id is not None:
            stmt = stmt.where(PortfolioTxRow.holding_id == holding_id)
        stmt = stmt.order_by(PortfolioTxRow.time)
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "holding_id": r.holding_id,
                "time": r.time,
                "kind": r.kind,
                "qty": r.qty,
                "price": r.price,
                "amount_inr": r.amount_inr,
                "fx_rate": r.fx_rate,
                "tax_withheld": r.tax_withheld,
                "note": r.note,
            }
            for r in rows
        ]

    # --- Write ---

    async def add_holding(self, payload: Holding) -> Holding:
        """Validate + persist a new holding. Also records the BUY tx."""
        self._validate(payload)
        row = HoldingRow(
            category=(
                payload.category.value
                if isinstance(payload.category, HoldingCategory)
                else str(payload.category)
            ),
            symbol=payload.symbol,
            isin=payload.isin,
            broker=payload.broker,
            account_id=payload.account_id,
            acquired_at=payload.acquired_at,
            qty=payload.qty,
            cost_basis_inr=payload.cost_basis_inr,
            cost_basis_ccy=payload.cost_basis_ccy,
            fx_rate=payload.fx_rate,
            is_self_custody=payload.is_self_custody,
            notes=payload.notes,
            closed_at=payload.closed_at,
            exit_price_inr=payload.exit_price_inr,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)

        # Record opening BUY tx for audit.
        tx = PortfolioTxRow(
            holding_id=row.id,
            time=payload.acquired_at,
            kind="BUY",
            qty=payload.qty,
            price=(
                (payload.cost_basis_inr / payload.qty).quantize(Decimal("0.0001"))
                if payload.qty
                else None
            ),
            amount_inr=payload.cost_basis_inr,
            fx_rate=payload.fx_rate,
            tax_withheld=Decimal("0"),
            note="Opening BUY (add_holding)",
        )
        self.db.add(tx)
        await self.db.commit()
        return Holding.model_validate(row)

    async def close_holding(
        self,
        holding_id: UUID,
        exit_price_inr: Decimal,
        when: datetime | None = None,
        *,
        qty: Decimal | None = None,
    ) -> dict:
        """Close a holding fully or partially. Emits SELL tx.

        Args:
            holding_id: the holding to close.
            exit_price_inr: total proceeds (INR) or per-unit if ``qty`` given.
            when: close timestamp; defaults to now(UTC).
            qty: optional partial close quantity. None ⇒ close all.

        Returns:
            ``{holding: Holding, sell_tx: {...}, post_mortem_required: True}``
        """
        when = when or datetime.now(tz=timezone.utc)
        stmt = select(HoldingRow).where(HoldingRow.id == holding_id)
        result = await self.db.execute(stmt)
        row = result.scalars().first()
        if row is None:
            raise HoldingNotFoundError(f"Holding {holding_id} not found")
        if row.closed_at is not None:
            raise HoldingValidationError(f"Holding {holding_id} already closed")

        close_qty = Decimal(str(qty)) if qty is not None else Decimal(str(row.qty))
        if close_qty <= 0:
            raise HoldingValidationError("qty must be positive")
        if close_qty > Decimal(str(row.qty)):
            raise HoldingValidationError(
                f"qty {close_qty} exceeds open qty {row.qty}"
            )

        # If per-unit or total? If exit_price_inr is "small" vs cost_basis we
        # assume per-unit; else total. To keep semantics explicit we treat
        # exit_price_inr as PER-UNIT when qty is given, else total.
        if qty is None:
            proceeds_total = Decimal(str(exit_price_inr))
            per_unit = (
                (proceeds_total / close_qty).quantize(Decimal("0.0001"))
                if close_qty
                else Decimal("0")
            )
        else:
            per_unit = Decimal(str(exit_price_inr))
            proceeds_total = (per_unit * close_qty).quantize(Decimal("0.01"))

        # Update the holding row.
        if qty is None:
            row.closed_at = when
            row.exit_price_inr = proceeds_total
        else:
            row.qty = Decimal(str(row.qty)) - close_qty
            if row.qty <= 0:
                row.closed_at = when
                row.exit_price_inr = proceeds_total

        tx = PortfolioTxRow(
            holding_id=row.id,
            time=when,
            kind="SELL",
            qty=close_qty,
            price=per_unit,
            amount_inr=proceeds_total,
            fx_rate=row.fx_rate,
            tax_withheld=Decimal("0"),
            note="close_holding",
        )
        self.db.add(tx)
        await self.db.commit()
        await self.db.refresh(row)
        return {
            "holding": Holding.model_validate(row),
            "sell_tx": {
                "holding_id": str(row.id),
                "time": when.isoformat(),
                "qty": str(close_qty),
                "price_inr": str(per_unit),
                "amount_inr": str(proceeds_total),
            },
            "post_mortem_required": True,
            "note": "Post-mortem is MANDATORY within 24h before the next trade in this asset.",
        }

    # --- Analytics ---

    async def weighted_avg_cost_basis(self, holding_id: UUID) -> Decimal:
        """Weighted-average cost basis per unit for all BUY tx on a holding."""
        txs = await self.list_transactions(holding_id=holding_id)
        total_cost = Decimal("0")
        total_qty = Decimal("0")
        for t in txs:
            if t["kind"] != "BUY":
                continue
            q = Decimal(str(t["qty"] or 0))
            amt = Decimal(str(t["amount_inr"] or 0))
            total_cost += amt
            total_qty += q
        if total_qty == 0:
            return Decimal("0")
        return (total_cost / total_qty).quantize(Decimal("0.0001"))

    async def compute_pnl(
        self,
        holding: Holding,
        *,
        mark_price_inr: Decimal | None = None,
    ) -> PnL:
        """Realized + unrealized P&L for a single holding.

        ``mark_price_inr`` is the current per-unit market price. If None,
        unrealized is computed against cost basis (⇒ 0 unrealized).
        """
        txs = await self.list_transactions(holding_id=holding.id) if holding.id else []
        realized = Decimal("0")
        cost_used = Decimal("0")
        for t in txs:
            if t["kind"] == "SELL":
                realized += Decimal(str(t["amount_inr"] or 0))
            elif t["kind"] == "BUY":
                cost_used += Decimal(str(t["amount_inr"] or 0))

        # Realized P&L = SELL proceeds - cost of sold units (via avg cost basis)
        avg_cost = (
            await self.weighted_avg_cost_basis(holding.id) if holding.id else Decimal("0")
        )
        sold_qty = sum(
            (Decimal(str(t["qty"] or 0)) for t in txs if t["kind"] == "SELL"),
            Decimal("0"),
        )
        cost_of_sold = (avg_cost * sold_qty).quantize(Decimal("0.01"))
        realized_pnl = (realized - cost_of_sold).quantize(Decimal("0.01"))

        open_qty = Decimal(str(holding.qty))
        if mark_price_inr is None:
            mark_price_inr = avg_cost  # ⇒ unrealized 0
        current_value = (mark_price_inr * open_qty).quantize(Decimal("0.01"))
        unrealized = (current_value - (avg_cost * open_qty)).quantize(Decimal("0.01"))

        return PnL(
            holding_id=holding.id,
            symbol=holding.symbol,
            realized_inr=realized_pnl,
            unrealized_inr=unrealized,
            total_inr=(realized_pnl + unrealized).quantize(Decimal("0.01")),
            cost_basis_inr=(avg_cost * open_qty).quantize(Decimal("0.01")),
            current_value_inr=current_value,
            qty_open=open_qty,
        )

    async def exposure_by_category(
        self,
        *,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> dict[str, Decimal]:
        """Return category→INR exposure and the percent distribution.

        ``mark_prices`` maps symbol → current INR price per unit. Missing
        symbols fall back to cost basis.
        """
        holdings = await self.list_holdings(active=True)
        exposure: dict[str, Decimal] = {}
        for h in holdings:
            cat = h.category.value
            if mark_prices and h.symbol and h.symbol in mark_prices:
                val = (mark_prices[h.symbol] * h.qty).quantize(Decimal("0.01"))
            else:
                val = h.cost_basis_inr
            exposure[cat] = exposure.get(cat, Decimal("0")) + val
        return exposure

    async def portfolio_summary(
        self,
        *,
        mark_prices: dict[str, Decimal] | None = None,
        nav_history: list[tuple[date, Decimal]] | None = None,
    ) -> PortfolioSummary:
        """Return a ``PortfolioSummary`` (contracts.py model).

        Args:
            mark_prices: symbol → current INR price.
            nav_history: list of ``(date, nav_inr)`` sorted ascending. Used for
                drawdown peak-to-current and trailing-30d Sharpe.

        The contract model has these fields: total_inr, pnl_inr, pnl_pct,
        exposure_by_category, drawdown. We stick to that exactly; Sharpe and
        Herfindahl live on adjacent helpers.
        """
        holdings = await self.list_holdings(active=True)
        closed = await self.list_holdings(active=False)

        total_cost = sum((h.cost_basis_inr for h in holdings), Decimal("0"))
        total_mkt = Decimal("0")
        for h in holdings:
            mp = (mark_prices or {}).get(h.symbol or "")
            total_mkt += (mp * h.qty).quantize(Decimal("0.01")) if mp else h.cost_basis_inr
        realized_sum = Decimal("0")
        for h in closed:
            if h.exit_price_inr is not None:
                realized_sum += Decimal(str(h.exit_price_inr)) - Decimal(
                    str(h.cost_basis_inr)
                )

        pnl_inr = (total_mkt - total_cost + realized_sum).quantize(Decimal("0.01"))
        pnl_pct = (
            float(pnl_inr / total_cost) if total_cost > 0 else 0.0
        )

        drawdown = 0.0
        if nav_history:
            peak = max(n for _, n in nav_history)
            current = nav_history[-1][1]
            if peak > 0:
                drawdown = float(Decimal("1") - current / peak)

        exposure = await self.exposure_by_category(mark_prices=mark_prices)

        return PortfolioSummary(
            total_inr=total_mkt,
            pnl_inr=pnl_inr,
            pnl_pct=pnl_pct,
            exposure_by_category=exposure,
            drawdown=drawdown,
        )

    async def correlation_matrix(
        self,
        return_series: dict[str, list[float]] | None = None,
        window_days: int = 90,
    ) -> dict[str, dict[str, float]]:
        """Pearson correlation across holding return series.

        ``return_series`` maps symbol → a list of daily log-returns (most
        recent last). If ``None`` or length < window_days, returns empty.
        """
        if not _HAS_PANDAS or not return_series:
            return {}
        # Align series and clip to window.
        trimmed = {
            k: v[-window_days:] for k, v in return_series.items() if len(v) >= 2
        }
        if not trimmed:
            return {}
        n = min(len(v) for v in trimmed.values())
        if n < 2:
            return {}
        trimmed = {k: v[-n:] for k, v in trimmed.items()}
        df = pd.DataFrame(trimmed)
        corr = df.corr().fillna(0.0)
        return {
            row: {col: float(corr.at[row, col]) for col in corr.columns}
            for row in corr.index
        }

    def historical_var(
        self,
        returns: list[float],
        *,
        confidence: float = 0.95,
        horizon_days: int = 1,
        portfolio_value_inr: Decimal | None = None,
    ) -> dict:
        """Historical-simulation Value-at-Risk.

        Args:
            returns: daily returns (fraction, not %). At least 30 points.
            confidence: e.g. 0.95.
            horizon_days: scales VaR by sqrt(horizon).
            portfolio_value_inr: if provided, returns INR loss at VaR.
        """
        if not returns or len(returns) < 30:
            return {"var_pct": 0.0, "cvar_pct": 0.0, "n": len(returns), "note": "n<30"}
        if not _HAS_PANDAS:
            sorted_r = sorted(returns)
            q_idx = int((1 - confidence) * len(sorted_r))
            var_ret = sorted_r[q_idx]
        else:
            s = pd.Series(returns)
            var_ret = float(s.quantile(1 - confidence))
        # horizon scaling
        import math

        var_ret_scaled = var_ret * math.sqrt(horizon_days)
        cvar = (
            float(pd.Series(returns)[pd.Series(returns) <= var_ret].mean())
            if _HAS_PANDAS
            else var_ret
        )
        out = {
            "confidence": confidence,
            "horizon_days": horizon_days,
            "var_pct": float(var_ret_scaled),
            "cvar_pct": float(cvar),
            "n": len(returns),
        }
        if portfolio_value_inr is not None:
            out["var_inr"] = str((Decimal(str(abs(var_ret_scaled))) * portfolio_value_inr).quantize(Decimal("0.01")))
        return out

    async def concentration_score(
        self,
        *,
        mark_prices: dict[str, Decimal] | None = None,
    ) -> dict:
        """Herfindahl-Hirschman Index across holdings (by symbol).

        Returns a dict with the HHI value (0 diverse → 1 fully concentrated) and
        the top-5 positions with their weights.
        """
        holdings = await self.list_holdings(active=True)
        values: dict[str, Decimal] = {}
        for h in holdings:
            key = h.symbol or h.category.value
            mp = (mark_prices or {}).get(h.symbol or "")
            v = (mp * h.qty).quantize(Decimal("0.01")) if mp else h.cost_basis_inr
            values[key] = values.get(key, Decimal("0")) + v
        total = sum(values.values(), Decimal("0"))
        if total == 0:
            return {"hhi": 0.0, "top5": [], "n": 0}
        weights = {k: float(v / total) for k, v in values.items()}
        hhi = sum(w * w for w in weights.values())
        top5 = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "hhi": hhi,
            "interpretation": (
                "HHI > 0.25 is concentrated (HHI of fully equal N assets = 1/N). "
                "Consider diversifying."
            ),
            "top5": [{"key": k, "weight": w} for k, w in top5],
            "n": len(weights),
        }

    # --- Validation ---

    @staticmethod
    def _validate(h: Holding) -> None:
        if Decimal(str(h.qty)) <= 0:
            raise HoldingValidationError("qty must be positive")
        if Decimal(str(h.cost_basis_inr)) < 0:
            raise HoldingValidationError("cost_basis_inr cannot be negative")
        if h.cost_basis_ccy != "INR" and h.fx_rate is None:
            raise HoldingValidationError(
                f"fx_rate required when cost_basis_ccy={h.cost_basis_ccy!r}"
            )
        if h.is_self_custody and h.category not in (
            HoldingCategory.CRYPTO_SELF_CUSTODY,
            HoldingCategory.CRYPTO_EXCHANGE,
        ):
            raise HoldingValidationError(
                "is_self_custody=True is only valid for crypto categories"
            )


# ---------------------------------------------------------------------------
# Performance / Sharpe helpers (pure, stateless)
# ---------------------------------------------------------------------------


def trailing_sharpe(returns: list[float], *, window: int = 30, rf: float = 0.0) -> float:
    """Annualised Sharpe over the trailing ``window`` daily returns.

    Returns 0.0 if ``len(returns) < window`` or std==0.
    """
    if len(returns) < window:
        return 0.0
    tail = returns[-window:]
    if _HAS_PANDAS:
        s = pd.Series(tail)
        mu = float(s.mean()) - rf / 252
        sd = float(s.std(ddof=1))
    else:
        import statistics

        mu = statistics.fmean(tail) - rf / 252
        sd = statistics.pstdev(tail)
    if sd == 0:
        return 0.0
    return (mu / sd) * (252 ** 0.5)


def peak_drawdown(nav_series: list[float]) -> float:
    """Peak-to-current drawdown of a NAV series (fraction, ≥0)."""
    if not nav_series:
        return 0.0
    peak = nav_series[0]
    dd = 0.0
    for n in nav_series:
        if n > peak:
            peak = n
        if peak > 0:
            dd = max(dd, 1 - n / peak)
    return dd
