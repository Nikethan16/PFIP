"""FX-aware cost basis helpers.

Primary source: RBI reference rates (ingested into ``ohlcv`` under the
``rbi`` source). Fallback: Frankfurter open API (cached daily; free).

Only USD/INR and a handful of G10 pairs are supported. All dates are the
*transaction* date; for weekend/holiday tx we step back to the last available
business-day rate ("RBI rule for non-business days").
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

try:  # httpx is a dependency; import lazily so tests don't require network
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# Fallback static table for tests and when no DB session is provided.
# Values here are illustrative — production overrides come from ``ohlcv`` table
# (source='rbi') or Frankfurter.
_STATIC_FALLBACK_USDINR: dict[date, Decimal] = {
    date(2023, 4, 3): Decimal("82.1950"),
    date(2024, 4, 1): Decimal("83.3825"),
    date(2024, 12, 31): Decimal("85.6200"),
    date(2025, 4, 1): Decimal("85.0150"),
    date(2025, 12, 31): Decimal("84.7800"),
    date(2026, 1, 2): Decimal("84.2000"),
    date(2026, 3, 31): Decimal("84.9100"),
}


class FxRateNotFoundError(LookupError):
    """Raised when no FX rate can be sourced for a given (currency, date)."""


def _frankfurter_fetch(currency: str, on: date) -> Decimal | None:
    """Fetch ``currency``/INR on ``on`` from Frankfurter. Returns None on failure."""
    if httpx is None:  # pragma: no cover — httpx always installed in prod
        return None
    try:
        url = f"https://api.frankfurter.app/{on.isoformat()}"
        r = httpx.get(url, params={"from": currency, "to": "INR"}, timeout=5.0)
        if r.status_code != 200:
            return None
        data = r.json()
        rate = data.get("rates", {}).get("INR")
        if rate is None:
            return None
        return Decimal(str(rate))
    except Exception:  # noqa: BLE001 — any network error is a miss
        return None


def _db_fetch(currency: str, on: date, db: Any | None) -> Decimal | None:
    """Best-effort DB lookup of RBI-ingested rate. Returns None if unavailable.

    We support a sync session with ``.execute`` returning a rowset whose
    ``.close`` is a ``Decimal``. Kept extremely defensive so tests work with the
    fake session from ``conftest.py``.
    """
    if db is None:
        return None
    try:
        from sqlalchemy import text  # local import to avoid hard dep in tests

        symbol = f"{currency.upper()}INR"
        sql = text(
            "SELECT close FROM ohlcv "
            "WHERE symbol = :sym AND source = 'rbi' AND time::date <= :on "
            "ORDER BY time DESC LIMIT 1"
        )
        result = db.execute(sql, {"sym": symbol, "on": on})
        row = result.first() if hasattr(result, "first") else None
        if row is None:
            return None
        return Decimal(str(row[0]))
    except Exception:  # noqa: BLE001
        return None


def get_fx_rate(
    currency: str,
    on: date,
    *,
    db: Any | None = None,
    fallback: bool = True,
) -> Decimal:
    """Return ``currency`` → INR rate for ``on``.

    Order of resolution:
        1. DB ``ohlcv`` where ``source='rbi'`` and symbol matches (e.g. ``USDINR``).
        2. Frankfurter fallback (if ``fallback=True``).
        3. Static in-memory table (dev/test).
        4. Step back up to 7 days to find a business-day rate.

    Raises:
        FxRateNotFoundError: if no rate can be resolved within the back-off window.
    """
    if currency.upper() == "INR":
        return Decimal("1")

    # 1. DB
    for offset in range(0, 8):  # today + up to 7 days back
        d = on - timedelta(days=offset)
        rate = _db_fetch(currency, d, db)
        if rate is not None:
            return rate

    # 2. Frankfurter
    if fallback:
        for offset in range(0, 8):
            d = on - timedelta(days=offset)
            rate = _frankfurter_fetch(currency, d)
            if rate is not None:
                return rate

    # 3. Static fallback (USD only)
    if currency.upper() == "USD":
        # find nearest date
        for offset in range(0, 365):
            d = on - timedelta(days=offset)
            if d in _STATIC_FALLBACK_USDINR:
                return _STATIC_FALLBACK_USDINR[d]

    raise FxRateNotFoundError(
        f"No FX rate for {currency}/INR on {on.isoformat()} (DB + Frankfurter + static all miss)"
    )


def convert_to_inr(
    amount: Decimal,
    currency: str,
    on: date,
    *,
    db: Any | None = None,
) -> Decimal:
    """Convert ``amount`` in ``currency`` to INR using ``on``-date FX rate."""
    rate = get_fx_rate(currency, on, db=db)
    return (amount * rate).quantize(Decimal("0.01"))


def rbi_peak_balance_usd_inr(
    daily_balances_usd: dict[date, Decimal],
    *,
    db: Any | None = None,
) -> tuple[Decimal, Decimal, date]:
    """Peak USD balance during a period + its INR-converted value + date.

    Used by Schedule FA. Returns ``(peak_usd, peak_usd_in_inr, peak_date)``.
    """
    if not daily_balances_usd:
        return (Decimal("0"), Decimal("0"), date.min)
    peak_date = max(daily_balances_usd, key=lambda d: daily_balances_usd[d])
    peak_usd = daily_balances_usd[peak_date]
    peak_inr = convert_to_inr(peak_usd, "USD", peak_date, db=db)
    return (peak_usd, peak_inr, peak_date)
