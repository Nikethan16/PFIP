"""Tax-loss harvesting suggestions for Indian assessees.

A loss-harvesting candidate is an open lot whose current mark-to-market
price is below its cost basis (in INR) **and** where realising that loss
this FY would actually reduce the tax bill — i.e. it can be set off
against an existing realised gain of the same character, or it can be
carried forward profitably.

Indian tax constraints baked in:

- **VDA (crypto)**: Section 115BBH allows **no loss set-off** and no
  carry-forward of crypto losses. We therefore *never* suggest
  harvesting a crypto loss.
- **STCG (equity)**: Short-term equity losses can be set off against
  STCG **or** LTCG (any class). Preferred matching target: STCG @ 15%
  taxed in the same FY.
- **LTCG (equity)**: Long-term equity losses can only be set off against
  LTCG. The ₹1L LTCG exemption means losses below that threshold are
  worthless to harvest unless the existing LTCG exceeds ₹1L.
- **Debt MF post-2023**: Treated like ordinary income; loss can offset
  any income head.
- **F&O / business income** is out of scope for v1 (the engine doesn't
  model business-income head).

The output ranks candidates by *estimated tax saved (INR)*, descending.
Estimates are deliberately conservative (use the marginal bracket the
user is in, not the average rate).

Strict policy:

- We **suggest** — we never execute. Output is read-only.
- We never recommend wash-sale-equivalent re-buy timing because Indian
  law has no formal wash-sale rule (yet) but the *spirit* of the
  ordinary-business rule applies; we mark suggestions whose re-buy
  within 30 days could plausibly attract attention.
- We add the standard tax disclaimer to every result envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Sequence


DISCLAIMER = (
    "Estimates only. Loss harvesting interacts with surcharge cliffs, "
    "DTAA credits, and your personal slab. Confirm with a CA before "
    "executing trades for tax purposes."
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class HarvestAssetClass(str, Enum):
    """Restricted subset relevant for harvesting; crypto excluded."""

    EQUITY = "equity"
    EQUITY_MF = "equity_mf"
    DEBT_MF = "debt_mf"
    US_STOCK = "us_stock"
    GOLD = "gold"


@dataclass(slots=True)
class OpenLot:
    """An open (un-sold) lot the user holds today."""

    lot_id: str
    symbol: str
    asset_class: HarvestAssetClass
    qty: Decimal
    cost_basis_inr_per_unit: Decimal
    acquired_on: date
    current_price_inr: Decimal


@dataclass(slots=True)
class FYContext:
    """What the user already realised this FY — needed to score offsets."""

    fy_start: date
    fy_end: date
    realised_stcg_equity_inr: Decimal = Decimal("0")  # already realised, taxable @15%
    realised_ltcg_equity_inr: Decimal = Decimal("0")  # already realised, @10% > ₹1L
    realised_debt_gain_inr: Decimal = Decimal("0")  # slab rate
    marginal_slab_rate: Decimal = Decimal("0.30")  # default to top old-regime bracket
    surcharge_rate: Decimal = Decimal("0")  # 0 / 0.10 / 0.15 / 0.25 / 0.37


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HarvestSuggestion:
    """One harvesting candidate."""

    lot_id: str
    symbol: str
    asset_class: HarvestAssetClass
    term: str  # "STCG" or "LTCG"
    qty: Decimal
    loss_inr: Decimal  # positive number = loss magnitude
    offsets_against: str  # human-readable: "STCG equity (already realised)"
    estimated_tax_saved_inr: Decimal
    warning: str | None = None  # e.g. "re-buy within 30 days may attract scrutiny"


@dataclass(slots=True)
class HarvestPlan:
    """Sorted plan envelope."""

    fy: str
    suggestions: list[HarvestSuggestion] = field(default_factory=list)
    total_loss_inr: Decimal = Decimal("0")
    total_tax_saved_inr: Decimal = Decimal("0")
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


_LONG_TERM_THRESHOLD_DAYS: dict[HarvestAssetClass, int] = {
    HarvestAssetClass.EQUITY: 365,
    HarvestAssetClass.EQUITY_MF: 365,
    HarvestAssetClass.DEBT_MF: 365 * 3,  # post-2023 reform makes this moot
    HarvestAssetClass.US_STOCK: 365 * 2,
    HarvestAssetClass.GOLD: 365 * 3,
}

_STCG_RATE: dict[HarvestAssetClass, Decimal] = {
    HarvestAssetClass.EQUITY: Decimal("0.15"),
    HarvestAssetClass.EQUITY_MF: Decimal("0.15"),
}

_LTCG_RATE: dict[HarvestAssetClass, Decimal] = {
    HarvestAssetClass.EQUITY: Decimal("0.10"),
    HarvestAssetClass.EQUITY_MF: Decimal("0.10"),
    HarvestAssetClass.US_STOCK: Decimal("0.20"),  # with indexation; approximation
    HarvestAssetClass.GOLD: Decimal("0.20"),
}


def _term_for(lot: OpenLot, today: date) -> str:
    """STCG vs LTCG label using India's per-asset holding-period rules."""
    days_held = (today - lot.acquired_on).days
    threshold = _LONG_TERM_THRESHOLD_DAYS.get(lot.asset_class, 365)
    return "LTCG" if days_held >= threshold else "STCG"


