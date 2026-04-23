"""CoinDCX CSV adapter (trade history + wallet flows).

Trade history columns:
    ``Date, Market, Side, Price, Quantity, Fee, Total, Order Type``
Wallet flow columns:
    ``Date, Coin, Amount, Type, Status, Address/Txn``
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

SCHEMA_VERSION = "coindcx.v2025-01"
TRADE_COLS = {"date", "market", "side", "price", "quantity", "total"}
WALLET_COLS = {"date", "coin", "amount", "type"}


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, TRADE_COLS) or detect_headers(
        sample_bytes, WALLET_COLS
    )


def _parse_trades(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        market = r.get(idx.get("market", ""), "")
        if not market:
            continue
        base = market.replace("INR", "").replace("USDT", "").replace("/", "").replace("_", "")
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("quantity", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        total = to_decimal(r.get(idx.get("total", ""), ""), default=qty * price)
        kind = normalize_kind(r.get(idx.get("side", ""), "BUY"))
        tds = (total * Decimal("0.01")).quantize(Decimal("0.01")) if kind == "SELL" else Decimal("0")
        out.append(
            ParsedRow(
                broker="coindcx",
                symbol=base.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=total.quantize(Decimal("0.01")),
                tax_withheld=tds,
                note=f"CoinDCX {market}",
                raw=r,
            )
        )
    return out


def _parse_wallet(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        coin = r.get(idx.get("coin", ""), "")
        if not coin:
            continue
        dt = to_datetime(r.get(idx.get("date", ""), "")).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("amount", ""), ""))
        out.append(
            ParsedRow(
                broker="coindcx",
                symbol=coin.upper(),
                isin=None,
                time=dt,
                kind="TRANSFER",
                qty=qty,
                price=None,
                amount_inr=Decimal("0"),
                note=f"{r.get(idx.get('type', ''), '')} {r.get(idx.get('address/txn', ''), '')}".strip(),
                raw=r,
            )
        )
    return out


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if detect_headers(csv_bytes, TRADE_COLS):
        return _parse_trades(csv_bytes)
    if detect_headers(csv_bytes, WALLET_COLS):
        return _parse_wallet(csv_bytes)
    raise UnknownSchemaError(
        f"CoinDCX CSV didn't match trade or wallet schemas. Expected {TRADE_COLS} or {WALLET_COLS}."
    )
