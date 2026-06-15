"""Feature orchestration: per watchlist asset, compute the full bundle and write it.

For each ``(symbol, source, timeframe)`` we:

1. Load OHLCV → compute :func:`compute_features` (technicals).
2. For every bar build a fundamentals / on-chain / derivatives / macro /
   cross-asset snapshot **point-in-time** (i.e. we only use rows whose
   ``as_of_date`` or ``time`` <= the bar's timestamp).
3. Upsert the merged row into the ``features`` table — canonical 5 features
   into typed columns, everything else into the ``extras`` JSONB.

The runner is safe to call multiple times: the upsert is idempotent via the
table's composite primary key.

This is the function the Prefect flow ``compute_features_daily`` invokes; it's
also re-used by the API layer for ad-hoc feature recomputation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import select, text

from pfip.db.sources import resolve_ohlcv_source
from pfip.features.cross_asset import (
    CROSS_ASSET_FEATURE_COLS,
    derive_from_panel as derive_cross_asset,
    load_cross_asset_panel,
)
from pfip.features.derivatives import (
    DERIVATIVES_FEATURE_COLS,
    derive_from_history as derive_derivatives,
    load_derivatives_history,
)
from pfip.features.fundamentals import (
    FUNDAMENTAL_FEATURE_COLS,
    load_pit_fundamentals,
)
from pfip.features.macro import (
    MACRO_FEATURE_COLS,
    derive_from_panel as derive_macro,
    load_macro_closes,
)
from pfip.features.on_chain import (
    ON_CHAIN_FEATURE_COLS,
    derive_from_history as derive_on_chain,
    load_on_chain_history,
)
from pfip.features.technicals import compute_features

log = logging.getLogger(__name__)


ALL_EXTRA_COLS: tuple[str, ...] = (
    *FUNDAMENTAL_FEATURE_COLS,
    *ON_CHAIN_FEATURE_COLS,
    *DERIVATIVES_FEATURE_COLS,
    *MACRO_FEATURE_COLS,
    *CROSS_ASSET_FEATURE_COLS,
)


def _is_crypto(symbol: str) -> bool:
    s = symbol.upper()
    return "/" in s or s.endswith("USD") or s.endswith("USDT") or s.endswith("USDC")


def _is_equity(symbol: str) -> bool:
    s = symbol
    return s.endswith(".NS") or s.endswith(".BO") or (s.isupper() and 2 <= len(s) <= 5)


@dataclass
class FeatureRunRequest:
    """A single feature-pipeline request for one (symbol, source, timeframe)."""

    symbol: str
    source: str = "coinbase"
    timeframe: str = "1d"
    market: str = "crypto"  # crypto | us | india | fx
    write_extras: bool = True


@dataclass
class FeatureRunResult:
    symbol: str
    source: str
    timeframe: str
    rows_written: int
    rows_read: int
    extras_computed: bool


async def _load_ohlcv_df(session, symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    try:
        from pfip.models.ohlcv import OHLCVRow

        stmt = (
            select(OHLCVRow)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.source == source,
                OHLCVRow.timeframe == timeframe,
            )
            .order_by(OHLCVRow.time.asc())
        )
        res = await session.execute(stmt)
        rows = res.scalars().all()
    except Exception as exc:
        log.warning("ohlcv load failed for %s: %s", symbol, exc)
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "time": r.time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ]
    ).set_index("time")


_UPSERT_SQL = text("""
    INSERT INTO features (
        time, symbol, source, timeframe,
        rsi_14, macd, macd_signal, macd_hist, atr_14, return_7d, volatility_30d, extras
    ) VALUES (
        :time, :symbol, :source, :timeframe,
        :rsi_14, :macd, :macd_signal, :macd_hist, :atr_14, :return_7d, :volatility_30d, :extras
    )
    ON CONFLICT (time, symbol, source, timeframe) DO UPDATE SET
        rsi_14 = EXCLUDED.rsi_14,
        macd = EXCLUDED.macd,
        macd_signal = EXCLUDED.macd_signal,
        macd_hist = EXCLUDED.macd_hist,
        atr_14 = EXCLUDED.atr_14,
        return_7d = EXCLUDED.return_7d,
        volatility_30d = EXCLUDED.volatility_30d,
        extras = EXCLUDED.extras
    """)


def _none_if_nan(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def _json_safe(d: dict) -> dict:
    """Drop keys whose value is None or a non-finite float.

    Postgres JSONB rejects the ``NaN``/``Infinity`` tokens that ``json.dumps``
    emits by default, which would abort the whole feature upsert transaction
    (the extras blob often carries NaNs for missing on-chain/derivative data).
    """
    import math

    out: dict = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, float) and not math.isfinite(v):
            continue
        out[k] = v
    return out


async def compute_and_persist(
    session,
    request: FeatureRunRequest,
) -> FeatureRunResult:
    """Compute the full feature set for one (symbol, source, timeframe) and upsert."""
    df = await _load_ohlcv_df(session, request.symbol, request.source, request.timeframe)
    if df.empty:
        return FeatureRunResult(
            symbol=request.symbol,
            source=request.source,
            timeframe=request.timeframe,
            rows_written=0,
            rows_read=0,
            extras_computed=False,
        )

    technicals = compute_features(df)

    # We only build the *latest* extras snapshot once and stamp it onto the
    # most-recent bar's extras blob. Historical bars get an empty extras blob
    # since the upstream tables (fundamentals, on-chain, derivatives) are
    # point-in-time aware but we don't (yet) want to re-query them per bar.
    last_ts = df.index[-1]
    as_of_dt = (
        last_ts.to_pydatetime()
        if hasattr(last_ts, "to_pydatetime")
        else datetime.now(tz=timezone.utc)
    )
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    as_of_d = as_of_dt.date()

    extras_blob: dict[str, float | None] = {}
    extras_computed = False

    if request.write_extras:
        try:
            if _is_equity(request.symbol):
                fund = await load_pit_fundamentals(session, request.symbol, as_of_d)
                extras_blob.update(fund.as_dict())
                extras_computed = True

            if _is_crypto(request.symbol):
                on_chain_hist = await load_on_chain_history(session, request.symbol, as_of_dt)
                oc = derive_on_chain(on_chain_hist, request.symbol, as_of_dt)
                extras_blob.update(oc.as_dict())

                deriv_hist = await load_derivatives_history(session, request.symbol, as_of_dt)
                d = derive_derivatives(deriv_hist, request.symbol, as_of_dt)
                extras_blob.update(d.as_dict())
                extras_computed = True

            macro_panel = await load_macro_closes(session, as_of_dt)
            macro = derive_macro(macro_panel, as_of_dt)
            extras_blob.update(macro.as_dict())

            ca_panel = await load_cross_asset_panel(session, request.symbol, as_of_dt)
            ca = derive_cross_asset(ca_panel, request.symbol, as_of_dt)
            extras_blob.update(ca.as_dict())
            extras_computed = True
        except Exception as exc:  # pragma: no cover — defensive
            log.warning("extras computation failed for %s: %s", request.symbol, exc)

    written = 0
    for ts, row in technicals.iterrows():
        # Only attach extras to the latest bar to keep historical writes light.
        is_latest = ts == last_ts
        extras = extras_blob if (is_latest and request.write_extras) else {}
        # psycopg cannot adapt a pandas Timestamp — convert to a native datetime.
        ts_py = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        params = {
            "time": ts_py,
            "symbol": request.symbol,
            "source": request.source,
            "timeframe": request.timeframe,
            "rsi_14": _none_if_nan(row.get("rsi_14")),
            "macd": _none_if_nan(row.get("macd")),
            "macd_signal": _none_if_nan(row.get("macd_signal")),
            "macd_hist": _none_if_nan(row.get("macd_hist")),
            "atr_14": _none_if_nan(row.get("atr_14")),
            "return_7d": _none_if_nan(row.get("return_7d")),
            "volatility_30d": _none_if_nan(row.get("volatility_30d")),
            "extras": json.dumps(_json_safe(extras)),
        }
        await session.execute(_UPSERT_SQL, params)
        written += 1
    await session.commit()

    return FeatureRunResult(
        symbol=request.symbol,
        source=request.source,
        timeframe=request.timeframe,
        rows_written=written,
        rows_read=len(df),
        extras_computed=extras_computed,
    )


async def run_for_watchlist(
    session,
    timeframe: str = "1d",
) -> list[FeatureRunResult]:
    """For every row in ``watchlist``, run the full feature pipeline.

    ``source`` is picked from a small heuristic table (crypto -> coinbase,
    Indian equities -> jugaad, US tickers -> yfinance, FX -> frankfurter).
    """
    try:
        from pfip.models.watchlist import WatchlistRow

        res = await session.execute(select(WatchlistRow))
        rows = list(res.scalars().all())
    except Exception as exc:  # pragma: no cover
        log.warning("watchlist load failed: %s", exc)
        return []

    # Use a fresh session per symbol. A single shared session reused across the
    # whole watchlist breaks under ``pool_pre_ping`` when a symbol returns early
    # with no data (the pooled connection gets pinged across the event-loop /
    # greenlet boundary on the next iteration -> ``MissingGreenlet``). A session
    # per symbol matches the working pattern used by the regime flow and keeps
    # one bad/empty symbol from aborting the rest.
    from pfip.db.session import get_sessionmaker

    factory = get_sessionmaker()
    out: list[FeatureRunResult] = []
    for r in rows:
        symbol = str(r.symbol)
        market_kind = _infer_market_kind(symbol)
        try:
            async with factory() as sym_session:
                # Use the source that ACTUALLY ingested this symbol (the heuristic
                # mislabels US equities as 'yfinance' when data is under 'tiingo',
                # so the scheduled run read 0 rows). Fall back to the heuristic
                # only when the symbol has no OHLCV rows yet.
                source = await resolve_ohlcv_source(
                    sym_session, symbol, timeframe
                ) or _infer_source(symbol, market_kind)
                req = FeatureRunRequest(
                    symbol=symbol,
                    source=source,
                    timeframe=timeframe,
                    market=market_kind,
                )
                result = await compute_and_persist(sym_session, req)
        except Exception as exc:  # pragma: no cover
            log.warning("feature compute failed for %s: %s", symbol, exc)
            continue
        out.append(result)
    return out


def _infer_market_kind(symbol: str) -> str:
    if _is_crypto(symbol):
        return "crypto"
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return "india"
    if symbol.endswith("=X") or symbol in ("USDINR", "EURUSD", "GBPUSD"):
        return "fx"
    return "us"


def _infer_source(symbol: str, market_kind: str) -> str:
    if market_kind == "crypto":
        return "coinbase"
    if market_kind == "india":
        return "jugaad"
    if market_kind == "fx":
        return "frankfurter"
    return "yfinance"