def _loss_per_lot(lot: OpenLot) -> Decimal:
    """Positive number = loss; zero or negative = no loss to harvest."""
    book = lot.qty * lot.cost_basis_inr_per_unit
    market = lot.qty * lot.current_price_inr
    return book - market  # positive when market < book


def _effective_rate(base: Decimal, surcharge: Decimal) -> Decimal:
    """Apply surcharge (no cess for simplicity; cess adds ~4% if needed)."""
    return base * (Decimal("1") + surcharge)


def suggest_harvest(
    lots: Sequence[OpenLot],
    ctx: FYContext,
    *,
    today: date | None = None,
    min_loss_inr: Decimal = Decimal("500"),
) -> HarvestPlan:
    """Score every open lot, return the ranked plan.

    Args:
        lots: open lots (no closed/sold lots — those have already been
            realised and have nothing to harvest).
        ctx: realised-so-far context for this FY.
        today: override "now" (testing); defaults to date.today().
        min_loss_inr: ignore lots whose harvestable loss is below this
            (rounding / micro-positions noise).
    """
    today = today or date.today()
    plan = HarvestPlan(
        fy=f"{ctx.fy_start.year}-{ctx.fy_end.year % 100:02d}"
    )

    # Track remaining offsetable gains as we plan — first-fit greedy by
    # tax saved.
    pool_stcg = ctx.realised_stcg_equity_inr
    pool_ltcg = ctx.realised_ltcg_equity_inr
    pool_debt = ctx.realised_debt_gain_inr
    ltcg_exemption_left = Decimal("100000")  # ₹1L per FY

    # Compute candidate metrics first so we can rank.
    candidates: list[HarvestSuggestion] = []
    for lot in lots:
        loss = _loss_per_lot(lot)
        if loss <= min_loss_inr:
            continue
        term = _term_for(lot, today)
        # Skip lots we know can't offset anything useful.
        offset_label, est_savings = _score_lot(
            lot=lot,
            loss=loss,
            term=term,
            pool_stcg=pool_stcg,
            pool_ltcg=pool_ltcg,
            pool_debt=pool_debt,
            ltcg_exemption_left=ltcg_exemption_left,
            ctx=ctx,
        )
        if est_savings <= 0:
            # No tax-saving benefit even though it's a loss — skip.
            continue
        warning = None
        # 30-day attention flag: anyone closing a position for tax purposes
        # and re-buying inside a month may want to document the intent.
        days_until_fy_end = (ctx.fy_end - today).days
        if days_until_fy_end < 30:
            warning = (
                "Within 30 days of FY end — consider whether you intend to "
                "re-establish the position immediately. India has no formal "
                "wash-sale rule but assessors notice."
            )
        candidates.append(
            HarvestSuggestion(
                lot_id=lot.lot_id,
                symbol=lot.symbol,
                asset_class=lot.asset_class,
                term=term,
                qty=lot.qty,
                loss_inr=loss,
                offsets_against=offset_label,
                estimated_tax_saved_inr=est_savings,
                warning=warning,
            )
        )

    # Rank by tax saved.
    candidates.sort(key=lambda c: c.estimated_tax_saved_inr, reverse=True)

    # Re-walk in ranked order and *commit* the consumption of the pools so
    # the total at the bottom is realistic (not double-counted).
    pool_stcg = ctx.realised_stcg_equity_inr
    pool_ltcg = ctx.realised_ltcg_equity_inr
    pool_debt = ctx.realised_debt_gain_inr
    ltcg_exemption_left = Decimal("100000")

    committed: list[HarvestSuggestion] = []
    for c in candidates:
        # Re-score against current (post-consumption) pools.
        # We use the lot to look up the original loss + term.
        # Find back the OpenLot quickly:
        lot = next((l for l in lots if l.lot_id == c.lot_id), None)
        if lot is None:
            continue
        loss = c.loss_inr
        term = c.term
        label, savings = _score_lot(
            lot=lot,
            loss=loss,
            term=term,
            pool_stcg=pool_stcg,
            pool_ltcg=pool_ltcg,
            pool_debt=pool_debt,
            ltcg_exemption_left=ltcg_exemption_left,
            ctx=ctx,
        )
        if savings <= 0:
            continue
        committed.append(
            HarvestSuggestion(
                lot_id=c.lot_id,
                symbol=c.symbol,
                asset_class=c.asset_class,
                term=term,
                qty=c.qty,
                loss_inr=loss,
                offsets_against=label,
                estimated_tax_saved_inr=savings,
                warning=c.warning,
            )
        )
        # Consume the pool for the next iteration.
        if term == "STCG" and lot.asset_class in (
            HarvestAssetClass.EQUITY,
            HarvestAssetClass.EQUITY_MF,
        ):
            used = min(loss, pool_stcg)
            pool_stcg -= used
            # Any leftover STCG-loss spills into LTCG offset (allowed).
            spill = loss - used
            ltcg_used = min(spill, pool_ltcg)
            pool_ltcg -= ltcg_used
        elif term == "LTCG" and lot.asset_class in (
            HarvestAssetClass.EQUITY,
            HarvestAssetClass.EQUITY_MF,
        ):
            used = min(loss, pool_ltcg)
            pool_ltcg -= used
        elif lot.asset_class == HarvestAssetClass.DEBT_MF:
            used = min(loss, pool_debt)
            pool_debt -= used

    plan.suggestions = committed
    plan.total_loss_inr = sum(
        (c.loss_inr for c in committed), Decimal("0")
    )
    plan.total_tax_saved_inr = sum(
        (c.estimated_tax_saved_inr for c in committed), Decimal("0")
    )
    return plan


