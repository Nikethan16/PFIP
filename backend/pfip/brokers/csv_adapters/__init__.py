"""Broker CSV adapters for portfolio + tax import.

Each adapter module exports:

    SCHEMA_VERSION: str  # pinned; bumped on any column change.
    REQUIRED_COLUMNS: set[str]
    def detect(sample_bytes: bytes) -> bool
    def parse(csv_bytes: bytes) -> list[ParsedRow]

``parse`` NEVER silently drops rows. Rows that fail validation are returned
under a ``rejected`` list via the ``parse_with_errors`` wrapper in
``router.py``. If the file's columns don't match any known schema,
``UnknownSchemaError`` is raised (the upload endpoint surfaces the broker's
expected columns to the user).

``ParsedRow`` is a superset of ``PortfolioTx`` with the owning symbol/ISIN
and broker tag attached so the router can pin them to a ``holding``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class UnknownSchemaError(Exception):
    """Raised when a CSV's header row doesn't match any known schema version."""


@dataclass(slots=True)
class ParsedRow:
    """A broker-CSV row normalised into a PortfolioTx-shaped record."""

    broker: str
    symbol: str
    isin: str | None
    time: datetime
    kind: str  # BUY / SELL / DIVIDEND / INTEREST / TRANSFER / FEE / TDS
    qty: Decimal | None
    price: Decimal | None
    amount_inr: Decimal
    fx_rate: Decimal | None = None
    tax_withheld: Decimal = Decimal("0")
    cost_basis_ccy: str = "INR"
    note: str | None = None
    raw: dict = field(default_factory=dict)


__all__ = ["ParsedRow", "UnknownSchemaError"]
