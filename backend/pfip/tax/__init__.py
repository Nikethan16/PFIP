"""Indian tax module — advisory only.

Implements Appendix F rules:
    - STCG / LTCG with 31-Jan-2018 grandfathering
    - VDA 30% + 1% TDS, no loss set-off
    - Schedule FA (peak balance USD + INR)
    - Form 67 / DTAA Section 90 credit for US dividends
    - 80C / 80CCD(1B) optimiser
    - Old-vs-new regime comparison
    - Surcharge-cliff flagger
    - ITR form router

Never files anything — always returns advisory output with ``DISCLAIMER``.
"""

from pfip.tax.engine import (  # noqa: F401
    AssetClass,
    CGEvent,
    Form67Row,
    GainTerm,
    ScheduleFARow,
    TaxSummary,
    build_tax_summary,
    classify_capital_gains,
    compare_regimes,
    compute_80c_optimizer,
    compute_form_67,
    compute_ltcg,
    compute_schedule_fa,
    compute_stcg,
    compute_vda_tax,
    dividend_tax,
    fy_bounds,
    itr_form_recommendation,
    surcharge_cliff_check,
)
from pfip.tax.indian_rules import DISCLAIMER  # noqa: F401

__all__ = [
    "AssetClass",
    "CGEvent",
    "DISCLAIMER",
    "Form67Row",
    "GainTerm",
    "ScheduleFARow",
    "TaxSummary",
    "build_tax_summary",
    "classify_capital_gains",
    "compare_regimes",
    "compute_80c_optimizer",
    "compute_form_67",
    "compute_ltcg",
    "compute_schedule_fa",
    "compute_stcg",
    "compute_vda_tax",
    "dividend_tax",
    "fy_bounds",
    "itr_form_recommendation",
    "surcharge_cliff_check",
]
