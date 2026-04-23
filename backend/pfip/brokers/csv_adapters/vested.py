"""Vested (US stocks) CSV adapter.

Typical columns:
    ``Ticker, Name, Transaction Type, Quantity, Unit Price (USD), Total (USD),
    Exchange Rate, Total (INR), Date, Order ID``
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

SCHEMA_VERSION = "vested.v2025-01"
REQUIRED = {"ticker", "transaction type", "quantity", "unit price (usd)", "date"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, REQUIRED)


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if not detect(csv_bytes):
        raise UnknownSchemaError(f"Vested CSV missing columns; expected {REQUIRED}.")
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        tkr = r.get(idx.get("ticker", ""), "")
        if not tkr:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price_usd = to_decimal(r.get(idx.get("unit price (usd)", ""), ""))
        fx = to_decimal(r.get(idx.get("exchange rate", ""), ""))
        total_usd = to_decimal(r.get(idx.get("total (usd)", ""), ""), default=qty * price_usd)
        total_inr = to_decimal(
            r.get(idx.get("total (inr)", ""), ""),
            default=(total_usd * fx).quantize(Decimal("0.01")),
        )
        kind = normalize_kind(r.get(idx.get("transaction type", ""), "BUY"))
        out.append(
            ParsedRow(
                broker="vested",
                symbol=tkr.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price_usd,
                amount_inr=total_inr,
                fx_rate=fx,
                cost_basis_ccy="USD",
                note=r.get(idx.get("order id", ""), "") or "Vested US equities",
                raw=r,
            )
        )
    return out
