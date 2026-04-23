"""Zerodha (Kite) CSV adapter.

Handles three export shapes:

1. **Trade history** (``Console → Reports → Tradebook``)
   Columns: ``Symbol, ISIN, Trade Date, Exchange, Segment, Series, Trade Type,
   Auction, Quantity, Price, Trade ID, Order ID, Order Execution Time``
2. **Ledger** (``Console → Funds → Ledger``)
   Columns: ``Particulars, Posting Date, Cost Center, Voucher Type,
   Debit, Credit, Net Balance``  (non-trade money flows)
3. **Mutual-fund report** (Coin)
   Columns: ``Folio, Scheme, Transaction Type, Amount, Units, NAV, Date``

The adapter detects which shape by header overlap, parses accordingly, and
emits ``ParsedRow`` records. Equity & F&O both route through the trade-history
path. For F&O we still record the BUY/SELL — P&L calculation in the tax
engine treats F&O lots the same as equity unless caller sets the asset_class.
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

SCHEMA_VERSION = "zerodha.v2025-01"

#: Required cols for each shape (lowercase for tolerant matching).
TRADEBOOK_COLS = {
    "symbol",
    "isin",
    "trade date",
    "quantity",
    "price",
    "trade type",
    "trade id",
}
LEDGER_COLS = {"particulars", "posting date", "debit", "credit"}
MF_COLS = {"folio", "scheme", "transaction type", "units", "nav", "date"}


def detect(sample_bytes: bytes) -> bool:
    return (
        detect_headers(sample_bytes, TRADEBOOK_COLS)
        or detect_headers(sample_bytes, LEDGER_COLS)
        or detect_headers(sample_bytes, MF_COLS)
    )


def _parse_tradebook(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    out: list[ParsedRow] = []
    # map lowercase → original header
    idx = {h.lower(): h for h in header}
    for r in rows:
        sym_raw = r.get(idx.get("symbol", ""), "")
        if not sym_raw:
            continue
        # Prefer Order Execution Time if present for intra-day precision.
        time_raw = r.get(idx.get("order execution time", ""), "") or r.get(
            idx.get("trade date", ""), ""
        )
        dt = to_datetime(time_raw).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        kind = normalize_kind(r.get(idx.get("trade type", ""), "BUY"))
        if kind == "SELL":
            qty = abs(qty)
        amount = (qty * price).quantize(Decimal("0.01"))
        exchange = r.get(idx.get("exchange", ""), "") or "NSE"
        segment = r.get(idx.get("segment", ""), "")
        symbol = f"{sym_raw}.{'BO' if exchange.upper() == 'BSE' else 'NS'}"
        out.append(
            ParsedRow(
                broker="zerodha",
                symbol=symbol,
                isin=r.get(idx.get("isin", ""), "") or None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=amount,
                note=f"{segment or exchange} trade {r.get(idx.get('trade id', ''), '')}".strip(),
                raw=r,
            )
        )
    return out


def _parse_ledger(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        part = r.get(idx.get("particulars", ""), "")
        if not part:
            continue
        dt = to_datetime(r.get(idx.get("posting date", ""), ""))
        debit = to_decimal(r.get(idx.get("debit", ""), ""))
        credit = to_decimal(r.get(idx.get("credit", ""), ""))
        amount = credit - debit
        kind = normalize_kind(part)
        if kind not in ("DIVIDEND", "INTEREST", "FEE", "TDS", "TRANSFER"):
            kind = "TRANSFER"
        out.append(
            ParsedRow(
                broker="zerodha",
                symbol="CASH",
                isin=None,
                time=dt,
                kind=kind,
                qty=None,
                price=None,
                amount_inr=amount.quantize(Decimal("0.01")),
                note=part,
                raw=r,
            )
        )
    return out


def _parse_mf(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        scheme = r.get(idx.get("scheme", ""), "")
        if not scheme:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), ""))
        units = to_decimal(r.get(idx.get("units", ""), ""))
        nav = to_decimal(r.get(idx.get("nav", ""), ""))
        kind = normalize_kind(r.get(idx.get("transaction type", ""), ""))
        if kind == "SELL":
            units = abs(units)
        amount = to_decimal(r.get(idx.get("amount", ""), ""))
        if amount == 0 and units and nav:
            amount = (units * nav).quantize(Decimal("0.01"))
        out.append(
            ParsedRow(
                broker="zerodha",
                symbol=scheme,
                isin=None,
                time=dt,
                kind=kind,
                qty=units,
                price=nav,
                amount_inr=amount,
                note=f"Folio {r.get(idx.get('folio', ''), '')}",
                raw=r,
            )
        )
    return out


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if detect_headers(csv_bytes, TRADEBOOK_COLS):
        return _parse_tradebook(csv_bytes)
    if detect_headers(csv_bytes, LEDGER_COLS):
        return _parse_ledger(csv_bytes)
    if detect_headers(csv_bytes, MF_COLS):
        return _parse_mf(csv_bytes)
    raise UnknownSchemaError(
        "Zerodha CSV didn't match Tradebook / Ledger / MF schemas. "
        f"Expected one of {TRADEBOOK_COLS} or {LEDGER_COLS} or {MF_COLS}."
    )
