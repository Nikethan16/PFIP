"""One-time history backfill — seed a FRESH Neon DB with ~3 years of data.

Run this **once** (via the ``backfill`` GitHub Actions workflow's
``workflow_dispatch``, or locally) right after ``alembic upgrade head`` on an
empty managed-Postgres database. It pulls ~3 years of daily history so the
feature/regime/signal stack has enough substrate to be meaningful, then computes
features + regime + signals for the whole watchlist.

This replaces the old "dump the local TimescaleDB hypertables and restore them
into the cloud" approach: instead of moving bytes, we re-pull from the same free
upstream sources the daily pipeline uses, so there's nothing to export/import and
no Timescale-specific dump format to wrangle.

What it seeds
-------------
* **crypto** — BTC/ETH/SOL-USD daily candles via ccxt, **paginated** back ~1100
  bars (Coinbase serves only ~300 candles/call, so a single call can't reach 3y;
  we page with ``since`` until we have enough). Falls back across
  Coinbase→Kraken→Bybit→OKX per symbol.
* **US** — the watchlist's US tickers via Tiingo EOD with a ~1200-day lookback
  (Tiingo is date-range based, so one call returns the full window).
* **India** — the 50 NIFTY-50 ``.NS`` names + ``NIFTYBEES.NS`` via jugaad with a
  ~1200-day lookback (jugaad is also date-range based).
* **FX** — USD/EUR/GBP→INR daily history via Frankfurter (~1100 days).
* then **features → regime → signals** for the watchlist (reusing the daily
  pipeline's stages verbatim).

Idempotent + non-fatal: every upsert is ``ON CONFLICT DO NOTHING`` and every
symbol/source is wrapped so one failure (delisted name, exchange 429) can't abort
the seed. Safe to re-run.

Run:

    python -m scripts.backfill_history                 # full ~3y seed
    python -m scripts.backfill_history --days 1100     # custom depth
    python -m scripts.backfill_history --skip-compute  # data only, no features
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio

from pfip.core.contracts import to_canonical_symbol
from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.upsert import upsert_ohlcv_rows

# Reuse the daily pipeline's compute stages + watchlist helpers verbatim so the
# backfill and the daily run share exactly one code path for features/regime/
# signals and for resolving the real per-market universe.
from scripts.run_daily_pipeline import (
    CRYPTO_SYMBOLS,
    StageSummary,
    _guarded,
    _india_watchlist_symbols,
    _us_watchlist_symbols,
    stage_features,
    stage_regime,
    stage_signals,
)

log = get_logger("scripts.backfill_history")

# Default seed depth (days). ~1100 trading-day-ish window → ~3 years of D1 bars.
DEFAULT_DAYS = 1200

# ccxt exchanges to try per crypto symbol, in priority order. Mirrors
# ``pfip.ingest.crypto.ccxt_multi.SUPPORTED_EXCHANGES`` but we page each one.
CRYPTO_EXCHANGES: tuple[str, ...] = ("coinbase", "kraken", "bybit", "okx")

# Per-exchange symbol rewrites (USDT-quoted on Bybit/OKX). Same map as ccxt_multi.
_SYMBOL_REWRITES: dict[str, dict[str, str]] = {
    "BTC/USD": {"bybit": "BTC/USDT", "okx": "BTC/USDT"},
    "ETH/USD": {"bybit": "ETH/USDT", "okx": "ETH/USDT"},
    "SOL/USD": {"bybit": "SOL/USDT", "okx": "SOL/USDT"},
    "BNB/USD": {"bybit": "BNB/USDT", "okx": "BNB/USDT", "coinbase": "BNB/USD"},
    "XRP/USD": {"bybit": "XRP/USDT", "okx": "XRP/USDT"},
}

# Per-call candle cap to request from ccxt. Exchanges clamp this to their own max
# (Coinbase ~300, Kraken ~720); we just page until we reach the target depth.
_CCXT_PAGE_LIMIT = 300


# ---------------------------------------------------------------------------
# Crypto: paginated ccxt fetch (the one source that needs paging for 3y)
# ---------------------------------------------------------------------------


def _paginate_ccxt_sync(
    exchange_id: str, symbol: str, timeframe: str, since_ms: int, target_bars: int
) -> list[list[Any]]:
    """Synchronously page ``fetch_ohlcv`` forward from ``since_ms``.

    ccxt is sync; this runs in a worker thread. We keep requesting pages, each
    starting just after the last candle we received, until we either reach
    ``target_bars``, catch up to ~now, or stop making progress. Returns the raw
    ccxt rows ``[ts_ms, o, h, l, c, v]`` (deduped, ascending).
    """
    import ccxt

    if not hasattr(ccxt, exchange_id):
        return []
    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})

    now_ms = int(time.time() * 1000)
    one_day_ms = 86_400_000
    cursor = since_ms
    seen: dict[int, list[Any]] = {}

    # Hard cap on page count so a misbehaving exchange can't loop forever.
    max_pages = (target_bars // _CCXT_PAGE_LIMIT) + 5
    for _ in range(max_pages):
        try:
            batch = exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=cursor, limit=_CCXT_PAGE_LIMIT
            )
        except Exception as e:  # noqa: BLE001 — bubble up as "no more data"
            log.warning(f"ccxt page {exchange_id} {symbol} failed: {type(e).__name__}: {e}")
            break
        if not batch:
            break
        new = 0
        last_ts = cursor
        for row in batch:
            ts = int(row[0])
            last_ts = ts
            if ts not in seen:
                seen[ts] = row
                new += 1
        # Advance the cursor one day past the last candle we got.
        next_cursor = last_ts + one_day_ms
        if next_cursor <= cursor:  # no forward progress → stop
            break
        cursor = next_cursor
        if len(seen) >= target_bars or cursor >= now_ms or new == 0:
            break

    return [seen[k] for k in sorted(seen)]


async def _backfill_crypto_symbol(symbol: str, *, target_bars: int, timeframe: str) -> int:
    """Backfill one crypto symbol, trying each exchange until we hit target depth.

    Writes rows under whichever exchange ``source`` actually served them (so the
    feature/regime resolver later reads the same source). Returns rows upserted.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(days=int(target_bars * 1.6))
    since_ms = int(since.timestamp() * 1000)

    total = 0
    for ex in CRYPTO_EXCHANGES:
        use_sym = _SYMBOL_REWRITES.get(symbol, {}).get(ex, symbol)
        raw = await anyio.to_thread.run_sync(
            _paginate_ccxt_sync, ex, use_sym, timeframe, since_ms, target_bars
        )
        if not raw:
            continue
        market = use_sym.replace("/", "_").replace("-", "_").upper()
        canonical = to_canonical_symbol(use_sym)
        rows = [
            {
                "time": datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc),
                "symbol": canonical,
                "market": market,
                "source": ex,
                "timeframe": timeframe,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v or 0,
            }
            for ts, o, h, low, c, v in raw
        ]
        factory = get_sessionmaker()
        async with factory() as s:
            n = await upsert_ohlcv_rows(s, rows)
        total += n
        log.info(f"crypto backfill {ex} {use_sym}: {len(rows)} bars ({n} new)")
        # Once an exchange gave us a healthy series, don't pile on duplicates from
        # the USDT-quoted fallbacks (which write under a *different* canonical
        # symbol, e.g. BTC-USDT). Stop after the first exchange that reached depth.
        if len(rows) >= target_bars * 0.8:
            break
    return total


