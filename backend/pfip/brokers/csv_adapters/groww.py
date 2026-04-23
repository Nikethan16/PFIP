"""Groww CSV adapter (stocks + MFs).

Groww export columns (reports → P&L → download):
    Stocks: ``Stock Name, ISIN, Symbol, Buy/Sell, Quantity, Price, Date, Order ID, Amount``
    MFs: ``Scheme Name, Folio No, Order Status, Order Type, Units, NAV, Date, Amount``
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

SCHEMA_VERSION = "groww.v2025-01"
STOCK_COLS = {"symbol", "buy/sell", "quantity", "price", "date"}
MF_COLS = {"scheme name", "order type", "units", "nav", "date"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, STOCK_COLS) or detect_headers(sample_bytes, MF_COLS)


def _parse_stocks(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        sym = r.get(idx.get("symbol", ""), "")
        if not sym:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        kind = normalize_kind(r.get(idx.get("buy/sell", ""), "BUY"))
        amount = to_decimal(r.get(idx.get("amount", ""), ""))
        if amount == 0:
            amount = (qty * price).quantize(Decimal("0.01"))
        out.append(
            ParsedRow(
                broker="groww",
                symbol=f"{sym}.NS",
                isin=r.get(idx.get("isin", ""), "") or None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=amount,
                note=r.get(idx.get("order id", ""), ""),
                raw=r,
            )
        )
    return out


def _parse_mfs(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        scheme = r.get(idx.get("scheme name", ""), "")
        if not scheme:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        units = to_decimal(r.get(idx.get("units", ""), ""))
        nav = to_decimal(r.get(idx.get("nav", ""), ""))
        kind = normalize_kind(r.get(idx.get("order type", ""), ""))
        amount = to_decimal(r.get(idx.get("amount", ""), ""))
        if amount == 0 and units and nav:
            amount = (units * nav).quantize(Decimal("0.01"))
        out.append(
            ParsedRow(
                broker="groww",
                symbol=scheme,
                isin=None,
                time=dt,
                kind=kind,
                qty=units,
                price=nav,
                amount_inr=amount,
                note=f"Folio {r.get(idx.get('folio no', ''), '')}",
                raw=r,
            )
        )
    return out


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if detect_headers(csv_bytes, STOCK_COLS):
        return _parse_stocks(csv_bytes)
    if detect_headers(csv_bytes, MF_COLS):
        return _parse_mfs(csv_bytes)
    raise UnknownSchemaError(
        f"Groww CSV didn't match stock or MF schemas. Expected {STOCK_COLS} or {MF_COLS}."
    )