def _score_lot(
    *,
    lot: OpenLot,
    loss: Decimal,
    term: str,
    pool_stcg: Decimal,
    pool_ltcg: Decimal,
    pool_debt: Decimal,
    ltcg_exemption_left: Decimal,
    ctx: FYContext,
) -> tuple[str, Decimal]:
    """Score a single lot's offset potential. Returns (label, tax_saved_inr).

    Pure function — no side-effects on the pools.
    """
    ac = lot.asset_class
    # Equity STCG loss: matches STCG first (best), then LTCG.
    if term == "STCG" and ac in (
        HarvestAssetClass.EQUITY,
        HarvestAssetClass.EQUITY_MF,
    ):
        offset_stcg = min(loss, pool_stcg)
        savings_stcg = offset_stcg * _effective_rate(
            _STCG_RATE[ac], ctx.surcharge_rate
        )
        remainder = loss - offset_stcg
        offset_ltcg = min(remainder, pool_ltcg)
        # LTCG-spillover savings: again compute as delta in *taxable* LTCG,
        # honouring the ₹1L exemption.
        taxable_before_ltcg = max(pool_ltcg - ltcg_exemption_left, Decimal("0"))
        taxable_after_ltcg = max(pool_ltcg - offset_ltcg - ltcg_exemption_left, Decimal("0"))
        delta_ltcg = taxable_before_ltcg - taxable_after_ltcg
        savings_ltcg = delta_ltcg * _effective_rate(
            _LTCG_RATE[ac], ctx.surcharge_rate
        )
        savings = savings_stcg + savings_ltcg
        if savings <= 0:
            return ("", Decimal("0"))
        label = "STCG equity (already realised)"
        if savings_ltcg > 0:
            label += " + LTCG spillover"
        return (label, savings)

    if term == "LTCG" and ac in (
        HarvestAssetClass.EQUITY,
        HarvestAssetClass.EQUITY_MF,
    ):
        # Correct economics: the ₹1L exemption applies once per FY to the
        # pool, *not* to the harvest. Compute the change in taxable LTCG
        # before vs after the harvest, then apply the rate.
        offset = min(loss, pool_ltcg)
        taxable_before = max(pool_ltcg - ltcg_exemption_left, Decimal("0"))
        taxable_after = max(pool_ltcg - offset - ltcg_exemption_left, Decimal("0"))
        delta = taxable_before - taxable_after
        savings = delta * _effective_rate(_LTCG_RATE[ac], ctx.surcharge_rate)
        if savings <= 0:
            return ("", Decimal("0"))
        return ("LTCG equity (already realised, above ₹1L)", savings)

    if ac == HarvestAssetClass.DEBT_MF:
        offset = min(loss, pool_debt)
        savings = offset * _effective_rate(ctx.marginal_slab_rate, ctx.surcharge_rate)
        if savings <= 0:
            return ("", Decimal("0"))
        return ("Debt-MF gain (slab rate)", savings)

    # US stocks / gold LTCG: similar to equity LTCG but 20% rate, no ₹1L floor.
    if term == "LTCG" and ac in (HarvestAssetClass.US_STOCK, HarvestAssetClass.GOLD):
        # No common pool for non-equity LTCG in this simplified model —
        # we can carry forward 8 years; estimate value at the surcharge-
        # adjusted marginal rate of the offset's natural counterpart.
        savings = loss * _effective_rate(
            _LTCG_RATE.get(ac, Decimal("0.20")), ctx.surcharge_rate
        )
        # Discount because we're estimating future-year offset.
        savings *= Decimal("0.5")
        return ("Carry-forward LTCG (8-year window)", savings)

    return ("", Decimal("0"))


__all__ = [
    "DISCLAIMER",
    "FYContext",
    "HarvestAssetClass",
    "HarvestPlan",
    "HarvestSuggestion",
    "OpenLot",
    "suggest_harvest",
]