# ---------------------------------------------------------------------------
# Backfill stages
# ---------------------------------------------------------------------------


async def backfill_data(*, days: int = DEFAULT_DAYS) -> StageSummary:
    """Seed ~``days`` of OHLCV + FX history across all markets. Non-fatal."""
    summary = StageSummary(name="backfill_data")
    target_bars = days  # ~1 bar/day for D1

    # --- crypto (paginated) ---
    async def _crypto() -> dict[str, int]:
        out: dict[str, int] = {}
        for sym in CRYPTO_SYMBOLS:
            try:
                out[sym] = await _backfill_crypto_symbol(
                    sym, target_bars=target_bars, timeframe="1d"
                )
            except Exception as e:  # noqa: BLE001
                out[sym] = -1
                log.warning(f"crypto backfill {sym} failed: {type(e).__name__}: {e}")
        return out

    await _guarded(summary, "crypto", _crypto, timeout=1200.0)

    # --- US (Tiingo, single date-range call) ---
    async def _us() -> int:
        from pfip.ingest.us_equities.tiingo_ohlcv import fetch_tiingo

        symbols = await _us_watchlist_symbols()
        rows = await fetch_tiingo(symbols, lookback_days=days)
        factory = get_sessionmaker()
        async with factory() as s:
            return await upsert_ohlcv_rows(s, rows)

    await _guarded(summary, "us_tiingo", _us, timeout=600.0)

    # --- India (jugaad, single date-range call per symbol) ---
    async def _india() -> int:
        from pfip.ingest.indian_equities.jugaad_ohlcv import ingest_jugaad

        symbols = await _india_watchlist_symbols()
        return await ingest_jugaad(symbols=symbols, lookback_days=days)

    await _guarded(summary, "india_jugaad", _india, timeout=900.0)

    # --- FX (Frankfurter range backfill) ---
    async def _fx() -> int:
        from pfip.ingest.macro.fx_rates import ingest_fx_rates

        n = await ingest_fx_rates(mode="backfill", lookback_days=days)
        n += await ingest_fx_rates(mode="latest")
        return n

    await _guarded(summary, "fx_frankfurter", _fx, timeout=600.0)

    # --- India MF NAVs (AMFI) ---
    async def _india_mf() -> int:
        from pfip.ingest.indian_mf.amfi_nav import ingest_amfi_nav

        return await ingest_amfi_nav()

    await _guarded(summary, "india_mf_amfi", _india_mf, timeout=300.0)

    summary.finish()
    return summary


