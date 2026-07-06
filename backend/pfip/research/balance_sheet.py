"""Balance-sheet insights — deterministic ratio + Altman-Z engine.

This module is pure, side-effect-free money math (per the architecture rule:
valuation / scoring math is deterministic and unit-tested, never routed through
an LLM). It takes a canonical set of balance-sheet / income-statement line
items and returns ratios with health ratings and an Altman Z-score.

Two extraction helpers (``parse_csv_bytes``, ``parse_text``) do *best-effort*
label matching from an uploaded CSV or extracted PDF text. They are lenient by
design and always echo what they parsed so the caller can correct it — we never
silently fabricate a number that wasn't on the page.

The LLM narrative lives in the API layer; this module only produces the numbers
the narrative is grounded in.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

Health = Literal["strong", "adequate", "weak", "unknown"]


class BalanceSheetInput(BaseModel):
    """Canonical line items. All optional, all in the same currency.

    Callers supply whatever the statement contains; ratios that lack their
    inputs are reported as ``unknown`` rather than guessed.
    """

    company: Optional[str] = None
    currency: str = "INR"
    period: Optional[str] = None  # e.g. "FY24" — free-text label

    total_current_assets: Optional[float] = None
    total_current_liabilities: Optional[float] = None
    inventory: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    total_debt: Optional[float] = None  # short + long borrowings
    retained_earnings: Optional[float] = None
    ebit: Optional[float] = None  # operating profit
    interest_expense: Optional[float] = None
    revenue: Optional[float] = None  # net sales
    market_cap: Optional[float] = None  # optional; improves Altman X4


class Ratio(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    health: Health = "unknown"
    interpretation: str


class AltmanZ(BaseModel):
    score: Optional[float] = None
    zone: Literal["safe", "grey", "distress", "unknown"] = "unknown"
    used_market_value: bool = False
    components: dict[str, float] = Field(default_factory=dict)
    interpretation: str


class BalanceSheetMetrics(BaseModel):
    input: BalanceSheetInput
    ratios: list[Ratio]
    altman_z: AltmanZ
    missing_fields: list[str]


def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den in (None, 0):
        return None
    return num / den


def _health_from_thresholds(
    value: Optional[float], strong: float, weak: float, higher_is_better: bool = True
) -> Health:
    if value is None:
        return "unknown"
    if higher_is_better:
        if value >= strong:
            return "strong"
        if value <= weak:
            return "weak"
        return "adequate"
    # lower is better (e.g. debt/equity)
    if value <= strong:
        return "strong"
    if value >= weak:
        return "weak"
    return "adequate"


def compute_metrics(inp: BalanceSheetInput) -> BalanceSheetMetrics:
    """Compute ratios + Altman Z from the supplied line items."""
    ratios: list[Ratio] = []

    # Current ratio ---------------------------------------------------------
    current = _safe_div(inp.total_current_assets, inp.total_current_liabilities)
    ratios.append(
        Ratio(
            key="current_ratio",
            label="Current ratio",
            value=current,
            health=_health_from_thresholds(current, strong=2.0, weak=1.0),
            interpretation=(
                "Short-term assets cover short-term liabilities "
                f"{current:.2f}× — comfortable above ~1.5×."
                if current is not None
                else "Needs current assets and current liabilities."
            ),
        )
    )

    # Quick ratio -----------------------------------------------------------
    quick_num = (
        None
        if inp.total_current_assets is None or inp.inventory is None
        else inp.total_current_assets - inp.inventory
    )
    quick = _safe_div(quick_num, inp.total_current_liabilities)
    ratios.append(
        Ratio(
            key="quick_ratio",
            label="Quick ratio",
            value=quick,
            health=_health_from_thresholds(quick, strong=1.0, weak=0.5),
            interpretation=(
                f"Liquidity excluding inventory is {quick:.2f}×."
                if quick is not None
                else "Needs current assets, inventory and current liabilities."
            ),
        )
    )

    # Debt-to-equity (lower is better) -------------------------------------
    debt = inp.total_debt if inp.total_debt is not None else inp.total_liabilities
    dte = _safe_div(debt, inp.total_equity)
    ratios.append(
        Ratio(
            key="debt_to_equity",
            label="Debt / equity",
            value=dte,
            health=_health_from_thresholds(dte, strong=0.5, weak=2.0, higher_is_better=False),
            interpretation=(
                f"Leverage is {dte:.2f}× equity"
                + (
                    " (using total liabilities — no debt line supplied)."
                    if inp.total_debt is None
                    else "."
                )
                if dte is not None
                else "Needs debt (or total liabilities) and equity."
            ),
        )
    )

    # Interest coverage -----------------------------------------------------
    icr = _safe_div(inp.ebit, inp.interest_expense)
    ratios.append(
        Ratio(
            key="interest_coverage",
            label="Interest coverage",
            value=icr,
            health=_health_from_thresholds(icr, strong=4.0, weak=1.5),
            interpretation=(
                f"Operating profit covers interest {icr:.1f}× — under ~1.5× is fragile."
                if icr is not None
                else "Needs EBIT and interest expense."
            ),
        )
    )

    # ROCE ------------------------------------------------------------------
    capital_employed = (
        None
        if inp.total_assets is None or inp.total_current_liabilities is None
        else inp.total_assets - inp.total_current_liabilities
    )
    roce = _safe_div(inp.ebit, capital_employed)
    ratios.append(
        Ratio(
            key="roce",
            label="ROCE",
            value=roce,
            health=_health_from_thresholds(roce, strong=0.15, weak=0.08),
            interpretation=(
                f"Return on capital employed is {roce * 100:.1f}%."
                if roce is not None
                else "Needs EBIT, total assets and current liabilities."
            ),
        )
    )

    altman = _altman_z(inp)

    missing = [
        name
        for name in (
            "total_current_assets",
            "total_current_liabilities",
            "total_assets",
            "total_equity",
            "ebit",
            "revenue",
            "retained_earnings",
        )
        if getattr(inp, name) is None
    ]

    return BalanceSheetMetrics(input=inp, ratios=ratios, altman_z=altman, missing_fields=missing)


def _altman_z(inp: BalanceSheetInput) -> AltmanZ:
    """Altman Z-score (original manufacturing model).

    Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
      X1 = working capital / total assets
      X2 = retained earnings / total assets
      X3 = EBIT / total assets
      X4 = market value of equity / total liabilities  (book equity if no mkt cap)
      X5 = sales / total assets
    """
    ta = inp.total_assets
    if ta in (None, 0):
        return AltmanZ(interpretation="Needs total assets to compute an Altman Z-score.")

    wc = (
        None
        if inp.total_current_assets is None or inp.total_current_liabilities is None
        else inp.total_current_assets - inp.total_current_liabilities
    )
    equity_for_x4 = inp.market_cap if inp.market_cap is not None else inp.total_equity
    total_liabs = inp.total_liabilities
    if inp.market_cap is None and total_liabs is None and inp.total_debt is not None:
        total_liabs = inp.total_debt

    x1 = _safe_div(wc, ta)
    x2 = _safe_div(inp.retained_earnings, ta)
    x3 = _safe_div(inp.ebit, ta)
    x4 = _safe_div(equity_for_x4, total_liabs)
    x5 = _safe_div(inp.revenue, ta)

    parts = {"X1": x1, "X2": x2, "X3": x3, "X4": x4, "X5": x5}
    present = {k: v for k, v in parts.items() if v is not None}
    # Require the profitability + turnover drivers to be meaningful.
    if any(parts[k] is None for k in ("X1", "X2", "X3", "X5")):
        return AltmanZ(
            components={k: round(v, 4) for k, v in present.items()},
            interpretation=(
                "Incomplete — Altman Z needs working capital, retained earnings, "
                "EBIT, sales and total assets (and ideally total liabilities)."
            ),
        )

    coeffs = {"X1": 1.2, "X2": 1.4, "X3": 3.3, "X4": 0.6, "X5": 1.0}
    score = sum(coeffs[k] * parts[k] for k in coeffs if parts[k] is not None)

    if score >= 2.99:
        zone: Literal["safe", "grey", "distress"] = "safe"
        interp = "Z ≥ 2.99 — financially healthy, low distress risk."
    elif score >= 1.81:
        zone = "grey"
        interp = "1.81 ≤ Z < 2.99 — grey zone, monitor leverage and profitability."
    else:
        zone = "distress"
        interp = "Z < 1.81 — distress zone, elevated bankruptcy risk (model estimate)."

    return AltmanZ(
        score=score,
        zone=zone,
        used_market_value=inp.market_cap is not None,
        components={k: round(v, 4) for k, v in present.items()},
        interpretation=interp,
    )


# --- best-effort extraction -------------------------------------------------

# Canonical field → the label fragments we accept (lowercased, substring match).
_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "total_current_assets": ("total current assets", "current assets"),
    "total_current_liabilities": ("total current liabilities", "current liabilities"),
    "inventory": ("inventories", "inventory"),
    "total_assets": ("total assets",),
    "total_liabilities": ("total liabilities",),
    "total_equity": (
        "total equity",
        "shareholders' equity",
        "shareholders equity",
        "total shareholders funds",
        "net worth",
    ),
    "total_debt": ("total debt", "borrowings", "total borrowings"),
    "retained_earnings": ("retained earnings", "reserves and surplus", "reserves & surplus"),
    "ebit": ("operating profit", "ebit", "profit before interest and tax"),
    "interest_expense": ("interest expense", "finance costs", "interest"),
    "revenue": ("revenue from operations", "total revenue", "net sales", "revenue", "sales"),
    "market_cap": ("market capitalisation", "market capitalization", "market cap"),
}

_NUMBER_RE = re.compile(r"-?\(?\d[\d,]*\.?\d*\)?")


def _parse_number(token: str) -> Optional[float]:
    """Parse '1,234.5', '(1,234)' (negative) → float; else None."""
    t = token.strip()
    if not t:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if neg else val


def _match_field(label: str) -> Optional[str]:
    """Return the canonical field for a row label, longest alias first."""
    low = label.strip().lower()
    if not low:
        return None
    best: Optional[str] = None
    best_len = 0
    for field, aliases in _LABEL_ALIASES.items():
        for alias in aliases:
            if alias in low and len(alias) > best_len:
                best = field
                best_len = len(alias)
    return best


def _assign_from_pairs(pairs: list[tuple[str, Optional[float]]]) -> dict[str, float]:
    """Given (label, number) pairs, assign the first hit per canonical field."""
    out: dict[str, float] = {}
    for label, number in pairs:
        if number is None:
            continue
        field = _match_field(label)
        if field and field not in out:
            out[field] = number
    return out


def parse_csv_bytes(data: bytes) -> dict[str, float]:
    """Parse a two-column (label, value) CSV into canonical line items."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    pairs: list[tuple[str, Optional[float]]] = []
    for row in reader:
        if not row:
            continue
        label = row[0]
        number = None
        # take the last numeric-looking cell on the row
        for cell in row[1:]:
            n = _parse_number(cell)
            if n is not None:
                number = n
        pairs.append((label, number))
    return _assign_from_pairs(pairs)


def parse_text(text: str) -> dict[str, float]:
    """Best-effort: for each line, match a label and take the last number on it."""
    pairs: list[tuple[str, Optional[float]]] = []
    for line in text.splitlines():
        nums = _NUMBER_RE.findall(line)
        number = _parse_number(nums[-1]) if nums else None
        # label = the line with trailing numbers stripped
        label = _NUMBER_RE.sub("", line)
        pairs.append((label, number))
    return _assign_from_pairs(pairs)
