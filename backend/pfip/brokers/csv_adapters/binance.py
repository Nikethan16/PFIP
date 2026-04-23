"""Binance CSV adapter (trade history + conversion).

Trade history (spot) columns:
    ``Date(UTC), Pair, Side, Price, Executed, Amount, Fee``

Conversion columns:
    ``Date, Wallet, Operation, Coin, Change, Remark``  (also 'Account' column)

Note: Binance doesn't provide INR rates on US residents' exports — we leave
``amount_inr`` as the quote value (usually USDT) and leave conversion to INR
to downstream tax engine using the RBI USD/INR rate at tx time. To keep the
contract numeric we store the raw quote as ``amount_inr`` temporarily and
flag cost_basis_ccy accordingly.
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

SCHEMA_VERSION = "binance.v2025-01"
TRADE_COLS = {"pair", "side", "price", "executed", "amount"}
# Binance sometimes exports with 'Date(UTC)' as the label.
DATE_ALIASES = ("date(utc)", "date", "utc time")
CONVERT_COLS = {"operation", "coin", "change"}


def _first_date_col(idx: dict[str, str]) -> str | None:
    for alias in DATE_ALIASES:
        if alias in idx:
            return idx[alias]
    return None


def detect(sample_bytes: bytes) -> bool:
    # Check trade via pair+side+amount; conversion via operation+coin+change.
    if detect_headers(sample_bytes, TRADE_COLS):
        return True
    if detect_headers(sample_bytes, CONVERT_COLS):
        return True
    return False


def _parse_trades(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    date_col = _first_date_col(idx)
    out: list[ParsedRow] = []
    for r in rows:
        pair = r.get(idx.get("pair", ""), "")
        if not pair:
            continue
        # e.g. "BTCUSDT" or "ETHBTC"; we pull the base conservatively.
        base = pair
        for quote in ("USDT", "BUSD", "USDC", "USD", "INR", "EUR", "BTC", "ETH"):
            if pair.endswith(quote) and len(pair) > len(quote):
                base = pair[: -len(quote)]
                break
        dt_raw = r.get(date_col, "") if date_col else ""
        dt = to_datetime(dt_raw).astimezone(timezone.utc)
        qty = to_decimal(r.get(idx.get("executed", ""), ""))
        price = to_decimal(r.get(idx.get("price", ""), ""))
        amount = to_decimal(r.get(idx.get("amount", ""), ""), default=qty * price)
        kind = normalize_kind(r.get(idx.get("side", ""), "BUY"))
        out.append(
            ParsedRow(
                broker="binance",
                symbol=base.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=price,
                amount_inr=amount.quantize(Decimal("0.01")),
                cost_basis_ccy="USD",  # Binance spot typically quotes USDT/USD
                note=f"Binance {pair}",
                raw=r,
            )
        )
    return out


def _parse_convert(csv_bytes: bytes) -> list[ParsedRow]:
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    date_col = _first_date_col(idx)
    out: list[ParsedRow] = []
    for r in rows:
        coin = r.get(idx.get("coin", ""), "")
        if not coin:
            continue
        dt_raw = r.get(date_col, "") if date_col else ""
        dt = to_datetime(dt_raw).astimezone(timezone.utc)
        change = to_decimal(r.get(idx.get("change", ""), ""))
        op = (r.get(idx.get("operation", ""), "") or "").lower()
        if "buy" in op:
            kind = "BUY"
        elif "sell" in op:
            kind = "SELL"
        elif "deposit" in op or "withdraw" in op:
            kind = "TRANSFER"
        elif "fee" in op:
            kind = "FEE"
        else:
            kind = "TRANSFER"
        out.append(
            ParsedRow(
                broker="binance",
                symbol=coin.upper(),
                isin=None,
                time=dt,
                kind=kind,
                qty=abs(change),
                price=None,
                amount_inr=Decimal("0"),
                cost_basis_ccy="USD",
                note=f"Binance convert {op}",
                raw=r,
            )
        )
    return out


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if detect_headers(csv_bytes, TRADE_COLS):
        return _parse_trades(csv_bytes)
    if detect_headers(csv_bytes, CONVERT_COLS):
        return _parse_convert(csv_bytes)
    raise UnknownSchemaError(
        f"Binance CSV didn't match trade or convert schemas. Expected {TRADE_COLS} or {CONVERT_COLS}."
    )
