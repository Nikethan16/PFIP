"""ICICI Direct trade history CSV adapter.

Typical columns (may vary by report):
    ``Stock Symbol, ISIN, Transaction Date, Action, Quantity, Price, Brokerage, Amount, Order No.``
"""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

from pfip.brokers.csv_adapters import ParsedRow, UnknownSchemaError
from pfip.brokers.csv_adapters._common import (
    detect_headers,
    normalize_kind,
    read_rows,
    to_datetime,
    to_decimal,
)

SCHEMA_VERSION = "icicidirect.v2025-01"
REQUIRED = {"stock symbol", "transaction date", "action", "quantity", "price"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, REQUIRED)


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if not detect(csv_bytes):
        raise UnknownSchemaError(f"ICICI Direct CSV missing columns; expected {REQUIRED}.")
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        sym = r.get(idx.get("stock symbol", ""), "")
        if not sym:
            continue
        dt = to_datetime(r.get(idx.get("transaction date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        kind = normalize_kind(r.get(idx.get("action", ""), "BUY"))
        brokerage = to_decimal(r.get(idx.get("brokerage", ""), ""))
        amount = to_decimal(r.get(idx.get("amount", ""), ""))
        if amount == 0:
            amount = (qty * price).quantize(Decimal("0.01"))
        if kind == "BUY":
            amount = amount + brokerage
        elif kind == "SELL":
            amount = amount - brokerage
        out.append(
            ParsedRow(
                broker="icicidirect",
                symbol=f"{sym}.NS",
                isin=r.get(idx.get("isin", ""), "") or None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=amount.quantize(Decimal("0.01")),
                note=f"ICICI order {r.get(idx.get('order no.', ''), '')}".strip(),
                raw=r,
            )
        )
    return out
