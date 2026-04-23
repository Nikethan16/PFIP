"""Core Indian tax engine.

Implements every rule from Appendix F of the platform plan:

- Capital-gains classifier (FIFO, with 31-Jan-2018 grandfathering for equity).
- STCG / LTCG for equity, debt MFs, non-equity.
- VDA flat 30% tax with 1% TDS tracking and no loss set-off.
- Schedule FA (peak balance USD + INR, dividends).
- Form 67 for DTAA foreign-tax-credit claims.
- 80C optimiser + old-vs-new regime comparison.
- Surcharge cliff detection.
- ITR form routing.
- Dividend slab-rate taxation (post-2020).

Everything is advisory. Every structured result carries ``DISCLAIMER``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pfip.core.contracts import PortfolioTx, PortfolioTxKind
from pfip.tax.fx_cost_basis import convert_to_inr
from pfip.tax.indian_rules import (
    DEBT_MF_SLAB_REGIME_START,
    DEDUCTION_LIMITS_INR,
    DISCLAIMER,
    EQUITY_LT_MONTHS,
    GRANDFATHERING_DATE,
    HEC_CESS_RATE,
    ITR_FORMS,
    LTCG_EQUITY_EXEMPT_INR,
    LTCG_EQUITY_RATE,
    NEW_REGIME_SURCHARGE_CAP,
    STCG_EQUITY_RATE,
    SURCHARGE_BANDS,
    US_DIVIDEND_WHT_RATE,
    VDA_RATE,
    VDA_TDS_RATE,
    SlabBand,
    get_slabs,
    is_vda,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class AssetClass(str, Enum):
    """Tax-relevant asset class."""

    EQUITY = "equity"
    EQUITY_MF = "equity_mf"
    DEBT_MF = "debt_mf"
    DEBT = "debt"
    VDA = "vda"
    US_STOCK = "us_stock"
    GOLD = "gold"
    OTHER = "other"


class GainTerm(str, Enum):
    """Short-term vs long-term label."""

    STCG = "STCG"
    LTCG = "LTCG"


@dataclass(slots=True)
class Lot:
    """A purchased lot used in FIFO matching."""

    symbol: str
    qty: Decimal
    price_inr: Decimal  # per-unit
    acquired_on: date
    fair_mkt_31_jan_2018: Decimal | None = None  # grandfathered FMV per unit
    asset_class: AssetClass = AssetClass.EQUITY
    fx_rate_at_buy: Decimal | None = None
    ccy: str = "INR"


@dataclass(slots=True)
class CGEvent:
    """One classified capital-gains realisation event."""

    symbol: str
    asset_class: AssetClass
    term: GainTerm
    qty: Decimal
    buy_date: date
    sell_date: date
    buy_cost_inr: Decimal
    sell_proceeds_inr: Decimal
    gain_inr: Decimal
    grandfathered: bool = False
    tds_inr: Decimal = Decimal("0")
    notes: str | None = None


@dataclass(slots=True)
class ScheduleFARow:
    """A Schedule FA row: one foreign asset, one FY."""

    country: str
    symbol: str
    isin: str | None
    acquired_on: date | None
    peak_balance_usd: Decimal
    peak_balance_inr: Decimal
    closing_balance_usd: Decimal
    closing_balance_inr: Decimal
    gross_interest_usd: Decimal
    gross_dividend_usd: Decimal
    gross_proceeds_usd: Decimal


@dataclass(slots=True)
class Form67Row:
    """One row of Form 67 — foreign-source income + tax withheld + DTAA credit."""

    country: str
    source_name: str  # e.g. "AAPL dividend"
    foreign_income_inr: Decimal
    tax_paid_abroad_inr: Decimal
    indian_tax_on_same_income_inr: Decimal
    dtaa_credit_inr: Decimal  # min of the two
    section: str = "90"


@dataclass(slots=True)
class TaxSummary:
    """Rolled-up FY tax snapshot."""

    fy: str
    stcg_equity_inr: Decimal
    ltcg_equity_inr: Decimal
    vda_gain_inr: Decimal
    vda_tds_inr: Decimal
    dividend_inr: Decimal
    interest_inr: Decimal
    total_tax_inr: Decimal
    recommended_regime: str
    recommended_itr: str
    surcharge_cliff_warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


# ---------------------------------------------------------------------------
# FY helpers
# ---------------------------------------------------------------------------


def fy_bounds(fy: str) -> tuple[date, date]:
    """Return ``(start, end)`` dates for Indian FY ``YYYY-YY``.

    Example: ``"2026-27"`` → ``(2026-04-01, 2027-03-31)``.
    """
    start_y = int(fy.split("-")[0])
    return (date(start_y, 4, 1), date(start_y + 1, 3, 31))


def in_fy(d: date, fy: str) -> bool:
    """True if ``d`` falls within FY ``fy``."""
    start, end = fy_bounds(fy)
    return start <= d <= end


# ---------------------------------------------------------------------------
# Capital-gains classifier (FIFO)
# ---------------------------------------------------------------------------


def _tx_date(tx: PortfolioTx | dict) -> date:
    """Resolve a PortfolioTx time to a date."""
    t: Any = tx.time if hasattr(tx, "time") else tx["time"]
    if isinstance(t, datetime):
        return t.date()
    if isinstance(t, date):
        return t
    return datetime.fromisoformat(str(t)).date()


def _tx_qty(tx: PortfolioTx | dict) -> Decimal:
    q = tx.qty if hasattr(tx, "qty") else tx.get("qty")
    return Decimal("0") if q is None else Decimal(str(q))


def _tx_price(tx: PortfolioTx | dict) -> Decimal:
    p = tx.price if hasattr(tx, "price") else tx.get("price")
    return Decimal("0") if p is None else Decimal(str(p))


def _tx_kind(tx: PortfolioTx | dict) -> PortfolioTxKind:
    k = tx.kind if hasattr(tx, "kind") else tx["kind"]
    return k if isinstance(k, PortfolioTxKind) else PortfolioTxKind(k)


def _tx_symbol(tx: PortfolioTx | dict) -> str:
    # The contract stores symbol on the holding, not the tx; callers pass enriched dicts.
    if hasattr(tx, "symbol"):
        return str(getattr(tx, "symbol"))
    return str(tx.get("symbol", ""))


def _tx_tds(tx: PortfolioTx | dict) -> Decimal:
    v = tx.tax_withheld if hasattr(tx, "tax_withheld") else tx.get("tax_withheld", 0)
    return Decimal(str(v or 0))


def _asset_class_for(symbol: str, declared: AssetClass | str | None) -> AssetClass:
    if declared is not None:
        return declared if isinstance(declared, AssetClass) else AssetClass(declared)
    if is_vda(symbol):
        return AssetClass.VDA
    return AssetClass.EQUITY


def _months_between(a: date, b: date) -> int:
    """Approximate calendar-months between two dates (b >= a)."""
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def classify_capital_gains(
    tx_list: list[dict],
    *,
    asset_class_hint: AssetClass | str | None = None,
    fmv_31jan2018: dict[str, Decimal] | None = None,
) -> list[CGEvent]:
    """Match sells to buys using FIFO and emit ``CGEvent``s.

    Args:
        tx_list: list of enriched tx dicts. Required keys:
            ``symbol``, ``time``, ``kind``, ``qty``, ``price`` (per-unit INR).
            Optional: ``asset_class``, ``tax_withheld`` (TDS on sell).
        asset_class_hint: default when individual tx does not specify one.
        fmv_31jan2018: mapping symbol→fair market value on 31-Jan-2018
            (per-unit INR). Used for grandfathered equity cost uplift.

    Returns:
        List of ``CGEvent`` ordered by sell date.

    Grandfathering rule (Section 112A):
        For equity acquired BEFORE 31-Jan-2018 and sold AFTER it, the cost of
        acquisition is the HIGHER of:
            (a) actual cost, and
            (b) LOWER of [FMV on 31-Jan-2018, sale consideration].
    """
    fmv_31jan2018 = fmv_31jan2018 or {}

    # Build FIFO queue per symbol.
    lots: dict[str, deque[Lot]] = {}
    events: list[CGEvent] = []

    # Sort tx ascending by time so FIFO is correct.
    ordered = sorted(tx_list, key=_tx_date)

    for tx in ordered:
        kind = _tx_kind(tx)
        sym = _tx_symbol(tx)
        if not sym:
            continue
        ac_raw = tx.get("asset_class") if isinstance(tx, dict) else None
        ac = _asset_class_for(sym, ac_raw or asset_class_hint)
        qty = _tx_qty(tx)
        price = _tx_price(tx)
        td = _tx_date(tx)

        if kind == PortfolioTxKind.BUY and qty > 0:
            lots.setdefault(sym, deque()).append(
                Lot(
                    symbol=sym,
                    qty=qty,
                    price_inr=price,
                    acquired_on=td,
                    fair_mkt_31_jan_2018=fmv_31jan2018.get(sym),
                    asset_class=ac,
                )
            )
            continue

        if kind != PortfolioTxKind.SELL or qty <= 0:
            continue

        # FIFO match
        remaining = qty
        queue = lots.get(sym) or deque()
        tds = _tx_tds(tx)
        while remaining > 0 and queue:
            lot = queue[0]
            take = min(remaining, lot.qty)
            # Cost basis computation with grandfathering for equity:
            buy_cost_per_unit = lot.price_inr
            grandfathered = False
            if (
                ac in (AssetClass.EQUITY, AssetClass.EQUITY_MF)
                and lot.acquired_on < GRANDFATHERING_DATE
                and td >= GRANDFATHERING_DATE
            ):
                fmv = lot.fair_mkt_31_jan_2018
                if fmv is not None:
                    # higher of actual cost and (lower of FMV and sale price)
                    floor_side = min(fmv, price)
                    buy_cost_per_unit = max(lot.price_inr, floor_side)
                    grandfathered = True

            buy_cost = (buy_cost_per_unit * take).quantize(Decimal("0.01"))
            proceeds = (price * take).quantize(Decimal("0.01"))
            gain = proceeds - buy_cost

            months = _months_between(lot.acquired_on, td)
            is_long = months >= EQUITY_LT_MONTHS
            # Debt MF / debt: pre-2023 used 36 months; post-2023 slab taxed regardless.
            if ac in (AssetClass.DEBT_MF, AssetClass.DEBT):
                if lot.acquired_on >= DEBT_MF_SLAB_REGIME_START:
                    # Slab-taxed — classify as STCG so caller slab-taxes it.
                    is_long = False
                else:
                    is_long = months >= 36
            if ac == AssetClass.VDA:
                # No STCG/LTCG distinction; tag everything as STCG so caller
                # routes to ``compute_vda_tax``. Term is informational only.
                is_long = False

            events.append(
                CGEvent(
                    symbol=sym,
                    asset_class=ac,
                    term=GainTerm.LTCG if is_long else GainTerm.STCG,
                    qty=take,
                    buy_date=lot.acquired_on,
                    sell_date=td,
                    buy_cost_inr=buy_cost,
                    sell_proceeds_inr=proceeds,
                    gain_inr=gain,
                    grandfathered=grandfathered,
                    tds_inr=(tds * (take / qty)).quantize(Decimal("0.01")) if qty else Decimal("0"),
                )
            )

            lot.qty -= take
            remaining -= take
            if lot.qty <= 0:
                queue.popleft()

        # Any "remaining" here means a short sale or missing lot — we surface as
        # a zero-cost-basis event so the user notices (never silently drop).
        if remaining > 0:
            events.append(
                CGEvent(
                    symbol=sym,
                    asset_class=ac,
                    term=GainTerm.STCG,
                    qty=remaining,
                    buy_date=td,
                    sell_date=td,
                    buy_cost_inr=Decimal("0"),
                    sell_proceeds_inr=(price * remaining).quantize(Decimal("0.01")),
                    gain_inr=(price * remaining).quantize(Decimal("0.01")),
                    grandfathered=False,
                    notes="No matching buy lot found; treated as zero-cost. Reconcile with broker.",
                )
            )

    return sorted(events, key=lambda e: e.sell_date)


# ---------------------------------------------------------------------------
# STCG / LTCG / VDA
# ---------------------------------------------------------------------------


def compute_stcg(events: list[CGEvent], asset_class: AssetClass | None = None) -> Decimal:
    """Compute STCG tax (rupees) across ``events``.

    Equity / Equity-MF → flat 15% (Section 111A).
    Debt / Debt-MF → slab (returned as 0 here; caller combines with slab income).
    VDA → handled separately by ``compute_vda_tax``.
    """
    tax = Decimal("0")
    for e in events:
        if e.term != GainTerm.STCG:
            continue
        if asset_class is not None and e.asset_class != asset_class:
            continue
        if e.asset_class in (AssetClass.EQUITY, AssetClass.EQUITY_MF, AssetClass.US_STOCK):
            # US stock STCG: slab-taxed in India, but plan treats as equity-like
            # for mark-to-market UX. Here we apply equity STCG rate for ease;
            # caller can override by passing asset_class=EQUITY.
            if e.asset_class == AssetClass.US_STOCK:
                # US stock is slab-rated when sold — return 0 so the slab
                # calculator catches it alongside ordinary income.
                continue
            if e.gain_inr > 0:
                tax += (e.gain_inr * STCG_EQUITY_RATE).quantize(Decimal("0.01"))
    return tax


def compute_ltcg(events: list[CGEvent], asset_class: AssetClass | None = None) -> Decimal:
    """Compute LTCG tax (rupees) for equity-class gains.

    - Net equity LTCG is aggregated per FY.
    - First ₹1,00,000 exempt (Section 112A).
    - 10% on the excess.
    """
    equity_gains = Decimal("0")
    for e in events:
        if e.term != GainTerm.LTCG:
            continue
        if asset_class is not None and e.asset_class != asset_class:
            continue
        if e.asset_class in (AssetClass.EQUITY, AssetClass.EQUITY_MF):
            equity_gains += e.gain_inr
    if equity_gains <= LTCG_EQUITY_EXEMPT_INR:
        return Decimal("0")
    taxable = equity_gains - LTCG_EQUITY_EXEMPT_INR
    return (taxable * LTCG_EQUITY_RATE).quantize(Decimal("0.01"))


def compute_vda_tax(crypto_events: list[CGEvent]) -> dict:
    """VDA taxation (Section 115BBH).

    Rules:
        - Flat 30% on gains.
        - Losses cannot be set off against any income.
        - Losses cannot be carried forward.
        - 1% TDS (Section 194S) reconciled separately.
    """
    gains = Decimal("0")
    losses = Decimal("0")
    tds_total = Decimal("0")
    per_sym: dict[str, Decimal] = {}
    for e in crypto_events:
        if e.asset_class != AssetClass.VDA:
            continue
        per_sym[e.symbol] = per_sym.get(e.symbol, Decimal("0")) + e.gain_inr
        if e.gain_inr >= 0:
            gains += e.gain_inr
        else:
            losses += e.gain_inr  # negative
        tds_total += e.tds_inr

    # Losses NOT set off:
    taxable_gains = gains  # not (gains + losses)
    tax = (taxable_gains * VDA_RATE).quantize(Decimal("0.01"))
    net_tax_after_tds = (tax - tds_total).quantize(Decimal("0.01"))

    return {
        "gross_gains_inr": gains,
        "gross_losses_inr": losses,
        "taxable_gains_inr": taxable_gains,
        "rate": VDA_RATE,
        "tax_before_tds_inr": tax,
        "tds_credit_inr": tds_total,
        "net_tax_payable_inr": net_tax_after_tds,
        "loss_setoff_allowed": False,
        "loss_carryforward_allowed": False,
        "per_symbol_net_gain_inr": per_sym,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Schedule FA + Form 67
# ---------------------------------------------------------------------------


def compute_schedule_fa(
    us_holdings: list[dict],
    dividends_usd: list[dict],
    fy: str,
    *,
    db: Any | None = None,
) -> list[ScheduleFARow]:
    """Build Schedule FA rows for an FY.

    ``us_holdings`` items: ``symbol``, ``isin`` (opt), ``acquired_on`` (date),
        ``daily_balances_usd`` (dict[date, Decimal]), ``closing_balance_usd`` (Decimal),
        ``country`` (default ``"USA"``).

    ``dividends_usd`` items: ``symbol``, ``amount_usd`` (Decimal), ``paid_on`` (date).
    """
    start, end = fy_bounds(fy)
    rows: list[ScheduleFARow] = []

    divs_by_sym: dict[str, Decimal] = {}
    for d in dividends_usd:
        paid_on = d["paid_on"]
        if not (start <= paid_on <= end):
            continue
        divs_by_sym[d["symbol"]] = divs_by_sym.get(d["symbol"], Decimal("0")) + Decimal(
            str(d["amount_usd"])
        )

    for h in us_holdings:
        daily = {
            dt: Decimal(str(v))
            for dt, v in (h.get("daily_balances_usd") or {}).items()
            if start <= dt <= end
        }
        if daily:
            peak_date = max(daily, key=lambda d: daily[d])
            peak_usd = daily[peak_date]
            peak_inr = convert_to_inr(peak_usd, "USD", peak_date, db=db)
        else:
            peak_usd = Decimal("0")
            peak_inr = Decimal("0")

        closing_usd = Decimal(str(h.get("closing_balance_usd", 0)))
        closing_inr = (
            convert_to_inr(closing_usd, "USD", end, db=db)
            if closing_usd
            else Decimal("0")
        )
        rows.append(
            ScheduleFARow(
                country=h.get("country", "USA"),
                symbol=h["symbol"],
                isin=h.get("isin"),
                acquired_on=h.get("acquired_on"),
                peak_balance_usd=peak_usd,
                peak_balance_inr=peak_inr,
                closing_balance_usd=closing_usd,
                closing_balance_inr=closing_inr,
                gross_interest_usd=Decimal("0"),
                gross_dividend_usd=divs_by_sym.get(h["symbol"], Decimal("0")),
                gross_proceeds_usd=Decimal("0"),
            )
        )
    return rows


def compute_form_67(
    us_dividends: list[dict],
    slab_rate: Decimal = Decimal("0.30"),
    *,
    db: Any | None = None,
) -> list[Form67Row]:
    """Build Form 67 rows for US dividend income.

    ``us_dividends`` items: ``symbol``, ``paid_on`` (date), ``amount_usd``,
        ``tax_withheld_usd``, optional ``fx_rate`` (USD→INR). Each row becomes
        one Form 67 line.

    DTAA credit = min(foreign tax paid in INR, Indian tax on same income).
    """
    out: list[Form67Row] = []
    for d in us_dividends:
        on = d["paid_on"]
        usd = Decimal(str(d["amount_usd"]))
        wht_usd = Decimal(str(d.get("tax_withheld_usd", usd * US_DIVIDEND_WHT_RATE)))
        fx = d.get("fx_rate")
        if fx is None:
            inr = convert_to_inr(usd, "USD", on, db=db)
            wht_inr = convert_to_inr(wht_usd, "USD", on, db=db)
        else:
            fx = Decimal(str(fx))
            inr = (usd * fx).quantize(Decimal("0.01"))
            wht_inr = (wht_usd * fx).quantize(Decimal("0.01"))

        indian_tax = (inr * slab_rate).quantize(Decimal("0.01"))
        credit = min(wht_inr, indian_tax)

        out.append(
            Form67Row(
                country="USA",
                source_name=f"{d['symbol']} dividend on {on.isoformat()}",
                foreign_income_inr=inr,
                tax_paid_abroad_inr=wht_inr,
                indian_tax_on_same_income_inr=indian_tax,
                dtaa_credit_inr=credit,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Dividends (post-2020 slab taxation)
# ---------------------------------------------------------------------------


def dividend_tax(
    dividend_events: list[dict],
    slab_rate: Decimal,
) -> dict:
    """Tax on domestic dividends (slab since FY20-21).

    ``dividend_events`` items: ``symbol``, ``amount_inr``, ``paid_on`` (date),
        optional ``tax_withheld_inr`` (reconciled against 26AS).
    """
    total = Decimal("0")
    tds = Decimal("0")
    for d in dividend_events:
        total += Decimal(str(d["amount_inr"]))
        tds += Decimal(str(d.get("tax_withheld_inr", 0)))
    tax = (total * slab_rate).quantize(Decimal("0.01"))
    return {
        "total_dividend_inr": total,
        "tds_inr": tds,
        "tax_on_dividend_inr": tax,
        "net_tax_payable_inr": (tax - tds).quantize(Decimal("0.01")),
        "note": "Post-FY20-21 dividends are slab-rated in the recipient's hands.",
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Slab computation utilities
# ---------------------------------------------------------------------------


def _slab_tax(taxable_income: Decimal, slabs: list[SlabBand]) -> Decimal:
    """Compute tax-on-slab for ``taxable_income`` using ``slabs``."""
    if taxable_income <= 0:
        return Decimal("0")
    prev = Decimal("0")
    tax = Decimal("0")
    for band in slabs:
        upper = band.upto if band.upto is not None else taxable_income
        if taxable_income > prev:
            band_income = min(taxable_income, upper) - prev
            if band_income > 0:
                tax += band_income * band.rate
            prev = upper
            if taxable_income <= upper:
                break
        else:
            break
    return tax.quantize(Decimal("0.01"))


def _apply_surcharge_and_cess(
    tax: Decimal, taxable_income: Decimal, *, new_regime: bool
) -> Decimal:
    """Apply surcharge bands then 4% cess to ``tax``."""
    surcharge_rate = Decimal("0")
    for band in SURCHARGE_BANDS:
        if taxable_income > band.threshold:
            surcharge_rate = band.rate
    if new_regime:
        surcharge_rate = min(surcharge_rate, NEW_REGIME_SURCHARGE_CAP)
    with_surcharge = tax * (Decimal("1") + surcharge_rate)
    with_cess = with_surcharge * (Decimal("1") + HEC_CESS_RATE)
    return with_cess.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Regime comparison
# ---------------------------------------------------------------------------


def compare_regimes(
    gross_income: Decimal,
    deductions: dict[str, Decimal] | None = None,
    *,
    fy: str = "2026-27",
) -> dict:
    """Compare old vs new regime; return recommended regime + both tax figures."""
    deductions = deductions or {}
    deduction_total = sum(deductions.values(), Decimal("0"))

    old_slabs = get_slabs("old", fy)
    new_slabs = get_slabs("new", fy)

    # Old regime applies deductions + standard deduction.
    old_taxable = max(
        Decimal("0"),
        gross_income
        - deduction_total
        - DEDUCTION_LIMITS_INR["STANDARD_DEDUCTION_SALARY"],
    )
    old_tax_base = _slab_tax(old_taxable, old_slabs)
    old_final = _apply_surcharge_and_cess(old_tax_base, old_taxable, new_regime=False)

    # New regime: only standard deduction (₹75k for salaried FY25-26+).
    new_taxable = max(
        Decimal("0"),
        gross_income - DEDUCTION_LIMITS_INR["STANDARD_DEDUCTION_NEW_REGIME"],
    )
    new_tax_base = _slab_tax(new_taxable, new_slabs)
    new_final = _apply_surcharge_and_cess(new_tax_base, new_taxable, new_regime=True)

    recommended = "new" if new_final <= old_final else "old"
    return {
        "fy": fy,
        "gross_income_inr": gross_income,
        "deduction_total_inr": deduction_total,
        "old_regime_tax_inr": old_final,
        "new_regime_tax_inr": new_final,
        "recommended_regime": recommended,
        "savings_if_switch_inr": abs(old_final - new_final),
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# 80C optimiser
# ---------------------------------------------------------------------------


def compute_80c_optimizer(
    current_investments: dict[str, Decimal],
    income_slab: Decimal,
) -> dict:
    """Rank remaining 80C-style options by marginal tax benefit.

    Args:
        current_investments: mapping of instrument code → amount already
            invested this FY (e.g. ``{"PPF": 50000, "ELSS": 25000, "NPS": 0}``).
        income_slab: the user's marginal slab rate (e.g. ``0.30``).

    Returns advisory dict with per-instrument available headroom and tax saved.
    """
    used_80c = sum(
        current_investments.get(k, Decimal("0"))
        for k in ("PPF", "ELSS", "EPF", "ULIP", "LIC", "SSY", "NSC", "5Y_FD")
    )
    remaining_80c = max(Decimal("0"), DEDUCTION_LIMITS_INR["80C"] - used_80c)
    used_nps_1b = current_investments.get("NPS_1B", Decimal("0"))
    remaining_80ccd_1b = max(
        Decimal("0"), DEDUCTION_LIMITS_INR["80CCD_1B"] - used_nps_1b
    )

    # Scoring: combination of (a) tax saved = amount * slab, (b) liquidity,
    # (c) lock-in, (d) post-tax return prior.
    instruments = [
        {
            "code": "PPF",
            "fits_under": "80C",
            "headroom_inr": remaining_80c,
            "tax_saved_if_maxed_inr": (remaining_80c * income_slab).quantize(Decimal("0.01")),
            "lock_in_years": 15,
            "post_tax_return_pct": 7.1,
            "liquidity": "low",
            "rationale": "EEE; sovereign-backed; inflation-adjusted returns.",
        },
        {
            "code": "ELSS",
            "fits_under": "80C",
            "headroom_inr": remaining_80c,
            "tax_saved_if_maxed_inr": (remaining_80c * income_slab).quantize(Decimal("0.01")),
            "lock_in_years": 3,
            "post_tax_return_pct": 12.0,  # historical, not guaranteed
            "liquidity": "medium",
            "rationale": "Shortest 80C lock-in; equity upside; LTCG @ 10% over ₹1L.",
        },
        {
            "code": "NPS_1B",
            "fits_under": "80CCD(1B)",
            "headroom_inr": remaining_80ccd_1b,
            "tax_saved_if_maxed_inr": (remaining_80ccd_1b * income_slab).quantize(
                Decimal("0.01")
            ),
            "lock_in_years": 60,  # till age 60
            "post_tax_return_pct": 9.0,  # assumed balanced
            "liquidity": "low",
            "rationale": "Extra ₹50k deduction over and above ₹1.5L 80C.",
        },
    ]
    ranked = sorted(
        instruments,
        key=lambda i: (i["tax_saved_if_maxed_inr"], -i["lock_in_years"]),
        reverse=True,
    )
    return {
        "ranked": ranked,
        "total_tax_saved_if_max_all_inr": sum(
            (i["tax_saved_if_maxed_inr"] for i in ranked), Decimal("0")
        ),
        "note": "Scoring weighs tax saved, lock-in, and post-tax return. Not investment advice.",
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Surcharge cliff detection
# ---------------------------------------------------------------------------


def surcharge_cliff_check(taxable_income: Decimal) -> dict:
    """Flag proximity to each surcharge threshold (₹50L/1Cr/2Cr/5Cr)."""
    flags: list[dict] = []
    for band in SURCHARGE_BANDS:
        delta = band.threshold - taxable_income
        proximity = "below" if delta > 0 else "above"
        within_5pct = abs(delta) <= band.threshold * Decimal("0.05")
        flags.append(
            {
                "threshold_inr": band.threshold,
                "surcharge_rate": band.rate,
                "distance_inr": delta,
                "position": proximity,
                "within_5_pct": within_5pct,
            }
        )
    return {
        "taxable_income_inr": taxable_income,
        "flags": flags,
        "note": (
            "A marginal sale that crosses a cliff can raise the surcharge tier. "
            "Consider deferring realisation if within a percentage point."
        ),
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# ITR form routing
# ---------------------------------------------------------------------------


def itr_form_recommendation(
    income_sources: dict[str, bool],
) -> dict:
    """Pick the appropriate ITR form.

    ``income_sources`` booleans:
        ``salary``, ``house_property``, ``capital_gains``, ``business``,
        ``foreign_assets``, ``presumptive``.
    """
    sources = {k: bool(v) for k, v in income_sources.items()}
    if sources.get("foreign_assets") or sources.get("capital_gains"):
        form = "ITR-3" if sources.get("business") else "ITR-2"
    elif sources.get("business"):
        form = "ITR-3"
    elif sources.get("presumptive"):
        form = "ITR-4"
    else:
        form = "ITR-1"
    return {
        "recommended_form": form,
        "why": ITR_FORMS[form],
        "all_applicable": list(ITR_FORMS.keys()),
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# End-to-end FY summary
# ---------------------------------------------------------------------------


def build_tax_summary(
    fy: str,
    events: list[CGEvent],
    *,
    gross_income: Decimal = Decimal("0"),
    deductions: dict[str, Decimal] | None = None,
    dividends: list[dict] | None = None,
    has_foreign_assets: bool = False,
    has_business: bool = False,
) -> TaxSummary:
    """Roll up STCG / LTCG / VDA / dividend + regime recommendation."""
    fy_events = [e for e in events if in_fy(e.sell_date, fy)]
    equity_stcg = sum(
        (e.gain_inr for e in fy_events if e.term == GainTerm.STCG and e.asset_class
         in (AssetClass.EQUITY, AssetClass.EQUITY_MF)),
        Decimal("0"),
    )
    equity_ltcg = sum(
        (e.gain_inr for e in fy_events if e.term == GainTerm.LTCG and e.asset_class
         in (AssetClass.EQUITY, AssetClass.EQUITY_MF)),
        Decimal("0"),
    )
    vda_events = [e for e in fy_events if e.asset_class == AssetClass.VDA]
    vda_summary = compute_vda_tax(vda_events)

    stcg_tax = compute_stcg(fy_events)
    ltcg_tax = compute_ltcg(fy_events)

    div_total = sum(
        (Decimal(str(d["amount_inr"])) for d in (dividends or [])),
        Decimal("0"),
    )

    regime_cmp = compare_regimes(gross_income, deductions, fy=fy)
    # Total tax = slab tax on ordinary income + CG-specific taxes + VDA tax
    base_tax = Decimal(str(
        regime_cmp["new_regime_tax_inr"]
        if regime_cmp["recommended_regime"] == "new"
        else regime_cmp["old_regime_tax_inr"]
    ))
    total_tax = base_tax + stcg_tax + ltcg_tax + Decimal(str(vda_summary["tax_before_tds_inr"]))

    itr = itr_form_recommendation(
        {
            "salary": gross_income > 0,
            "capital_gains": bool(fy_events),
            "foreign_assets": has_foreign_assets,
            "business": has_business,
            "presumptive": False,
            "house_property": False,
        }
    )
    cliff = surcharge_cliff_check(gross_income)
    cliff_warnings = [
        f"Within 5% of ₹{int(f['threshold_inr']):,} cliff ({f['surcharge_rate']:.0%})"
        for f in cliff["flags"]
        if f["within_5_pct"]
    ]

    return TaxSummary(
        fy=fy,
        stcg_equity_inr=Decimal(str(equity_stcg)),
        ltcg_equity_inr=Decimal(str(equity_ltcg)),
        vda_gain_inr=Decimal(str(vda_summary["taxable_gains_inr"])),
        vda_tds_inr=Decimal(str(vda_summary["tds_credit_inr"])),
        dividend_inr=div_total,
        interest_inr=Decimal("0"),
        total_tax_inr=total_tax.quantize(Decimal("0.01")),
        recommended_regime=regime_cmp["recommended_regime"],
        recommended_itr=itr["recommended_form"],
        surcharge_cliff_warnings=cliff_warnings,
    )
