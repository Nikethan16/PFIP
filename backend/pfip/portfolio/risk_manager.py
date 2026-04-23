"""Pre-trade and portfolio-level risk checks.

Implements the 10-item Appendix B pre-trade checklist (automatable items),
portfolio-level drawdown halt, correlation gate, Van Tharp position sizing,
and the daily new-positions cap.

Rules come from ``pfip.core.config.Settings``:
    - ``max_position_pct``       per-trade position cap (default 10%)
    - ``drawdown_halt_pct``      halt threshold (default 20%)
    - ``daily_new_positions_cap``  (default 2)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterable

from pfip.core.config import Settings, get_settings
from pfip.core.contracts import Holding


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    """Single-reason check outcome."""

    ok: bool
    reason: str | None = None

    def __bool__(self) -> bool:  # allow `if result:` style
        return self.ok


@dataclass(frozen=True, slots=True)
class PreTradeVerdict:
    """Aggregate outcome of the 10-item checklist."""

    pass_all: bool
    reasons: list[str]
    per_item: dict[str, bool]

    def __bool__(self) -> bool:
        return self.pass_all


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class RiskManager:
    """Risk engine. Stateless; pass inputs per call."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Pre-trade — 10-item Appendix B checklist (automatable subset)
    # ------------------------------------------------------------------

    def check_pre_trade(
        self,
        *,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        existing_holdings: Iterable[Holding] | list[dict],
        portfolio_value_inr: Decimal,
        stop_distance_pct: float | None = None,
        regime: str | None = None,
        signal_confidence: int | None = None,
        news_count_24h: int | None = None,
        event_calendar_conflict: bool = False,
        positions_added_today: int = 0,
        current_drawdown_pct: float = 0.0,
        correlation_matrix: dict[tuple[str, str], float] | None = None,
        correlation_threshold: float = 0.7,
    ) -> PreTradeVerdict:
        """Evaluate a proposed trade against automatable checklist items.

        Non-automatable items (thesis text, counter-argument text, emotional
        state, override rationale) are enforced by the journal UI — the API
        just records the user's responses.

        Returns:
            ``PreTradeVerdict`` with per-item pass/fail.
        """
        per_item: dict[str, bool] = {}
        reasons: list[str] = []

        proposed_notional = (Decimal(str(qty)) * Decimal(str(price))).quantize(
            Decimal("0.01")
        )

        # Normalise existing_holdings to plain symbols list.
        existing_symbols: list[str] = []
        for h in existing_holdings:
            sym = getattr(h, "symbol", None) if not isinstance(h, dict) else h.get("symbol")
            if sym:
                existing_symbols.append(sym)

        # Item 3 — stop-loss set (we just check it was provided).
        per_item["stop_loss_provided"] = stop_distance_pct is not None
        if stop_distance_pct is None:
            reasons.append("Stop-loss distance not specified.")

        # Item 4 — position size <= cap.
        if portfolio_value_inr > 0:
            pct = float(proposed_notional / portfolio_value_inr)
            per_item["position_size_within_cap"] = pct <= self._settings.max_position_pct
            if pct > self._settings.max_position_pct:
                reasons.append(
                    f"Position {pct:.1%} exceeds cap {self._settings.max_position_pct:.0%}."
                )
        else:
            per_item["position_size_within_cap"] = True

        # Item 5 — correlation check.
        corr_res = self.check_correlation(
            symbol,
            existing_symbols,
            correlation_matrix or {},
            threshold=correlation_threshold,
        )
        per_item["correlation_under_threshold"] = corr_res.ok
        if not corr_res.ok and corr_res.reason:
            reasons.append(corr_res.reason)

        # Item 6 — regime fit (we just require a regime is known).
        per_item["regime_known"] = bool(regime)
        if not regime:
            reasons.append("Regime for this market is unknown; run the regime classifier first.")

        # Item 7 — material news check (>=1 recent item is informational; we warn if none).
        per_item["news_scanned"] = news_count_24h is not None
        if news_count_24h is None:
            reasons.append("News scan for last 24h not performed.")

        # Item 8 — no HIGH-impact event conflict.
        per_item["no_event_conflict"] = not event_calendar_conflict
        if event_calendar_conflict:
            reasons.append("HIGH-impact event on calendar in next 72h.")

        # Item 9 — model signal present.
        per_item["signal_present"] = signal_confidence is not None

        # --- Portfolio-level guards (also from Section 8.3) ---

        # Drawdown halt.
        per_item["no_drawdown_halt"] = current_drawdown_pct < self._settings.drawdown_halt_pct
        if not per_item["no_drawdown_halt"]:
            reasons.append(
                f"Drawdown {current_drawdown_pct:.1%} >= halt {self._settings.drawdown_halt_pct:.0%}."
            )

        # Daily new-positions cap.
        per_item["daily_cap_not_reached"] = (
            positions_added_today < self._settings.daily_new_positions_cap
        )
        if not per_item["daily_cap_not_reached"]:
            reasons.append(
                f"Daily new-positions cap ({self._settings.daily_new_positions_cap}) reached."
            )

        pass_all = all(per_item.values())
        return PreTradeVerdict(pass_all=pass_all, reasons=reasons, per_item=per_item)

    # ------------------------------------------------------------------
    # Portfolio-level
    # ------------------------------------------------------------------

    def check_drawdown(
        self,
        portfolio_history: list[tuple[date, Decimal]] | list[Decimal] | list[float],
    ) -> tuple[str, float]:
        """Compute peak-to-current drawdown + status label.

        Status:
            ``"HALT"`` if dd ≥ ``drawdown_halt_pct``
            ``"WARN"`` if dd ≥ 0.5 × halt threshold
            ``"OK"`` otherwise
        """
        if not portfolio_history:
            return ("OK", 0.0)
        # normalise to floats
        values: list[float] = []
        for item in portfolio_history:
            if isinstance(item, tuple):
                values.append(float(item[1]))
            else:
                values.append(float(item))
        peak = values[0]
        dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            if peak > 0:
                dd = max(dd, 1 - v / peak)
        halt = self._settings.drawdown_halt_pct
        status = "HALT" if dd >= halt else ("WARN" if dd >= halt * 0.5 else "OK")
        return (status, dd)

    def check_correlation(
        self,
        new_symbol: str,
        existing_symbols: list[str],
        correlation_matrix: dict[tuple[str, str], float],
        *,
        threshold: float = 0.7,
    ) -> RiskCheckResult:
        """Flag correlations ≥ ``threshold`` to any existing symbol."""
        conflicts: list[str] = []
        for other in existing_symbols:
            if other == new_symbol:
                continue
            corr = correlation_matrix.get((new_symbol, other)) or correlation_matrix.get(
                (other, new_symbol)
            )
            if corr is None:
                continue
            if abs(corr) >= threshold:
                conflicts.append(f"{other} (ρ={corr:+.2f})")
        if conflicts:
            return RiskCheckResult(
                ok=False,
                reason=(
                    f"{new_symbol} is highly correlated to: " + ", ".join(conflicts)
                ),
            )
        return RiskCheckResult(ok=True)

    def position_size_recommend(
        self,
        *,
        stop_distance_pct: float,
        portfolio_value_inr: Decimal,
        risk_per_trade_pct: float = 0.01,
        price_per_unit_inr: Decimal | None = None,
    ) -> dict:
        """Van Tharp position sizing.

        Risk per trade = account equity × risk-per-trade fraction.
        Position size (units) = (risk per trade) / (price × stop-distance).
        Notional = min(position × price, max_position_pct × equity).
        """
        if stop_distance_pct <= 0:
            raise ValueError("stop_distance_pct must be > 0")
        risk_amount = Decimal(str(portfolio_value_inr)) * Decimal(str(risk_per_trade_pct))
        per_unit_risk_inr = None
        units: Decimal | None = None
        if price_per_unit_inr is not None and Decimal(str(price_per_unit_inr)) > 0:
            per_unit_risk_inr = (
                Decimal(str(price_per_unit_inr)) * Decimal(str(stop_distance_pct))
            )
            units = (risk_amount / per_unit_risk_inr).quantize(Decimal("0.0001"))
        # notional cap
        cap_notional = (
            Decimal(str(portfolio_value_inr)) * Decimal(str(self._settings.max_position_pct))
        ).quantize(Decimal("0.01"))
        suggested_notional = (
            (Decimal(str(price_per_unit_inr)) * units).quantize(Decimal("0.01"))
            if (units is not None and price_per_unit_inr is not None)
            else risk_amount / Decimal(str(stop_distance_pct))
        )
        suggested_notional = min(suggested_notional, cap_notional)
        return {
            "risk_amount_inr": str(risk_amount.quantize(Decimal("0.01"))),
            "per_unit_stop_risk_inr": str(per_unit_risk_inr.quantize(Decimal("0.0001")))
            if per_unit_risk_inr is not None
            else None,
            "units": str(units) if units is not None else None,
            "suggested_notional_inr": str(suggested_notional),
            "notional_cap_inr": str(cap_notional),
            "formula": "Units = (equity × risk%) / (price × stop%)",
        }

    def daily_new_positions_remaining(self, positions_added_today: int) -> int:
        """Remaining slots on the daily new-position cap."""
        return max(
            0, self._settings.daily_new_positions_cap - int(positions_added_today)
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def is_today_utc(dt: datetime) -> bool:
        """True if ``dt`` is today in UTC."""
        return dt.astimezone(timezone.utc).date() == datetime.now(tz=timezone.utc).date()
