"""Fundamental feature derivation from the ``fundamentals`` table.

Computes the canonical equity-style ratios used downstream by the signal layer
and the agent's morning brief: P/E, P/B, debt/equity, ROE, ROCE. All queries
are point-in-time: a feature row dated ``as_of_t`` may only reference
fundamental rows with ``as_of_date <= as_of_t``.

Designed to degrade gracefully: missing fields produce ``None`` (rather than
raising) so the surrounding feature runner can carry on with technicals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping

import pandas as pd

log = logging.getLogger(__name__)


# Canonical fundamental fields we look for in the ``fundamentals.field`` column.
# Source pipelines (yfinance, jugaad, sec_edgar) normalise to these keys.
FIELD_PE = "pe_ratio"
FIELD_PB = "pb_ratio"
FIELD_DEBT_EQUITY = "debt_to_equity"
FIELD_ROE = "roe"
FIELD_ROCE = "roce"
FIELD_EARNINGS = "eps_ttm"
FIELD_BOOK_VALUE = "book_value_per_share"
FIELD_TOTAL_DEBT = "total_debt"
FIELD_TOTAL_EQUITY = "total_equity"
FIELD_NET_INCOME = "net_income"
FIELD_EBIT = "ebit"
FIELD_CAPITAL_EMPLOYED = "capital_employed"


FUNDAMENTAL_FEATURE_COLS: tuple[str, ...] = (
    "pe_ratio",
    "pb_ratio",
    "debt_to_equity",
    "roe",
    "roce",
)


@dataclass(frozen=True)
class FundamentalSnapshot:
    """The PIT snapshot of one symbol's fundamentals at a moment in time."""

    symbol: str
    as_of: date
    pe_ratio: float | None
    pb_ratio: float | None
    debt_to_equity: float | None
    roe: float | None
    roce: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
            "debt_to_equity": self.debt_to_equity,
            "roe": self.roe,
            "roce": self.roce,
        }


def _as_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


def derive_from_rows(
    rows: Iterable[Mapping[str, object]],
    symbol: str,
    as_of: date,
) -> FundamentalSnapshot:
    """Collapse fundamental rows into a single PIT snapshot.

    ``rows`` must be an iterable of mappings with keys ``field`` and ``value``
    (matching ``FundamentalRow`` columns). The latest value per field that
    satisfies ``as_of_date <= as_of`` wins; callers are responsible for that
    filter.
    """
    by_field: dict[str, float | None] = {}
    for r in rows:
        f = str(r.get("field"))
        v = _as_float(r.get("value"))  # type: ignore[arg-type]
        # Keep the latest non-null per field.
        if v is not None or f not in by_field:
            by_field[f] = v

    pe = by_field.get(FIELD_PE)
    pb = by_field.get(FIELD_PB)
    de = by_field.get(FIELD_DEBT_EQUITY)
    roe = by_field.get(FIELD_ROE)
    roce = by_field.get(FIELD_ROCE)

    # Derive missing ratios from raw inputs when present.
    if pe is None and (eps := by_field.get(FIELD_EARNINGS)) and (price := by_field.get("price")):
        try:
            pe = float(price) / float(eps) if eps else None
        except Exception:
            pe = None
    if pb is None and (book := by_field.get(FIELD_BOOK_VALUE)) and (price := by_field.get("price")):
        try:
            pb = float(price) / float(book) if book else None
        except Exception:
            pb = None
    if de is None:
        td = by_field.get(FIELD_TOTAL_DEBT)
        te = by_field.get(FIELD_TOTAL_EQUITY)
        if td is not None and te:
            de = float(td) / float(te)
    if roe is None:
        ni = by_field.get(FIELD_NET_INCOME)
        te = by_field.get(FIELD_TOTAL_EQUITY)
        if ni is not None and te:
            roe = float(ni) / float(te)
    if roce is None:
        ebit = by_field.get(FIELD_EBIT)
        ce = by_field.get(FIELD_CAPITAL_EMPLOYED)
        if ebit is not None and ce:
            roce = float(ebit) / float(ce)

    return FundamentalSnapshot(
        symbol=symbol,
        as_of=as_of,
        pe_ratio=pe,
        pb_ratio=pb,
        debt_to_equity=de,
        roe=roe,
        roce=roce,
    )


def empty_snapshot(symbol: str, as_of: date) -> FundamentalSnapshot:
    """A snapshot with everything None — used when no fundamentals exist."""
    return FundamentalSnapshot(
        symbol=symbol,
        as_of=as_of,
        pe_ratio=None,
        pb_ratio=None,
        debt_to_equity=None,
        roe=None,
        roce=None,
    )


async def load_pit_fundamentals(session, symbol: str, as_of: date) -> FundamentalSnapshot:
    """Load the most recent PIT fundamentals row per field for ``symbol``.

    Read-only. Tolerates missing table or zero rows by returning ``empty_snapshot``.
    """
    try:
        from sqlalchemy import and_, select  # local import to keep module light

        from pfip.models.fundamentals import FundamentalRow
    except Exception:  # pragma: no cover
        return empty_snapshot(symbol, as_of)

    try:
        stmt = (
            select(FundamentalRow)
            .where(
                and_(
                    FundamentalRow.symbol == symbol,
                    FundamentalRow.as_of_date <= as_of,
                )
            )
            .order_by(FundamentalRow.as_of_date.asc())
        )
        res = await session.execute(stmt)
        rows = [{"field": r.field, "value": r.value} for r in res.scalars().all()]
    except Exception as exc:  # pragma: no cover
        log.warning("load_pit_fundamentals failed for %s: %s", symbol, exc)
        return empty_snapshot(symbol, as_of)

    if not rows:
        return empty_snapshot(symbol, as_of)
    return derive_from_rows(rows, symbol=symbol, as_of=as_of)
