"""Resolve which ingest ``source`` actually holds a symbol's OHLCV data.

The scheduled feature/regime flows must read OHLCV from the same ``source`` the
data was *ingested* under. A static heuristic (US equity -> ``yfinance``,
NSE -> ``jugaad``) mislabels reality:

* US equities land under ``tiingo`` (see ``pfip.ingest.us_equities.tiingo_ohlcv``)
* NSE names land under ``nse_bhavcopy``

so heuristic-driven reads returned **0 rows** for e.g. SPY / NVDA / QQQ and the
scheduled compute-features / regime flows silently wrote nothing for them. This
helper asks the database which source the bars are actually under instead of
guessing, and callers fall back to the static heuristic only when there are no
bars yet (e.g. a freshly-added watchlist symbol that hasn't been ingested).
"""

from __future__ import annotations

from sqlalchemy import func, select


async def resolve_ohlcv_source(session, symbol: str, timeframe: str) -> str | None:
    """Return the ``source`` holding the most OHLCV bars for ``(symbol, timeframe)``.

    Picking the source with the *most* rows (rather than merely the most recent
    bar) is the robust choice: if a symbol ever has bars under two sources — say
    a full ``tiingo`` history plus a single stray ``yfinance`` backfill — we want
    the one with real coverage so the HMM / technicals have enough data. Ties are
    broken by the most-recent bar, so a freshly back-filled source overtakes a
    stale one once their coverage is equal.

    Returns ``None`` when the symbol has no OHLCV rows yet; the caller is expected
    to fall back to a static heuristic in that case.

    Never raises: a query failure (e.g. the table is absent under a unit-test
    fake session) resolves to ``None`` so a best-effort source lookup can never
    abort the surrounding feature/regime run.
    """
    try:
        from pfip.models.ohlcv import OHLCVRow

        source = (
            await session.execute(
                select(OHLCVRow.source)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.timeframe == timeframe,
                )
                .group_by(OHLCVRow.source)
                .order_by(func.count().desc(), func.max(OHLCVRow.time).desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return str(source) if source else None
    except Exception:  # defensive: missing table / fake session — see docstring
        return None
