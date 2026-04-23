"""WazirX CSV adapter.

Two known export shapes:

1. **Trade history** (``Reports → Trade History``):
   ``Date, Market, Price, Volume, Total, Trade, Fee, Fee Coin``

2. **Deposit / withdrawal** (``Reports → Funds``):
   ``Date, Currency, Volume, Type, Status``  (Type = Deposit/Withdrawal)

Detection picks the right path. Symbol in trade history is stored as the
base asset (e.g. ``BTC`` from ``BTC/INR``) so VDA classifier recognises it.
All amounts in INR (WazirX uses the quote currency of the pair).
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

SCHEMA_VERSION = "wazirx.v2025-01"
TRADE_COLS = {"date", "market", "price", "volume", "total", "trade"}
FUND_COLS = {"date", "currency", "volume", "type"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, TRADE_COLS) or detect_headers(sample_bytes, FUND_COLS)


def _parse_trades(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        market = r.get(idx.get("market", ""), "")
        if not market:
            continue
        base = market.split("/")[0] if "/" in market else market.split("-")[0]
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("volume", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        total = to_decimal(
            r.get(idx.get("total", ""), ""),
            default=(qty * price).quantize(Decimal("0.01")),
        )
        fee = to_decimal(r.get(idx.get("fee", ""), ""))
        kind = normalize_kind(r.get(idx.get("trade", ""), "BUY"))
        # 1% TDS on every transaction on or after 2022-07-01.
        tds = Decimal("0")
        if kind == "SELL":
            tds = (total * Decimal("0.01")).quantize(Decimal("0.01"))
        out.append(
            ParsedRow(
                broker="wazirx",
                symbol=base.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=total.quantize(Decimal("0.01")),
                tax_withheld=tds,
                note=f"WazirX {market} | fee={fee}",
                raw=r,
            )
        )
    return out


def _parse_funds(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        ccy = r.get(idx.get("currency", ""), "")
        if not ccy:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("volume", ""), ""))
        type_raw = r.get(idx.get("type", ""), "")
        kind = "TRANSFER"
        note = f"WazirX {type_raw} {ccy}"
        out.append(
            ParsedRow(
                broker="wazirx",
                symbol=ccy.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=None,
                amount_inr=Decimal("0"),  # unknown INR value for a coin flow
                note=note,
                raw=r,
            )
        )
    return out


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if detect_headers(csv_bytes, TRADE_COLS):
        return _parse_trades(csv_bytes)
    if detect_headers(csv_bytes, FUND_COLS):
        return _parse_funds(csv_bytes)
    raise UnknownSchemaError(
        f"WazirX CSV didn't match trade or funds schemas. Expected {TRADE_COLS} or {FUND_COLS}."
    )
