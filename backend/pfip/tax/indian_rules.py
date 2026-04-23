"""Indian tax constants & tables.

Sourced from Appendix F of the platform plan and current Income-Tax-Act rules
(FY25-26 and FY26-27). All monetary values are in INR unless specified.

IMPORTANT: these figures are config. A CA review is always required before
filing — this module is advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# ---------------------------------------------------------------------------
# Disclaimer — prepended to every structured tax response
# ---------------------------------------------------------------------------

DISCLAIMER: str = "This is guidance; consult a CA before filing."

# ---------------------------------------------------------------------------
# Key dates
# ---------------------------------------------------------------------------

#: 31-Jan-2018 grandfathering date (LTCG equity cost-basis uplift).
GRANDFATHERING_DATE: date = date(2018, 1, 31)

#: VDA TDS regime start (Section 194S) — 01-Jul-2022.
VDA_TDS_START: date = date(2022, 7, 1)

#: Debt-MF regime change (no indexation, slab-taxed) — 01-Apr-2023.
DEBT_MF_SLAB_REGIME_START: date = date(2023, 4, 1)

# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

#: STCG rate for listed equity / equity MFs (Section 111A).
STCG_EQUITY_RATE: Decimal = Decimal("0.15")

#: LTCG rate for listed equity / equity MFs (Section 112A).
LTCG_EQUITY_RATE: Decimal = Decimal("0.10")

#: LTCG exemption threshold for equity (₹1,00,000/FY).
LTCG_EQUITY_EXEMPT_INR: Decimal = Decimal("100000")

#: Equity-holding threshold for LTCG vs STCG (12 months).
EQUITY_LT_MONTHS: int = 12

#: Debt-MF holding threshold pre-2023 (36 months) — still matters for legacy lots.
DEBT_LT_MONTHS: int = 36

#: VDA (crypto) flat tax rate — Section 115BBH.
VDA_RATE: Decimal = Decimal("0.30")

#: VDA TDS — Section 194S.
VDA_TDS_RATE: Decimal = Decimal("0.01")

#: US dividend withholding rate (India-US DTAA).
US_DIVIDEND_WHT_RATE: Decimal = Decimal("0.25")

# ---------------------------------------------------------------------------
# Regime-aware slab tables (individual, non-senior)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlabBand:
    """A tax slab band: income up to ``upto`` is taxed at ``rate``.

    ``upto=None`` means the top band (unbounded).
    """

    upto: Decimal | None
    rate: Decimal


#: Old-regime slabs (FY25-26 / FY26-27 — unchanged from FY23-24 old-regime).
OLD_REGIME_SLABS_FY25_26: list[SlabBand] = [
    SlabBand(upto=Decimal("250000"), rate=Decimal("0.00")),
    SlabBand(upto=Decimal("500000"), rate=Decimal("0.05")),
    SlabBand(upto=Decimal("1000000"), rate=Decimal("0.20")),
    SlabBand(upto=None, rate=Decimal("0.30")),
]

#: New regime (default) slabs for FY25-26 (as amended by Finance Act 2024).
NEW_REGIME_SLABS_FY25_26: list[SlabBand] = [
    SlabBand(upto=Decimal("300000"), rate=Decimal("0.00")),
    SlabBand(upto=Decimal("700000"), rate=Decimal("0.05")),
    SlabBand(upto=Decimal("1000000"), rate=Decimal("0.10")),
    SlabBand(upto=Decimal("1200000"), rate=Decimal("0.15")),
    SlabBand(upto=Decimal("1500000"), rate=Decimal("0.20")),
    SlabBand(upto=None, rate=Decimal("0.30")),
]

#: New regime FY26-27 (proposed revised bands — higher 0% threshold).
NEW_REGIME_SLABS_FY26_27: list[SlabBand] = [
    SlabBand(upto=Decimal("400000"), rate=Decimal("0.00")),
    SlabBand(upto=Decimal("800000"), rate=Decimal("0.05")),
    SlabBand(upto=Decimal("1200000"), rate=Decimal("0.10")),
    SlabBand(upto=Decimal("1600000"), rate=Decimal("0.15")),
    SlabBand(upto=Decimal("2000000"), rate=Decimal("0.20")),
    SlabBand(upto=Decimal("2400000"), rate=Decimal("0.25")),
    SlabBand(upto=None, rate=Decimal("0.30")),
]


def get_slabs(regime: str, fy: str) -> list[SlabBand]:
    """Return slab bands for a regime/FY combination.

    Args:
        regime: ``"old"`` or ``"new"``.
        fy: FY string such as ``"2025-26"`` or ``"2026-27"``.
    """
    regime = regime.lower()
    if regime == "old":
        return OLD_REGIME_SLABS_FY25_26
    if regime == "new":
        if fy.startswith("2026"):
            return NEW_REGIME_SLABS_FY26_27
        return NEW_REGIME_SLABS_FY25_26
    raise ValueError(f"Unknown regime: {regime!r}; use 'old' or 'new'")


# ---------------------------------------------------------------------------
# Surcharge brackets (applies on tax, not income, above each threshold)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurchargeBand:
    """Surcharge tier: taxable income above ``threshold`` gets ``rate``."""

    threshold: Decimal
    rate: Decimal


SURCHARGE_BANDS: list[SurchargeBand] = [
    SurchargeBand(threshold=Decimal("5000000"), rate=Decimal("0.10")),
    SurchargeBand(threshold=Decimal("10000000"), rate=Decimal("0.15")),
    SurchargeBand(threshold=Decimal("20000000"), rate=Decimal("0.25")),
    SurchargeBand(threshold=Decimal("50000000"), rate=Decimal("0.37")),
]

#: New-regime surcharge is capped at 25% (even above ₹5Cr).
NEW_REGIME_SURCHARGE_CAP: Decimal = Decimal("0.25")

#: Health + Education cess, levied on (tax + surcharge).
HEC_CESS_RATE: Decimal = Decimal("0.04")

# ---------------------------------------------------------------------------
# Deduction limits (old regime only)
# ---------------------------------------------------------------------------

DEDUCTION_LIMITS_INR: dict[str, Decimal] = {
    "80C": Decimal("150000"),
    "80CCD_1B": Decimal("50000"),  # extra NPS, Tier-1 only
    "80CCD_2_SALARY_PCT": Decimal("0.10"),  # employer NPS (non-govt)
    "80D_SELF": Decimal("25000"),
    "80D_SELF_SENIOR": Decimal("50000"),
    "80D_PARENTS": Decimal("25000"),
    "80D_PARENTS_SENIOR": Decimal("50000"),
    "80TTA": Decimal("10000"),
    "80TTB": Decimal("50000"),
    "STANDARD_DEDUCTION_SALARY": Decimal("50000"),
    "STANDARD_DEDUCTION_NEW_REGIME": Decimal("75000"),
}


# ---------------------------------------------------------------------------
# VDA universe (non-exhaustive — used for "is this a VDA?" routing)
# ---------------------------------------------------------------------------

VDA_SYMBOLS: frozenset[str] = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "ADA",
        "DOT",
        "MATIC",
        "AVAX",
        "XRP",
        "LTC",
        "DOGE",
        "TRX",
        "ATOM",
        "LINK",
        "UNI",
        "NEAR",
        "APT",
        "ARB",
        "OP",
        "USDT",
        "USDC",
        "DAI",
        "SHIB",
        "BUSD",
    }
)


def is_vda(symbol: str | None) -> bool:
    """True if ``symbol`` refers to a Virtual Digital Asset."""
    if not symbol:
        return False
    upper = symbol.upper()
    # strip common quote-currency suffixes/prefixes
    for sep in ("-", "/", "_"):
        if sep in upper:
            upper = upper.split(sep)[0]
    return upper in VDA_SYMBOLS


# ---------------------------------------------------------------------------
# ITR form routing
# ---------------------------------------------------------------------------

ITR_FORMS: dict[str, str] = {
    "ITR-1": "Salary + one house + up to ₹50L income + interest income. No capital gains.",
    "ITR-2": "Salary + capital gains + foreign assets (Schedule FA). No business income.",
    "ITR-3": "ITR-2 + business/profession income (includes F&O declared as business).",
    "ITR-4": "Presumptive scheme (44AD/ADA/AE). Excludes foreign assets.",
}
