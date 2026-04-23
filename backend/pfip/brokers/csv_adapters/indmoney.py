"""INDmoney (US stocks) CSV adapter.

Columns include both USD and INR legs + the FX rate used at execution:

    ``Symbol, ISIN, Trade Date, Side, Quantity, Price (USD), Amount (USD),
    FX Rate, Amount (INR), Fees (USD)``

The adapter sets ``cost_basis_ccy='USD'`` and stores the per-trade ``fx_rate``.
This powers Schedule FA peak-balance and Form 67 DTAA credit downstream.
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

SCHEMA_VERSION = "indmoney.v2025-01"
REQUIRED = {"symbol", "trade date", "side", "quantity", "price (usd)", "fx rate"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, REQUIRED)


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if not detect(csv_bytes):
        raise UnknownSchemaError(f"INDmoney CSV missing columns; expected {REQUIRED}.")
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        sym = r.get(idx.get("symbol", ""), "")
        if not sym:
            continue
        dt = to_datetime(r.get(idx.get("trade date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price_usd = to_decimal(r.get(idx.get("price (usd)", ""), ""))
        fx = to_decimal(r.get(idx.get("fx rate", ""), ""))
        amount_usd = to_decimal(
            r.get(idx.get("amount (usd)", ""), ""),
            default=(qty * price_usd),
        )
        amount_inr = to_decimal(
            r.get(idx.get("amount (inr)", ""), ""),
            default=(amount_usd * fx).quantize(Decimal("0.01")),
        )
        kind = normalize_kind(r.get(idx.get("side", ""), "BUY"))
        out.append(
            ParsedRow(
                broker="indmoney",
                symbol=sym.upper(),
                isin=r.get(idx.get("isin", ""), "") or None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price_usd,
                amount_inr=amount_inr,
                fx_rate=fx,
                cost_basis_ccy="USD",
                note="INDmoney US equities",
                raw=r,
            )
        )
    return out
