"""Shared helpers for CSV adapters — CSV parsing, date coercion, money coercion."""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterator


def decode_csv(csv_bytes: bytes) -> str:
    """Decode bytes as UTF-8-with-BOM first, fall back to latin-1."""
    try:
        return csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return csv_bytes.decode("latin-1", errors="replace")


def read_rows(csv_bytes: bytes) -> tuple[list[str], Iterator[dict[str, str]]]:
    """Return ``(headers, dict-reader-iterator)``. Trims whitespace on every cell."""
    text = decode_csv(csv_bytes).lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None) or []
    header = [h.strip() for h in header]

    def _rows() -> Iterator[dict[str, str]]:
        for row in reader:
            padded = row + [""] * (len(header) - len(row))
            yield {h: (padded[i].strip() if i < len(padded) else "") for i, h in enumerate(header)}

    return header, _rows()


def detect_headers(sample_bytes: bytes, expected: set[str]) -> bool:
    """Return True if every header in ``expected`` appears in the CSV sample."""
    try:
        header, _ = read_rows(sample_bytes)
    except Exception:  # noqa: BLE001
        return False
    lower = {h.lower() for h in header}
    return {e.lower() for e in expected}.issubset(lower)


_DECIMAL_CLEAN = re.compile(r"[,₹$£€\s]")


def to_decimal(raw: str | None, *, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a messy money string to Decimal. Empty → default."""
    if raw is None or raw == "" or raw.lower() in ("none", "null", "nan", "-"):
        return default
    cleaned = _DECIMAL_CLEAN.sub("", str(raw))
    # handle accounting negatives like (123.45)
    neg = cleaned.startswith("(") and cleaned.endswith(")")
    if neg:
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Could not parse decimal: {raw!r}") from exc


_DATE_PATTERNS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%b %d, %Y",
    "%d %b %Y",
    "%d-%b-%Y",
)


def to_datetime(raw: str | None) -> datetime:
    """Parse a messy date string to a timezone-aware datetime (UTC fallback)."""
    if not raw:
        raise ValueError("empty date")
    s = raw.strip()
    # Try ISO 8601 first
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        pass
    for pat in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(s, pat)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {raw!r}")


def to_date(raw: str | None) -> date:
    """Parse to date (ignores time)."""
    return to_datetime(raw).date()


def normalize_kind(raw: str) -> str:
    """Map various broker labels to PortfolioTxKind string values."""
    r = (raw or "").upper().strip()
    if r in ("BUY", "B", "PURCHASE", "ADD"):
        return "BUY"
    if r in ("SELL", "S", "SALE", "DISPOSE", "REDEMPTION"):
        return "SELL"
    if "DIV" in r:
        return "DIVIDEND"
    if "INTEREST" in r or r == "INT":
        return "INTEREST"
    if "TDS" in r or "WITHHOLD" in r:
        return "TDS"
    if "FEE" in r or "COMMISSION" in r or "BROKERAGE" in r:
        return "FEE"
    if "TRANSFER" in r or "DEPOSIT" in r or "WITHDRAW" in r:
        return "TRANSFER"
    return r or "BUY"
