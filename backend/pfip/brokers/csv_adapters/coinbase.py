"""Coinbase transaction export CSV adapter.

Coinbase's export has:

    ``Timestamp, Transaction Type, Asset, Quantity Transacted, Spot Price Currency,
    Spot Price at Transaction, Subtotal, Total (inclusive of fees and/or spread),
    Fees and/or Spread, Notes``

Transaction Type values: Buy / Sell / Send / Receive / Convert / Staking Income / Coinbase Earn etc.
"""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

from pfip.brokers.csv_adapters import ParsedRow, UnknownSchemaError
from pfip.brokers.csv_adapters._common import (
    detect_headers,
    read_rows,
    to_datetime,
    to_decimal,
)

SCHEMA_VERSION = "coinbase.v2025-01"
REQUIRED = {"timestamp", "transaction type", "asset", "quantity transacted"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, REQUIRED)


_BUY_TYPES = {"BUY", "CONVERT", "RECEIVE", "COINBASE EARN", "STAKING INCOME", "REWARD", "ADVANCE TRADE BUY"}
_SELL_TYPES = {"SELL", "SEND", "ADVANCE TRADE SELL"}


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if not detect(csv_bytes):
        raise UnknownSchemaError(f"Coinbase CSV missing columns; expected {REQUIRED}.")
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        asset = r.get(idx.get("asset", ""), "")
        if not asset:
            continue
        dt = to_datetime(r.get(idx.get("timestamp", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity transacted", ""), ""))
        price = to_decimal(r.get(idx.get("spot price at transaction", ""), ""))
        subtotal = to_decimal(r.get(idx.get("subtotal", ""), ""), default=qty * price)
        total = to_decimal(
            r.get(idx.get("total (inclusive of fees and/or spread)", ""), ""),
            default=subtotal,
        )
        ttype_raw = (r.get(idx.get("transaction type", ""), "") or "").upper()
        if ttype_raw in _BUY_TYPES:
            kind = "BUY"
        elif ttype_raw in _SELL_TYPES:
            kind = "SELL"
        elif "DIVIDEND" in ttype_raw or "INTEREST" in ttype_raw:
            kind = "DIVIDEND"
        else:
            kind = "TRANSFER"
        ccy = r.get(idx.get("spot price currency", ""), "USD") or "USD"
        out.append(
            ParsedRow(
                broker="coinbase",
                symbol=asset.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=total.quantize(Decimal("0.01")),
                cost_basis_ccy=ccy.upper(),
                note=f"Coinbase {ttype_raw}",
                raw=r,
            )
        )
    return out
