"""Kraken ledger CSV adapter.

Ledger columns:
    ``txid, refid, time, type, subtype, aclass, asset, amount, fee, balance``

``type`` values: deposit, withdrawal, trade, margin, rollover, spend, receive, staking.
Pairs require matching across two rows with the same refid (one per leg),
but for tax purposes we emit each leg as its own ParsedRow and let the
downstream FIFO matcher reconstruct the trade.
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

SCHEMA_VERSION = "kraken.v2025-01"
REQUIRED = {"time", "type", "asset", "amount"}


_KRAKEN_ASSET_MAP = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "XXRP": "XRP",
    "XLTC": "LTC",
    "ZUSD": "USD",
    "ZEUR": "EUR",
    "ZGBP": "GBP",
    "ZJPY": "JPY",
}


def _map_asset(a: str) -> str:
    a = (a or "").upper()
    return _KRAKEN_ASSET_MAP.get(a, a)


def detect(sample_bytes: bytes) -> bool:
    return detect_headers(sample_bytes, REQUIRED)


def parse(csv_bytes: bytes) -> list[ParsedRow]:
    if not detect(csv_bytes):
        raise UnknownSchemaError(f"Kraken CSV missing columns; expected {REQUIRED}.")
    header, rows = read_rows(csv_bytes)
    idx = {h.lower(): h for h in header}
    out: list[ParsedRow] = []
    for r in rows:
        asset = _map_asset(r.get(idx.get("asset", ""), ""))
        if not asset:
            continue
        dt = to_datetime(r.get(idx.get("time", ""), "")).astimezone(timezone.utc)
        amount = to_decimal(r.get(idx.get("amount", ""), ""))
        fee = to_decimal(r.get(idx.get("fee", ""), ""))
        t = (r.get(idx.get("type", ""), "") or "").lower()
        if t == "trade":
            kind = "BUY" if amount > 0 else "SELL"
            qty = abs(amount)
        elif t in ("deposit", "withdrawal"):
            kind = "TRANSFER"
            qty = abs(amount)
        elif t in ("staking", "earn", "receive"):
            kind = "DIVIDEND"
            qty = abs(amount)
        elif t == "spend":
            kind = "SELL"
            qty = abs(amount)
        else:
            kind = "TRANSFER"
            qty = abs(amount)
        out.append(
            ParsedRow(
                broker="kraken",
                symbol=asset,
                isin=None,
                time=dt,
                kind=kind,
                qty=qty,
                price=None,
                amount_inr=Decimal("0"),  # Kraken ledger doesn't carry price directly
                cost_basis_ccy="USD" if asset in {"USD", "EUR", "GBP", "JPY"} else "USD",
                tax_withheld=fee.copy_abs(),
                note=f"Kraken {t} refid={r.get(idx.get('refid', ''), '')}",
                raw=r,
            )
        )
    return out
