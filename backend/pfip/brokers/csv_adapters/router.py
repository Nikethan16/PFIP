"""CSV upload router.

Responsibility:
    1. Given an uploaded file + optional ``broker`` hint, pick the right adapter.
    2. Auto-detect if no hint is given by calling each adapter's ``detect``.
    3. Parse into ``ParsedRow`` list; surface per-row errors.
    4. Never silently drop a row: failures appear under ``rejected``.

Also exports ``ADAPTERS`` — the broker → module map — so callers can
introspect supported brokers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import ModuleType
from typing import Callable

from pfip.brokers.csv_adapters import ParsedRow, UnknownSchemaError
from pfip.brokers.csv_adapters import (
    binance,
    coinbase,
    coindcx,
    groww,
    icicidirect,
    indmoney,
    kraken,
    vested,
    wazirx,
    zerodha,
)


# Broker ID → adapter module
ADAPTERS: dict[str, ModuleType] = {
    "zerodha": zerodha,
    "icicidirect": icicidirect,
    "groww": groww,
    "indmoney": indmoney,
    "vested": vested,
    "wazirx": wazirx,
    "coindcx": coindcx,
    "binance": binance,
    "coinbase": coinbase,
    "kraken": kraken,
}


@dataclass(slots=True)
class ImportResult:
    """Aggregate outcome of a CSV import."""

    broker: str
    schema_version: str
    imported: list[ParsedRow] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "broker": self.broker,
            "schema_version": self.schema_version,
            "imported": len(self.imported),
            "rejected": len(self.rejected),
            "rows": [
                {
                    "symbol": r.symbol,
                    "time": r.time.isoformat(),
                    "kind": r.kind,
                    "qty": str(r.qty) if r.qty is not None else None,
                    "amount_inr": str(r.amount_inr),
                    "cost_basis_ccy": r.cost_basis_ccy,
                }
                for r in self.imported
            ],
            "errors": self.rejected,
        }


def autodetect(sample_bytes: bytes) -> str | None:
    """Return the broker ID whose ``detect`` matches ``sample_bytes`` first."""
    for name, mod in ADAPTERS.items():
        try:
            if mod.detect(sample_bytes):  # type: ignore[attr-defined]
                return name
        except Exception:  # noqa: BLE001 — detection must be defensive
            continue
    return None


def list_supported() -> list[dict]:
    """For use by ``GET /portfolio/import/supported``."""
    return [
        {
            "broker": name,
            "schema_version": getattr(mod, "SCHEMA_VERSION", "unknown"),
        }
        for name, mod in ADAPTERS.items()
    ]


def route_and_parse(csv_bytes: bytes, broker: str | None = None) -> ImportResult:
    """Parse ``csv_bytes`` with the adapter matching ``broker`` (or auto-detect).

    Raises:
        UnknownSchemaError: if no adapter matches.
    """
    key = (broker or "").strip().lower() or autodetect(csv_bytes)
    if key is None or key not in ADAPTERS:
        supported = ", ".join(sorted(ADAPTERS))
        raise UnknownSchemaError(
            f"Could not auto-detect broker. Supply one of: {supported}. "
            "If the file is from a supported broker, the headers may have changed."
        )
    mod = ADAPTERS[key]
    try:
        rows = mod.parse(csv_bytes)  # type: ignore[attr-defined]
    except UnknownSchemaError:
        raise
    result = ImportResult(
        broker=key,
        schema_version=getattr(mod, "SCHEMA_VERSION", "unknown"),
    )
    # post-filter obviously invalid rows (qty=0 and amount=0 ⇒ noise line)
    for row in rows:
        try:
            if (
                (row.qty in (None,) or row.qty == 0)
                and row.amount_inr == 0
                and row.kind not in {"TRANSFER", "FEE"}
            ):
                result.rejected.append({"row": row.raw, "reason": "empty qty and amount"})
                continue
            result.imported.append(row)
        except Exception as exc:  # noqa: BLE001
            result.rejected.append({"row": getattr(row, "raw", {}), "reason": str(exc)})
    return result


# ---------------------------------------------------------------------------
# Tax-focused parse: same routing but annotates each row with asset_class hint
# ---------------------------------------------------------------------------


_VDA_BROKERS = {"wazirx", "coindcx", "binance", "coinbase", "kraken"}
_US_BROKERS = {"indmoney", "vested"}


def tax_focused_parse(csv_bytes: bytes, broker: str | None = None) -> ImportResult:
    """Same as ``route_and_parse`` but tags asset_class for the tax engine.

    Sets ``note`` suffix ``asset_class=...`` that downstream tax code reads.
    """
    result = route_and_parse(csv_bytes, broker)
    for r in result.imported:
        if result.broker in _VDA_BROKERS:
            r.note = (r.note or "") + " [asset_class=vda]"
        elif result.broker in _US_BROKERS:
            r.note = (r.note or "") + " [asset_class=us_stock]"
        else:
            r.note = (r.note or "") + " [asset_class=equity]"
    return result