async def run_backfill(
    *, days: int = DEFAULT_DAYS, compute: bool = True, timeframe: str = "1d"
) -> dict[str, Any]:
    """Full one-time seed: data → features → regime → signals."""
    log.info(f"backfill starting: days={days}, compute={compute}")
    started = time.monotonic()
    results: dict[str, Any] = {}

    data = await backfill_data(days=days)
    results["backfill_data"] = data.as_dict()

    if compute:
        # Backfill is the one place we stamp extras onto every historical bar so
        # supervised models get a real feature history (the daily run only
        # refreshes the latest bar).
        feats = await stage_features(timeframe=timeframe, historical_extras=True)
        results["features"] = feats.as_dict()
        regime = await stage_regime(timeframe=timeframe)
        results["regime"] = regime.as_dict()
        signals = await stage_signals(timeframe=timeframe)
        results["signals"] = signals.as_dict()

    summary = {
        "days": days,
        "compute": compute,
        "elapsed_s": round(time.monotonic() - started, 1),
        "results": results,
    }
    log.info("backfill summary:\n" + json.dumps(summary, indent=2, default=str))
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-time ~3y history backfill for a fresh Neon DB (no Prefect/Docker).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"History depth in days (default: {DEFAULT_DAYS} ≈ 3 years).",
    )
    p.add_argument("--timeframe", default="1d", help="OHLCV timeframe (default: 1d).")
    p.add_argument(
        "--skip-compute",
        action="store_true",
        help="Only seed OHLCV/FX data; skip features/regime/signals.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    return asyncio.run(
        run_backfill(days=args.days, compute=not args.skip_compute, timeframe=args.timeframe)
    )


if __name__ == "__main__":
    main()
