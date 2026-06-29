"""Plain-async daily PFIP pipeline — the always-on cloud entrypoint.

This is the script GitHub Actions runs on a schedule against managed Postgres
(Neon), and which can also be run locally against the Docker DB. It deliberately
does **not** depend on Prefect or Docker: it imports the same underlying ingest /
feature / regime / signal functions the Prefect flows call and drives them
directly with ``asyncio``.

Design goals
------------
* **Env-driven DB.** Everything routes through ``DATABASE_URL`` (read by
  ``pfip.core.config`` → ``pfip.db.session``). Nothing here hardcodes a DSN, so
  the same script works on Neon, local Docker, or a bare venv.
* **Each stage is non-fatal.** A dead source (rate-limited, WAF-blocked, hung
  CDN) must never abort the whole job. Every source runs under
  ``asyncio.wait_for`` with a wall-clock budget and is wrapped in try/except —
  on timeout/error we log and contribute 0 rows.
* **Stage selection via argv.** ``--stages ingest,features,regime,signals``
  (default: all). Useful for cheap CI probes and for splitting work across the
  two daily cron windows (US close vs India close).
* **Structured summary.** Ends with a per-stage / per-source rows+symbols dict
  printed as JSON so the Actions log (and any future alerting) has a machine-
  readable record.
* **Retention.** Prunes ``features`` older than ~1200 days and ensures the news
  relevance/age prune ran, keeping a free-tier Neon DB (0.5 GB) bounded.

Run locally (no Prefect):

    # cheap probe — just recompute features + regime from existing OHLCV
    python -m scripts.run_daily_pipeline --stages features,regime

    # full daily run
    python -m scripts.run_daily_pipeline

    # one stage, bounded
    python -m scripts.run_daily_pipeline --stages ingest
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from sqlalchemy import text

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker

log = get_logger("scripts.run_daily_pipeline")

# ---------------------------------------------------------------------------
# Stage / source configuration
# ---------------------------------------------------------------------------

ALL_STAGES: tuple[str, ...] = (
    "ingest",
    "features",
    "regime",
    "signals",
    "events",
    "shadow",
    "retention",
)

# Crypto symbols to refresh daily (ccxt slash form; the adapter canonicalizes to
# dash form on write). Matches the watchlist crypto universe.
CRYPTO_SYMBOLS: tuple[str, ...] = ("BTC/USD", "ETH/USD", "SOL/USD", "BNB/USD", "XRP/USD")

# US symbols we actively track (Tiingo EOD). Kept in sync with the watchlist's
# US rows; ETFs included because Tiingo serves them.
US_SYMBOLS: tuple[str, ...] = ("SPY", "NVDA")

# Per-source wall-clock budgets (seconds). A source that exceeds its budget is
# abandoned (0 rows) so it can't head-of-line-block the whole job. Multi-feed /
# multi-symbol sources get larger budgets.
TIMEOUT_CRYPTO = 240.0
TIMEOUT_US = 240.0
TIMEOUT_INDIA = 420.0  # jugaad iterates ~50 NSE symbols sequentially
TIMEOUT_FX = 90.0
TIMEOUT_NEWS = 300.0  # many feeds + the post-ingest pipeline (dedupe/classify/prune)
TIMEOUT_FUNDAMENTALS = 300.0
TIMEOUT_COMPUTE = 1800.0  # features/regime/signals over the whole watchlist

# Retention: keep ~3.3 years of feature history. OHLCV history is kept (it's the
# training substrate); features are recomputable so they're the cheap thing to
# prune to bound DB size on the free tier.
FEATURES_RETENTION_DAYS = 1200


# ---------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------


@dataclass
class StageSummary:
    """Accumulates per-source outcomes for one stage."""

    name: str
    sources: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    elapsed_s: float = 0.0
    skipped: bool = False

    def record(self, source: str, value: Any) -> None:
        self.sources[source] = value

    def finish(self) -> None:
        self.elapsed_s = round(time.monotonic() - self.started_at, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "elapsed_s": self.elapsed_s,
            "skipped": self.skipped,
            **self.sources,
        }


async def _guarded(
    summary: StageSummary,
    source: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    timeout: float,
) -> Any:
    """Run one source ingest under a wall-clock timeout; never raise.

    Records the row count (or an ``"error: ..."`` / ``"timeout"`` marker) into
    ``summary`` and returns the value (or ``None`` on failure). Keeps the stage
    non-fatal: one bad source can't abort the others or the job.
    """
    t0 = time.monotonic()
    err: str | None = None
    result: Any = None
    rows = 0
    try:
        result = await asyncio.wait_for(coro_factory(), timeout=timeout)
        summary.record(source, result)
        rows = result if isinstance(result, int) else 0
        log.info(f"[{summary.name}] {source}: {result} ({time.monotonic() - t0:.0f}s)")
    except asyncio.TimeoutError:
        err = f"timeout>{timeout:.0f}s"
        summary.record(source, err)
        log.warning(f"[{summary.name}] {source} timed out after {timeout:.0f}s; skipping")
    except Exception as e:  # noqa: BLE001 — non-fatal by design
        err = f"{type(e).__name__}: {e}"
        summary.record(source, f"error: {err}")
        log.warning(f"[{summary.name}] {source} failed: {type(e).__name__}: {e}")
    # Observability: record per-source health (rows + error + timestamp) so silent
    # source failures surface on the ops page. Best-effort — never fatal.
    try:
        from pfip.ingest._common.source_health import record_run

        await record_run(f"{summary.name}:{source}", rows=rows, error=err)
    except Exception as he:  # noqa: BLE001
        log.debug(f"source_health record skipped for {source}: {he}")
    return result


# ---------------------------------------------------------------------------
# Watchlist helpers (resolve the REAL universe from the DB)
# ---------------------------------------------------------------------------


async def _india_watchlist_symbols() -> list[str]:
    """NSE symbols from the watchlist, ``.NS`` stripped (jugaad wants bare names).

    Falls back to a tiny default if the table is empty/unreachable so a fresh DB
    still ingests something useful.
    """
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            r = await s.execute(
                text(
                    """
                    SELECT symbol FROM watchlist
                    WHERE upper(market) IN ('IN', 'NSE', 'BSE', 'NIFTY50', 'NIFTY500', 'SENSEX')
                       OR symbol ~ '\\.(NS|BO)$'
                    """
                )
            )
            syms = [
                row[0].replace(".NS", "").replace(".BO", "")
                for row in r.fetchall()
                if row and row[0]
            ]
            return syms or ["RELIANCE", "TCS", "HDFCBANK", "INFY"]
    except Exception as e:  # noqa: BLE001
        log.warning(f"india watchlist read failed: {type(e).__name__}: {e}")
        return ["RELIANCE", "TCS", "HDFCBANK", "INFY"]


async def _us_watchlist_symbols() -> list[str]:
    """US tickers from the watchlist (no suffix); falls back to the tracked set."""
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            r = await s.execute(
                text(
                    """
                    SELECT symbol FROM watchlist
                    WHERE upper(market) IN ('US', 'US_EQUITY', 'US_ETF', 'SPY', 'QQQ', 'DIA', 'VTI')
                       OR (symbol ~ '^[A-Z]{1,5}$' AND symbol NOT LIKE '%.%')
                    """
                )
            )
            syms = [row[0] for row in r.fetchall() if row and row[0]]
            return syms or list(US_SYMBOLS)
    except Exception as e:  # noqa: BLE001
        log.warning(f"us watchlist read failed: {type(e).__name__}: {e}")
        return list(US_SYMBOLS)


# ---------------------------------------------------------------------------
# INGEST stage
# ---------------------------------------------------------------------------


async def stage_ingest(
    *,
    crypto_lookback_days: int = 7,
    us_lookback_days: int = 14,
    india_lookback_days: int = 30,
    fx_backfill: bool = False,
    fx_backfill_days: int = 365,
    include_news: bool = True,
    include_fundamentals: bool = True,
) -> StageSummary:
    """Refresh all raw data sources. Each source is non-fatal + time-bounded.

    The lookbacks are small (a daily top-up); ``backfill_history`` uses much
    larger windows for the one-time seed. Idempotent everywhere (all adapters
    upsert), so re-running is safe.
    """
    summary = StageSummary(name="ingest")

    # --- crypto (ccxt) ---
    async def _crypto() -> int:
        from pfip.ingest.crypto.ccxt_multi import ingest_watchlist

        return await ingest_watchlist(
            symbols=list(CRYPTO_SYMBOLS),
            timeframe="1d",
            lookback_days=crypto_lookback_days,
        )

    await _guarded(summary, "crypto_ccxt", _crypto, timeout=TIMEOUT_CRYPTO)

    # --- US EOD (Tiingo) ---
    async def _us() -> int:
        from pfip.ingest.us_equities.tiingo_ohlcv import fetch_tiingo
        from pfip.ingest._common.upsert import upsert_ohlcv_rows

        symbols = await _us_watchlist_symbols()
        rows = await fetch_tiingo(symbols, lookback_days=us_lookback_days)
        factory = get_sessionmaker()
        async with factory() as s:
            return await upsert_ohlcv_rows(s, rows)

    await _guarded(summary, "us_tiingo", _us, timeout=TIMEOUT_US)

    # --- US EOD fallback (yfinance, no key) — fills gaps when Tiingo lags ---
    async def _us_yf() -> int:
        from pfip.ingest.us_equities.yfinance_ohlcv import ingest_yfinance

        return await ingest_yfinance(symbols=await _us_watchlist_symbols(), lookback_days=60)

    await _guarded(summary, "us_yfinance", _us_yf, timeout=TIMEOUT_US)

    # --- US EOD fallback #2 (Stooq, no key) — reachable where Yahoo blocks the
    # VM's datacenter IP (observed: us_yfinance returns 0 rows on the Oracle box). ---
    async def _us_stooq() -> int:
        from pfip.ingest.us_equities.stooq_ohlcv import ingest_stooq

        return await ingest_stooq(symbols=await _us_watchlist_symbols())

    await _guarded(summary, "us_stooq", _us_stooq, timeout=TIMEOUT_US)

    # --- India EOD (jugaad) ---
    async def _india() -> int:
        from pfip.ingest.indian_equities.jugaad_ohlcv import ingest_jugaad

        symbols = await _india_watchlist_symbols()
        return await ingest_jugaad(symbols=symbols, lookback_days=india_lookback_days)

    await _guarded(summary, "india_jugaad", _india, timeout=TIMEOUT_INDIA)

    # --- India EOD fallback (yfinance handles .NS) — fills gaps when NSE/jugaad lags ---
    async def _india_yf() -> int:
        from pfip.ingest.us_equities.yfinance_ohlcv import ingest_yfinance

        # _india_watchlist_symbols() returns BARE names (jugaad-style); yfinance
        # needs the .NS/.BO suffix, and we store under that suffixed symbol to
        # match how jugaad rows + the frontend reference them.
        bare = await _india_watchlist_symbols()
        symbols = [s if s.endswith((".NS", ".BO")) else f"{s}.NS" for s in bare]
        return await ingest_yfinance(symbols=symbols, lookback_days=60)

    await _guarded(summary, "india_yfinance", _india_yf, timeout=TIMEOUT_INDIA)

    # --- FX (frankfurter, no key) ---
    async def _fx() -> int:
        from pfip.ingest.macro.fx_rates import ingest_fx_rates

        total = 0
        if fx_backfill:
            total += await ingest_fx_rates(mode="backfill", lookback_days=fx_backfill_days)
        total += await ingest_fx_rates(mode="latest")
        return total

    await _guarded(summary, "fx_frankfurter", _fx, timeout=TIMEOUT_FX)

    # --- Mutual-fund NAVs (AMFI, no key) ---
    async def _mf() -> int:
        from pfip.ingest.indian_mf.amfi_nav import ingest_amfi_nav

        return await ingest_amfi_nav()

    await _guarded(summary, "mf_amfi", _mf, timeout=TIMEOUT_INDIA)

    # --- Macro series (FRED; no-ops without FRED_API_KEY) ---
    async def _macro() -> int:
        from pfip.ingest.macro.fred import ingest_fred_macro

        return await ingest_fred_macro()

    await _guarded(summary, "macro_fred", _macro, timeout=TIMEOUT_FX)

    # --- news (raw adapters + post-ingest pipeline incl. relevance/age prune) ---
    if include_news:
        await _guarded(summary, "news", _ingest_news, timeout=TIMEOUT_NEWS)

    # --- fundamentals (finnhub US metrics + screener.in India ratios) ---
    if include_fundamentals:
        await _guarded(summary, "fundamentals", _ingest_fundamentals, timeout=TIMEOUT_FUNDAMENTALS)

    summary.finish()
    return summary


async def _ingest_news() -> dict[str, Any]:
    """Run the news adapters that have usable creds, then the post-ingest pipeline.

    Mirrors ``pfip.prefect.flows.ingest_news_15min`` but without Prefect: each
    adapter is guarded so a single 403/429/hang contributes 0 rows, and we then
    run ``pfip.ingest.news._pipeline.run_pipeline`` which dedupes, entity-links,
    classifies, and — critically for storage — **prunes** the irrelevant/stale
    news so the table stays small.
    """
    from pfip.ingest.crypto.cryptopanic import ingest_cryptopanic
    from pfip.ingest.news.bluesky import ingest_bluesky
    from pfip.ingest.news.farcaster import ingest_farcaster
    from pfip.ingest.news.gdelt import ingest_gdelt
    from pfip.ingest.news.google_news_rss import ingest_google_news
    from pfip.ingest.news.marketaux import ingest_marketaux
    from pfip.ingest.news.newsapi import ingest_newsapi
    from pfip.ingest.news.reddit_praw import ingest_reddit
    from pfip.ingest.news.rss_fetcher import ingest_rss
    from pfip.ingest.news.telegram_telethon import ingest_telegram

    google_queries = ["RELIANCE NS", "TCS NS", "NIFTY", "SPY", "bitcoin"]

    # (name, coro_factory, per-source timeout)
    sources: list[tuple[str, Callable[[], Awaitable[int]], float]] = [
        ("rss", ingest_rss, 120.0),
        ("google_news", lambda: ingest_google_news(queries=google_queries), 120.0),
        ("gdelt", ingest_gdelt, 60.0),
        ("reddit", ingest_reddit, 45.0),
        ("telegram", ingest_telegram, 45.0),
        ("bluesky", ingest_bluesky, 45.0),
        ("farcaster", ingest_farcaster, 45.0),
        ("cryptopanic", ingest_cryptopanic, 45.0),
        ("newsapi", ingest_newsapi, 45.0),
        ("marketaux", ingest_marketaux, 45.0),
    ]

    per_source: dict[str, Any] = {}
    total = 0
    for name, factory_fn, src_timeout in sources:
        try:
            n = int(await asyncio.wait_for(factory_fn(), timeout=src_timeout))
            per_source[name] = n
            total += n
        except asyncio.TimeoutError:
            per_source[name] = "timeout"
        except Exception as e:  # noqa: BLE001
            per_source[name] = f"error: {type(e).__name__}"

    # Post-ingest pipeline: dedupe → entity-link → classify → PRUNE → embed.
    pipeline: Any = "skipped"
    try:
        from pfip.ingest.news._pipeline import run_pipeline

        pipeline = await asyncio.wait_for(run_pipeline(), timeout=180.0)
    except Exception as e:  # noqa: BLE001
        pipeline = f"error: {type(e).__name__}: {e}"

    return {"raw_rows": total, "per_source": per_source, "pipeline": pipeline}


async def _ingest_fundamentals() -> dict[str, Any]:
    """Finnhub /stock/metric for US + Screener.in ratios for India.

    Both are no-ops without their respective creds (Finnhub needs a key;
    Screener is keyless but polite/slow). Non-fatal individually.
    """
    out: dict[str, Any] = {}

    async def _finnhub() -> int:
        from pfip.ingest.us_equities.finnhub_fundamentals import ingest_finnhub

        symbols = await _us_watchlist_symbols()
        return await ingest_finnhub(symbols=symbols)

    async def _screener() -> int:
        from pfip.ingest.indian_equities.screener_fundamentals import ingest_screener

        symbols = await _india_watchlist_symbols()
        return await ingest_screener(symbols=symbols)

    try:
        out["finnhub"] = await asyncio.wait_for(_finnhub(), timeout=120.0)
    except Exception as e:  # noqa: BLE001
        out["finnhub"] = f"error: {type(e).__name__}"
    try:
        out["screener"] = await asyncio.wait_for(_screener(), timeout=240.0)
    except Exception as e:  # noqa: BLE001
        out["screener"] = f"error: {type(e).__name__}"
    return out


# ---------------------------------------------------------------------------
# FEATURES / REGIME / SIGNALS stages
# ---------------------------------------------------------------------------


async def stage_features(*, timeframe: str = "1d", historical_extras: bool = False) -> StageSummary:
    """Compute + persist the feature bundle for every watchlist asset.

    Reuses ``pfip.features.runner.run_for_watchlist`` which resolves each
    symbol's REAL OHLCV source from the DB (US under ``tiingo``, NSE under
    ``jugaad``/``nse_bhavcopy``), so it reads the bars that actually exist.

    ``historical_extras`` (set by the one-time backfill) stamps the time-varying
    extras onto every historical bar; the daily run leaves it off.
    """
    summary = StageSummary(name="features")

    async def _run() -> dict[str, Any]:
        from pfip.features.runner import run_for_watchlist

        factory = get_sessionmaker()
        async with factory() as s:
            results = await run_for_watchlist(
                s, timeframe=timeframe, historical_extras=historical_extras
            )
        total_rows = sum(r.rows_written for r in results)
        return {
            "symbols": len(results),
            "rows_written": total_rows,
            "with_data": sum(1 for r in results if r.rows_read > 0),
        }

    await _guarded(summary, "watchlist", _run, timeout=TIMEOUT_COMPUTE)
    summary.finish()
    return summary


async def _detect_regime_one(symbol: str, source: str, timeframe: str) -> str:
    """Fit the HMM on trailing 3y of D1 closes for one symbol; persist the label.

    Plain-async reimplementation of the per-symbol logic in
    ``pfip.prefect.flows.regime_detect_daily`` — same DB I/O and same
    :class:`pfip.regime.hmm_detector.HMMRegimeDetector`, but with no Prefect
    ``@task`` wrappers so this script never imports/needs the Prefect runtime.
    Returns ``"no-data"`` when there aren't enough bars to fit.
    """
    from datetime import datetime, timedelta, timezone

    import numpy as np
    import pandas as pd
    from sqlalchemy import desc, select

    from pfip.models.calibration_reports import RegimeTransitionRow
    from pfip.models.ohlcv import OHLCVRow
    from pfip.models.regime import RegimeRow
    from pfip.regime.hmm_detector import HMMRegimeDetector

    since = datetime.now(tz=timezone.utc) - timedelta(days=365 * 3)
    factory = get_sessionmaker()
    async with factory() as s:
        res = await s.execute(
            select(OHLCVRow)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.source == source,
                OHLCVRow.timeframe == timeframe,
                OHLCVRow.time >= since,
            )
            .order_by(OHLCVRow.time.asc())
        )
        rows = res.scalars().all()
    if not rows or len(rows) < 50:
        return "no-data"
    df = pd.DataFrame([{"time": r.time, "close": float(r.close)} for r in rows]).set_index("time")

    returns = np.log(df["close"] / df["close"].shift(1)).dropna()
    detector = HMMRegimeDetector(n_states=4)
    detector.fit(returns)
    try:  # MLflow persist is best-effort; never block the label write
        detector.persist_to_mlflow(run_name=f"regime_{symbol}")
    except Exception:  # noqa: BLE001
        pass

    last = detector.score_per_bar(df).iloc[-1]
    regime_label = str(last["regime"])
    confidence = float(last["confidence"])

    async with factory() as s:
        prev = (
            (
                await s.execute(
                    select(RegimeRow)
                    .where(RegimeRow.symbol == symbol)
                    .order_by(desc(RegimeRow.since))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        now = datetime.now(tz=timezone.utc)
        s.add(RegimeRow(symbol=symbol, regime=regime_label, since=now, confidence=confidence))
        if prev is None or prev.regime != regime_label:
            s.add(
                RegimeTransitionRow(
                    symbol=symbol,
                    from_regime=prev.regime if prev is not None else None,
                    to_regime=regime_label,
                    at=now,
                    confidence=confidence,
                )
            )
        await s.commit()
    log.info(f"[regime] {symbol}: {regime_label} (conf={confidence:.2f})")
    return regime_label


async def stage_regime(*, timeframe: str = "1d") -> StageSummary:
    """Fit the HMM regime detector per watchlist symbol and write today's label.

    Resolves each symbol's REAL OHLCV source via
    ``pfip.db.sources.resolve_ohlcv_source`` (US under ``tiingo``, NSE under
    ``jugaad``/``nse_bhavcopy``), then fits + persists with no Prefect runtime.
    """
    summary = StageSummary(name="regime")

    async def _run() -> dict[str, Any]:
        from sqlalchemy import select

        from pfip.db.sources import resolve_ohlcv_source
        from pfip.models.watchlist import WatchlistRow

        factory = get_sessionmaker()
        async with factory() as s:
            symbols = [
                str(r.symbol) for r in (await s.execute(select(WatchlistRow))).scalars().all()
            ]

        ok = 0
        no_data = 0
        errors = 0
        for sym in symbols:
            try:
                async with factory() as s:
                    src = await resolve_ohlcv_source(s, sym, timeframe)
                if not src:
                    no_data += 1
                    continue
                res = await _detect_regime_one(sym, src, timeframe)
                if res == "no-data":
                    no_data += 1
                else:
                    ok += 1
            except Exception as e:  # noqa: BLE001 — one symbol can't abort the rest
                errors += 1
                log.warning(f"[regime] {sym} failed: {type(e).__name__}: {e}")
        return {"symbols": len(symbols), "labeled": ok, "no_data": no_data, "errors": errors}

    await _guarded(summary, "watchlist", _run, timeout=TIMEOUT_COMPUTE)
    summary.finish()
    return summary


async def stage_signals(*, timeframe: str = "1d") -> StageSummary:
    """Generate + persist a signal per watchlist asset (if FEATURE_ML_SIGNALS).

    Reuses ``pfip.signals.runner.run_for_watchlist``. Respects the
    ``FEATURE_ML_SIGNALS`` kill-switch — signals stay OFF until the operator has
    enough OHLCV history for the walk-forward trainer to be trustworthy.
    """
    summary = StageSummary(name="signals")

    from pfip.core.config import get_settings

    if not get_settings().feature_ml_signals:
        summary.skipped = True
        summary.record("watchlist", "skipped: FEATURE_ML_SIGNALS=false")
        log.warning("[signals] skipped: FEATURE_ML_SIGNALS is off")
        summary.finish()
        return summary

    async def _run() -> dict[str, Any]:
        from collections import Counter

        from pfip.signals.runner import run_for_watchlist

        factory = get_sessionmaker()
        async with factory() as s:
            results = await run_for_watchlist(s, timeframe=timeframe)
        by_dir = Counter(r.direction.value for r in results)
        return {
            "symbols": len(results),
            "ok": sum(1 for r in results if r.status == "ok"),
            "by_direction": dict(by_dir),
        }

    await _guarded(summary, "watchlist", _run, timeout=TIMEOUT_COMPUTE)
    summary.finish()
    return summary


# ---------------------------------------------------------------------------
# SHADOW (paper-trading) stage
# ---------------------------------------------------------------------------


async def stage_shadow() -> StageSummary:
    """Paper-trade today's signals through the shadow portfolio.

    Reads today's high-confidence signals, applies them under the shadow risk
    rules (max 10%/position, correlation guard, 2 new/day), marks-to-market, and
    records shadow-vs-actual metrics — a forward paper-trading track record that
    accrues daily. Respects ``FEATURE_SHADOW_PORTFOLIO``; a no-op when signals
    were skipped (nothing to act on).
    """
    summary = StageSummary(name="shadow")
    from pfip.core.config import get_settings

    if not get_settings().feature_shadow_portfolio:
        summary.skipped = True
        summary.record("shadow", "skipped: FEATURE_SHADOW_PORTFOLIO=false")
        summary.finish()
        return summary

    async def _run() -> dict[str, Any]:
        from pfip.shadow.runner import run_daily

        factory = get_sessionmaker()
        async with factory() as s:
            res = await run_daily(s)
        return res.headline()

    await _guarded(summary, "shadow", _run, timeout=TIMEOUT_COMPUTE)
    summary.finish()
    return summary


# ---------------------------------------------------------------------------
# RETENTION stage
# ---------------------------------------------------------------------------


async def stage_retention(*, features_days: int = 0) -> StageSummary:
    """News hygiene + (optional, off by default) feature pruning.

    * **Feature pruning is DISABLED by default** (``features_days=0``). We
      deliberately keep all historical ``features`` — back data is never deleted.
      The DB sits well under the Neon free-tier ceiling (~74 MB of 512 MB), so
      there's no need to drop history; ML training wants the full feature record.
      To re-enable bounded pruning, pass a positive ``features_days`` (or set the
      ``PFIP_FEATURES_RETENTION_DAYS`` env var) — e.g. if the DB ever nears the
      free-tier limit.
    * Always runs the news age/relevance prune (``prune_old`` +
      ``prune_irrelevant``) — that's transient noise, not historical market data.
    """
    import os

    summary = StageSummary(name="retention")

    env_days = int(os.environ.get("PFIP_FEATURES_RETENTION_DAYS", "0") or "0")
    effective_days = features_days or env_days

    async def _prune_features() -> int:
        factory = get_sessionmaker()
        async with factory() as s:
            r = await s.execute(
                text("DELETE FROM features " "WHERE time < now() - (:d || ' days')::interval"),
                {"d": int(effective_days)},
            )
            await s.commit()
            return r.rowcount or 0

    if effective_days > 0:
        await _guarded(summary, "features_pruned", _prune_features, timeout=120.0)
    else:
        summary.record("features_pruned", "disabled (keep all history)")

    async def _prune_news() -> dict[str, int]:
        from pfip.ingest.news._pipeline import prune_irrelevant, prune_old

        factory = get_sessionmaker()
        async with factory() as s:
            old = await prune_old(s)
            irrelevant = await prune_irrelevant(s)
            return {"pruned_old": old, "pruned_irrelevant": irrelevant}

    await _guarded(summary, "news_pruned", _prune_news, timeout=120.0)

    summary.finish()
    return summary


# ---------------------------------------------------------------------------
# EVENTS (catalyst detection) stage
# ---------------------------------------------------------------------------


async def stage_events() -> StageSummary:
    """Extract typed catalysts from recent (entity-linked) news into the events
    table, and fire a CATALYST alert for fresh high-materiality events."""
    summary = StageSummary(name="events")

    async def _run() -> dict[str, Any]:
        from pfip.events.extractor import extract_events

        factory = get_sessionmaker()
        async with factory() as s:
            res = await extract_events(s, days=7)
        # Best-effort alert when this run surfaced material new catalysts.
        if res.get("events", 0) > 0:
            try:
                from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

                await send_alert(
                    AlertKind.CATALYST,
                    AlertSeverity.INFO,
                    title_override="New catalysts detected",
                    body_override=f"{res['events']} new market event(s) from today's news. See the Events page.",
                    context=res,
                )
            except Exception as exc:  # noqa: BLE001
                log.debug(f"catalyst alert skipped: {type(exc).__name__}")
        return res

    await _guarded(summary, "events", _run, timeout=TIMEOUT_COMPUTE)
    summary.finish()
    return summary


# ---------------------------------------------------------------------------
# Freshness SLA check (data observability)
# ---------------------------------------------------------------------------

# Max acceptable age (calendar days) of the freshest bar per asset class before
# we alert. Generous enough to absorb weekends/holidays; trips on real staleness.
_FRESHNESS_SLA_DAYS = {"crypto": 2.0, "india_equity": 5.0, "us_equity": 5.0}


def _asset_class(symbol: str) -> str | None:
    """Coarse asset class from a symbol, for freshness bucketing."""
    s = symbol.upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        return "india_equity"
    if "-USD" in s or "/USD" in s or s.endswith("USDT") or "-USDT" in s:
        return "crypto"
    if s.isalpha() and 1 <= len(s) <= 5:
        return "us_equity"
    return None


async def check_data_freshness() -> dict[str, Any]:
    """Alert if the freshest OHLCV bar per asset class is older than its SLA.

    Turns silent source staleness (the kind a green pipeline run hides) into a
    visible WARN alert + log line. Best-effort; never raises.
    """
    from sqlalchemy import func, select

    from pfip.models.ohlcv import OHLCVRow

    now = datetime.now(tz=timezone.utc)
    factory = get_sessionmaker()
    try:
        async with factory() as s:
            rows = (
                await s.execute(
                    select(OHLCVRow.symbol, func.max(OHLCVRow.time)).group_by(OHLCVRow.symbol)
                )
            ).all()
    except Exception as e:  # noqa: BLE001
        log.warning(f"freshness check skipped: {type(e).__name__}: {e}")
        return {"checked": 0, "stale": {}}

    per_class: dict[str, float] = {}
    for sym, ts in rows:
        cls = _asset_class(str(sym))
        if not cls or ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_d = (now - ts).total_seconds() / 86400.0
        per_class[cls] = min(per_class.get(cls, age_d), age_d)  # freshest in class

    stale = {c: round(a, 1) for c, a in per_class.items() if a > _FRESHNESS_SLA_DAYS.get(c, 5.0)}
    if stale:
        lines = ", ".join(
            f"{c}: {a}d old (SLA {_FRESHNESS_SLA_DAYS[c]}d)" for c, a in stale.items()
        )
        log.warning(f"[freshness] STALE data: {lines}")
        try:
            from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

            await send_alert(
                AlertKind.INGEST_FAILURE,
                AlertSeverity.WARN,
                title_override="Stale market data",
                body_override=f"Newest bars exceed freshness SLA — {lines}. Check /ops/sources.",
                context={"stale": stale},
            )
        except Exception as e:  # noqa: BLE001
            log.warning(f"freshness alert failed: {type(e).__name__}: {e}")
    else:
        log.info(f"[freshness] all classes within SLA: {per_class}")
    return {
        "checked": len(rows),
        "stale": stale,
        "per_class": {c: round(a, 1) for c, a in per_class.items()},
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_pipeline(
    stages: Iterable[str] = ALL_STAGES,
    *,
    timeframe: str = "1d",
    ingest_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the requested stages in order; return a structured summary.

    Stages always execute in canonical order (ingest → features → regime →
    signals → retention) regardless of the order given, because later stages
    consume earlier stages' output.
    """
    requested = [s for s in ALL_STAGES if s in set(stages)]
    log.info(f"daily pipeline starting: stages={requested}")
    started = time.monotonic()
    results: dict[str, Any] = {}

    if "ingest" in requested:
        summ = await stage_ingest(**(ingest_kwargs or {}))
        results["ingest"] = summ.as_dict()
    if "features" in requested:
        summ = await stage_features(timeframe=timeframe)
        results["features"] = summ.as_dict()
    if "regime" in requested:
        summ = await stage_regime(timeframe=timeframe)
        results["regime"] = summ.as_dict()
    if "signals" in requested:
        summ = await stage_signals(timeframe=timeframe)
        results["signals"] = summ.as_dict()
    if "events" in requested:
        summ = await stage_events()
        results["events"] = summ.as_dict()
    if "shadow" in requested:
        summ = await stage_shadow()
        results["shadow"] = summ.as_dict()
    if "retention" in requested:
        summ = await stage_retention()
        results["retention"] = summ.as_dict()

    # Always run the freshness SLA check at the end (independent of stages) so
    # silent source staleness surfaces as an alert rather than going unnoticed.
    results["freshness"] = await check_data_freshness()

    summary = {
        "stages_run": requested,
        "elapsed_s": round(time.monotonic() - started, 1),
        "results": results,
    }
    log.info("daily pipeline summary:\n" + json.dumps(summary, indent=2, default=str))
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the PFIP daily pipeline against DATABASE_URL (no Prefect/Docker).",
    )
    p.add_argument(
        "--stages",
        default=",".join(ALL_STAGES),
        help=("Comma-separated stages to run. " f"Choices: {','.join(ALL_STAGES)}. Default: all."),
    )
    p.add_argument("--timeframe", default="1d", help="OHLCV timeframe (default: 1d).")
    p.add_argument(
        "--no-news",
        action="store_true",
        help="Skip the news source within the ingest stage.",
    )
    p.add_argument(
        "--no-fundamentals",
        action="store_true",
        help="Skip fundamentals within the ingest stage.",
    )
    p.add_argument(
        "--fx-backfill",
        action="store_true",
        help="Also backfill FX history (otherwise just the latest fix).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    requested = [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = [s for s in requested if s not in ALL_STAGES]
    if unknown:
        raise SystemExit(f"Unknown stage(s): {unknown}. Valid stages: {', '.join(ALL_STAGES)}")
    ingest_kwargs: dict[str, Any] = {
        "include_news": not args.no_news,
        "include_fundamentals": not args.no_fundamentals,
        "fx_backfill": args.fx_backfill,
    }
    return asyncio.run(
        run_pipeline(
            stages=requested,
            timeframe=args.timeframe,
            ingest_kwargs=ingest_kwargs,
        )
    )


if __name__ == "__main__":
    main()
