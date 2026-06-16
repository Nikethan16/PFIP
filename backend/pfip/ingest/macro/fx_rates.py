"""FX reference rates — Frankfurter (ECB), no API key.

Populates the dedicated ``fx_rates`` table (created in migration 0006) so the
tax / mark-to-market path in :mod:`pfip.tax.fx_cost_basis` can resolve
``base``→INR rates. That reader queries:

    SELECT rate FROM fx_rates
    WHERE base = :base AND quote = 'INR' AND rate_date <= :on
    ORDER BY rate_date DESC LIMIT 1

so we MUST write the exact columns ``base``, ``quote``, ``rate`` and
``rate_date`` (plus ``source`` which is part of the PK).

Endpoints (free, no key):
    - Range:  GET https://api.frankfurter.app/{start}..{end}?from=USD&to=INR
    - Latest: GET https://api.frankfurter.app/latest?from=USD&to=INR
Both return ``{"base": "USD", "rates": {"YYYY-MM-DD": {"INR": x, ...}, ...}}``
for the range endpoint; the latest endpoint returns a single flat
``{"base": "USD", "date": "YYYY-MM-DD", "rates": {"INR": x, ...}}``.

USD->INR is the priority pair; EUR->INR and GBP->INR ride along for free via
the multi-``to`` parameter.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import get_async_client, retry_http

log = get_logger("pfip.ingest.macro.fx_rates")

BASE_URL = "https://api.frankfurter.app"
SOURCE = "frankfurter"

# USD is the priority base; EUR/GBP ride along on the same request.
DEFAULT_BASE = "USD"
DEFAULT_QUOTES: tuple[str, ...] = ("INR",)
# Extra bases worth backfilling cheaply (each is one extra HTTP request).
DEFAULT_EXTRA_BASES: tuple[str, ...] = ("EUR", "GBP")


# ---------------------------------------------------------------------------
# URL / param construction (pure — unit-tested without network)
# ---------------------------------------------------------------------------


def range_path(start: date, end: date) -> str:
    """Frankfurter date-range path: ``/{start}..{end}``."""
    return f"/{start.isoformat()}..{end.isoformat()}"


def latest_path() -> str:
    """Frankfurter latest path."""
    return "/latest"


def query_params(base: str, quotes: Iterable[str]) -> dict[str, str]:
    """Build the ``from``/``to`` query for a base + quote list."""
    return {"from": base.upper(), "to": ",".join(q.upper() for q in quotes)}


# ---------------------------------------------------------------------------
# Response parsing (pure — unit-tested without network)
# ---------------------------------------------------------------------------


def parse_rate_rows(payload: dict[str, Any], base: str) -> list[dict[str, Any]]:
    """Map a Frankfurter JSON payload into ``fx_rates`` rows.

    Handles both shapes:
      * range:  ``{"rates": {"2026-01-02": {"INR": 84.2, ...}, ...}}``
      * latest: ``{"date": "2026-01-02", "rates": {"INR": 84.2, ...}}``

    Returns a list of dicts with exactly the columns written to ``fx_rates``:
    ``rate_date`` (date), ``base`` (upper), ``quote`` (upper), ``rate``
    (float) and ``source``.
    """
    base_u = (payload.get("base") or base or "").upper()
    rates = payload.get("rates") or {}
    rows: list[dict[str, Any]] = []

    if not isinstance(rates, dict) or not rates:
        return rows

    # Detect shape: range payloads key by date-string -> {quote: rate};
    # latest payloads key by quote -> rate (a flat scalar map).
    sample = next(iter(rates.values()))
    is_range = isinstance(sample, dict)

    if is_range:
        items: Iterable[tuple[str, dict[str, Any]]] = rates.items()
    else:
        # Flat latest map: synthesize a single date bucket from payload["date"].
        d = payload.get("date")
        items = [(d, rates)] if d else []

    for d_str, quote_map in items:
        try:
            rate_date = date.fromisoformat(str(d_str))
        except (ValueError, TypeError):
            continue
        if not isinstance(quote_map, dict):
            continue
        for quote, value in quote_map.items():
            if value is None:
                continue
            try:
                rate = float(value)
            except (ValueError, TypeError):
                continue
            rows.append(
                {
                    "rate_date": rate_date,
                    "base": base_u,
                    "quote": str(quote).upper(),
                    "rate": rate,
                    "source": SOURCE,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# DB upsert (idempotent; matches the text()/ON CONFLICT style used elsewhere)
# ---------------------------------------------------------------------------


async def upsert_fx_rates(session: AsyncSession, rows: Iterable[dict[str, Any]]) -> int:
    """Idempotently upsert ``fx_rates`` rows.

    PK is ``(rate_date, base, quote, source)`` (migration 0006). On conflict we
    refresh ``rate`` (and ``ingested_at``) so re-runs pick up any restatement.
    """
    stmt = text(
        """
        INSERT INTO fx_rates (rate_date, base, quote, rate, source)
        VALUES (:rate_date, :base, :quote, :rate, :source)
        ON CONFLICT (rate_date, base, quote, source) DO UPDATE SET
            rate = EXCLUDED.rate,
            ingested_at = now()
        """
    )
    count = 0
    for row in rows:
        await session.execute(
            stmt,
            {
                "rate_date": (
                    row["rate_date"]
                    if isinstance(row["rate_date"], date)
                    else date.fromisoformat(str(row["rate_date"]))
                ),
                "base": str(row["base"]).upper(),
                "quote": str(row["quote"]).upper(),
                "rate": row["rate"],
                "source": row.get("source", SOURCE),
            },
        )
        count += 1
    await session.commit()
    return count


# ---------------------------------------------------------------------------
# HTTP fetch (async; shared client + retry/backoff)
# ---------------------------------------------------------------------------


@retry_http(max_attempts=3)
async def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(f"{BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json() or {}


async def fetch_range(
    base: str,
    quotes: Iterable[str],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Fetch the daily ``base``->``quotes`` rates over ``[start, end]``."""
    payload = await _get(range_path(start, end), query_params(base, quotes))
    return parse_rate_rows(payload, base)


