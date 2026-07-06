"""Fundamentals screener — pure filter engine over canonical key metrics.

Given a map of ``symbol → {canonical_field: value}`` (produced by
:func:`pfip.diligence.peers.load_key_metrics`) and a set of numeric criteria,
return the symbols that satisfy *all* criteria. Pure and unit-testable — the
API layer handles loading the universe.

A symbol that lacks a field a criterion references is excluded (we can't assert
a condition we can't evaluate), never silently passed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from pfip.diligence.peers import COMPARE_FIELDS

Op = Literal["gt", "gte", "lt", "lte", "eq"]

# Fields a screen may filter/return, with a human label and "better" direction.
FIELD_LABELS: dict[str, str] = {
    "pe_ratio": "P/E",
    "pb_ratio": "P/B",
    "roe": "ROE",
    "roce": "ROCE",
    "net_margin": "Net margin",
    "operating_margin": "Operating margin",
    "revenue_growth": "Revenue growth",
    "debt_to_equity": "Debt / equity",
    "dividend_yield": "Dividend yield",
}
ALLOWED_FIELDS = set(FIELD_LABELS)


class Criterion(BaseModel):
    field: str
    op: Op
    value: float


class ScreenMatch(BaseModel):
    symbol: str
    metrics: dict[str, float]


class ScreenResult(BaseModel):
    matches: list[ScreenMatch]
    n_universe: int
    n_evaluated: int  # symbols that had every filtered field
    fields_returned: list[str]
    disclaimer: str = (
        "Screen over stored fundamentals only — coverage varies by name and the "
        "latest available period. A research filter, not advice."
    )


def _passes(value: float, op: Op, threshold: float) -> bool:
    if op == "gt":
        return value > threshold
    if op == "gte":
        return value >= threshold
    if op == "lt":
        return value < threshold
    if op == "lte":
        return value <= threshold
    return value == threshold


def validate_criteria(criteria: list[Criterion]) -> list[str]:
    """Return a list of error strings (empty if all criteria are valid)."""
    errors: list[str] = []
    for c in criteria:
        if c.field not in ALLOWED_FIELDS:
            errors.append(f"Unknown field '{c.field}'.")
    return errors


def apply_screen(
    metrics_by_symbol: dict[str, dict[str, Any]],
    criteria: list[Criterion],
) -> ScreenResult:
    """Filter symbols by all criteria; return matches with their metrics."""
    filtered_fields = [c.field for c in criteria]
    # Union of filtered fields + all canonical fields we know, so the UI can show
    # context columns alongside the ones actually filtered on.
    return_fields = list(dict.fromkeys(filtered_fields + list(COMPARE_FIELDS)))

    matches: list[ScreenMatch] = []
    n_evaluated = 0
    for symbol, metrics in metrics_by_symbol.items():
        # Must have every filtered field to be evaluable.
        if any(metrics.get(c.field) is None for c in criteria):
            continue
        n_evaluated += 1
        if all(_passes(float(metrics[c.field]), c.op, c.value) for c in criteria):
            shown = {f: float(metrics[f]) for f in return_fields if metrics.get(f) is not None}
            matches.append(ScreenMatch(symbol=symbol, metrics=shown))

    # Sort by the first criterion's field in its "better" direction when known.
    if criteria:
        first = criteria[0].field
        better = COMPARE_FIELDS.get(first, "higher")
        matches.sort(
            key=lambda m: m.metrics.get(first, 0.0),
            reverse=(better == "higher"),
        )

    return ScreenResult(
        matches=matches,
        n_universe=len(metrics_by_symbol),
        n_evaluated=n_evaluated,
        fields_returned=return_fields,
    )
