"""FX-aware cost basis helpers.

Primary source: the dedicated ``fx_rates`` table (one row per
``(rate_date, base, quote, source)``, created in migration 0006). Fallback:
Frankfurter open API (cached daily; free). Last resort: a small static table.

Only USD/INR and a handful of G10 pairs are supported. All dates are the
*transaction* date; for weekend/holiday tx we step back to the last available
business-day rate ("RBI rule for non-business days").

Async note
----------
The tax engine math is synchronous but is driven from async FastAPI handlers
that hold an ``AsyncSession``. A synchronous ``session.execute`` on an
``AsyncSession`` cannot be awaited and silently fails. To keep the math sync
while still reading the DB, callers in ``pfip.api.tax`` pre-fetch the needed
rates via :func:`prefetch_fx_rates` (async) and pass the resulting mapping in
as ``rate_cache=``. Sync callers (CLI/tests) may still pass a plain sync
``db=`` session, which is queried directly.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from loguru import logger

try:  # httpx is a dependency; import lazily so tests don't require network
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# Mapping shape passed by async callers: {(CURRENCY_UPPER, date): rate}.
RateCache = dict[tuple[str, date], Decimal]

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
    """Fetch ``currency``/INR on ``on`` from Frankfurter. Returns None on failure.

    NOTE: this is a *blocking* call and must not be hit from inside an async
    request handler. Async callers pre-populate ``rate_cache`` (see
    :func:`prefetch_fx_rates`) so this path is only exercised by sync callers
    (CLI/tests) or as a genuine last resort.
    """
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


def _is_async_session(db: Any) -> bool:
    """True if ``db`` is a SQLAlchemy AsyncSession (cannot be used sync)."""
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        return isinstance(db, AsyncSession)
    except Exception:  # pragma: no cover
        return False


def _db_fetch(currency: str, on: date, db: Any | None) -> Decimal | None:
    """Best-effort *synchronous* DB lookup of the FX rate from ``fx_rates``.

    Returns None if unavailable. This path is only valid for a *sync* session;
    an ``AsyncSession`` is skipped here (its ``.execute`` returns a coroutine
    that cannot be awaited from sync code — that was the silent-failure bug).
    Async callers must pre-fetch via :func:`prefetch_fx_rates` instead.
    """
    if db is None or _is_async_session(db):
        return None
    try:
        from sqlalchemy import text  # local import to avoid hard dep in tests

        base = currency.upper()
        sql = text(
            "SELECT rate FROM fx_rates "
            "WHERE base = :base AND quote = 'INR' AND rate_date <= :on "
            "ORDER BY rate_date DESC LIMIT 1"
        )
        result = db.execute(sql, {"base": base, "on": on})
        row = result.first() if hasattr(result, "first") else None
        if row is None:
            return None
        return Decimal(str(row[0]))
    except Exception:  # noqa: BLE001
        return None


async def prefetch_fx_rates(
    db: Any,
    needs: list[tuple[str, date]],
) -> RateCache:
    """Async-fetch the latest ``base``→INR rate on/at-or-before each requested
    date from the ``fx_rates`` table.

    ``needs`` is a list of ``(currency, on)`` pairs (currency case-insensitive).
    Returns a mapping ``{(CURRENCY_UPPER, on): Decimal}`` for the pairs we could
    resolve. Missing pairs simply aren't in the map; the sync resolver then
    falls back to Frankfurter/static as before.

    Designed for ``AsyncSession`` callers in ``pfip.api.tax`` so the blocking
    DB/HTTP paths never run inside the event loop.
    """
    cache: RateCache = {}
    if db is None:
        return cache
    from sqlalchemy import text  # local import

    sql = text(
        "SELECT rate FROM fx_rates "
        "WHERE base = :base AND quote = 'INR' AND rate_date <= :on "
        "ORDER BY rate_date DESC LIMIT 1"
    )
    for currency, on in needs:
        base = currency.upper()
        if base == "INR" or (base, on) in cache:
            continue
        try:
            result = await db.execute(sql, {"base": base, "on": on})
            row = result.first() if hasattr(result, "first") else None
        except Exception as exc:  # noqa: BLE001 — table may be missing on old DB
            logger.warning(f"prefetch_fx_rates({base},{on}) failed: {exc}")
            continue
        if row is not None:
            cache[(base, on)] = Decimal(str(row[0]))
    return cache


def get_fx_rate(
    currency: str,
    on: date,
    *,
    db: Any | None = None,
    fallback: bool = True,
    rate_cache: RateCache | None = None,
) -> Decimal:
    """Return ``currency`` → INR rate for ``on``.

    Order of resolution:
        1. ``rate_cache`` (pre-fetched from ``fx_rates`` by an async caller).
        2. Sync DB ``fx_rates`` lookup (sync sessions only).
        3. Frankfurter fallback (if ``fallback=True``).
        4. Static in-memory table (dev/test) — logs a clear warning.
        5. Step back up to 7 days to find a business-day rate.

    Raises:
        FxRateNotFoundError: if no rate can be resolved within the back-off window.
    """
    if currency.upper() == "INR":
        return Decimal("1")

    base = currency.upper()

    # 1. Pre-fetched cache + 2. sync DB (both stepped back up to 7 days).
    for offset in range(0, 8):  # today + up to 7 days back
        d = on - timedelta(days=offset)
        if rate_cache is not None:
            cached = rate_cache.get((base, d))
            if cached is not None:
                return cached
        rate = _db_fetch(currency, d, db)
        if rate is not None:
            return rate

    # 3. Frankfurter
    if fallback:
        for offset in range(0, 8):
            d = on - timedelta(days=offset)
            rate = _frankfurter_fetch(currency, d)
            if rate is not None:
                return rate

    # 4. Static fallback (USD only)
    if base == "USD":
        # find nearest date
        for offset in range(0, 365):
            d = on - timedelta(days=offset)
            if d in _STATIC_FALLBACK_USDINR:
                logger.warning(
                    "fx_cost_basis: using STATIC fallback USD/INR rate for "
                    f"{on.isoformat()} (resolved {d.isoformat()}={_STATIC_FALLBACK_USDINR[d]}). "
                    "DB fx_rates + Frankfurter both missed — tax INR conversion may be stale."
                )
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
    rate_cache: RateCache | None = None,
) -> Decimal:
    """Convert ``amount`` in ``currency`` to INR using ``on``-date FX rate."""
    rate = get_fx_rate(currency, on, db=db, rate_cache=rate_cache)
    return (amount * rate).quantize(Decimal("0.01"))


def rbi_peak_balance_usd_inr(
    daily_balances_usd: dict[date, Decimal],
    *,
    db: Any | None = None,
    rate_cache: RateCache | None = None,
) -> tuple[Decimal, Decimal, date]:
    """Peak USD balance during a period + its INR-converted value + date.

    Used by Schedule FA. Returns ``(peak_usd, peak_usd_in_inr, peak_date)``.
    """
    if not daily_balances_usd:
        return (Decimal("0"), Decimal("0"), date.min)
    peak_date = max(daily_balances_usd, key=lambda d: daily_balances_usd[d])
    peak_usd = daily_balances_usd[peak_date]
    peak_inr = convert_to_inr(peak_usd, "USD", peak_date, db=db, rate_cache=rate_cache)
    return (peak_usd, peak_inr, peak_date)