async def fetch_latest(base: str, quotes: Iterable[str]) -> list[dict[str, Any]]:
    """Fetch the most recent ``base``->``quotes`` rates."""
    payload = await _get(latest_path(), query_params(base, quotes))
    return parse_rate_rows(payload, base)


# ---------------------------------------------------------------------------
# Public ingest entrypoints
# ---------------------------------------------------------------------------


async def ingest_fx_rates(
    *,
    mode: str = "latest",
    lookback_days: int = 7,
    bases: Iterable[str] | None = None,
    quotes: Iterable[str] = DEFAULT_QUOTES,
    session: AsyncSession | None = None,
) -> int:
    """Ingest FX rates into ``fx_rates``.

    Parameters
    ----------
    mode:
        ``"latest"`` (daily ECB fix) or ``"backfill"`` (date range ending today,
        spanning ``lookback_days``).
    lookback_days:
        Range size for ``mode="backfill"``. e.g. ``365`` for a year.
    bases:
        Base currencies. Defaults to ``("USD", "EUR", "GBP")`` (USD priority).
    quotes:
        Quote currencies. Defaults to ``("INR",)``.
    session:
        Optional caller-provided ``AsyncSession``. If absent, a fresh one is
        opened from the process session factory.

    Returns the number of rows upserted (idempotent).
    """
    base_list = list(bases) if bases is not None else [DEFAULT_BASE, *DEFAULT_EXTRA_BASES]
    quote_list = list(quotes)
    log.info(f"ingest.fx_rates starting (mode={mode}, bases={base_list}, quotes={quote_list})")

    all_rows: list[dict[str, Any]] = []
    end = date.today()
    start = end - timedelta(days=max(0, lookback_days))

    async def _fetch_one(base: str) -> list[dict[str, Any]]:
        try:
            if mode == "backfill":
                return await fetch_range(base, quote_list, start, end)
            return await fetch_latest(base, quote_list)
        except Exception as e:  # noqa: BLE001
            log.warning(f"fx_rates: {base}->{quote_list} failed: {type(e).__name__}: {e}")
            return []

    results = await asyncio.gather(*(_fetch_one(b) for b in base_list))
    for rows in results:
        all_rows.extend(rows)

    if not all_rows:
        log.warning("ingest.fx_rates: no rows fetched")
        return 0

    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_fx_rates(s, all_rows)
    else:
        n = await upsert_fx_rates(session, all_rows)
    log.info(f"ingest.fx_rates done: {n} rows")
    return n
