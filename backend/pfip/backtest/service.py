"""On-demand backtest runner + persistence (Phase 2 gap-fill).

The walk-forward engine (``run_walk_forward``) and the ``backtest_runs`` table
already existed, but nothing let a user actually *start* a run from the app — so
the Backtest page showed an empty list forever. This service is the missing
middle: load a symbol's OHLCV, run a named strategy through the rigorous
walk-forward + CPCV + lookahead engine, build an equity curve, and persist a
``BacktestRunRow`` the existing read endpoints already surface.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select

from pfip.backtest.vectorbt_engine import (
    _BENCHMARKS,
    _apply_strategy,
    benchmark_comparison,
    transaction_cost_bps,
)
from pfip.backtest.walk_forward import run_walk_forward
from pfip.db.sources import resolve_ohlcv_source
from pfip.models.backtest import BacktestRunRow

log = logging.getLogger(__name__)

# Strategies a user can pick. Keyed to the engine's built-in benchmark set so
# there's a single source of truth for what each name does.
AVAILABLE_STRATEGIES: tuple[str, ...] = tuple(_BENCHMARKS.keys())
DEFAULT_STRATEGY = "ma_50_200"


def _market_kind(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(("-USD", "-USDT", "/USD", "/USDT")) or s.endswith("USDT"):
        return "crypto"
    return "equity"


async def _load_ohlcv(session, symbol: str, days: int) -> pd.DataFrame:
    """Load a symbol's daily OHLCV as a close-bearing DataFrame (freshest source)."""
    from pfip.models.ohlcv import OHLCVRow

    source = await resolve_ohlcv_source(session, symbol, "1d")
    if not source:
        return pd.DataFrame()
    since = datetime.now(tz=UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                OHLCVRow.time,
                OHLCVRow.open,
                OHLCVRow.high,
                OHLCVRow.low,
                OHLCVRow.close,
                OHLCVRow.volume,
            )
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.source == source,
                OHLCVRow.timeframe == "1d",
                OHLCVRow.time >= since,
            )
            .order_by(OHLCVRow.time.asc())
        )
    ).all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "time": t,
                "open": float(o),
                "high": float(h),
                "low": float(low),
                "close": float(c),
                "volume": float(v),
            }
            for t, o, h, low, c, v in rows
        ]
    ).set_index("time")


def _equity_curve(
    df: pd.DataFrame, strategy, cost_bps: float, max_points: int = 300
) -> list[dict[str, Any]]:
    """Full-sample net-of-cost equity curve for the chart (₹1 → cumulative)."""
    try:
        net_ret, _ = _apply_strategy(df, strategy, cost_bps)
    except Exception:  # noqa: BLE001
        return []
    equity = (1.0 + net_ret.fillna(0.0)).cumprod()
    if equity.empty:
        return []
    # Ceil division so the curve is actually capped at ~max_points (floor
    # division left a 400-bar series un-thinned).
    step = max(1, (len(equity) + max_points - 1) // max_points)
    points = [
        {
            "date": (idx.date().isoformat() if hasattr(idx, "date") else str(idx)),
            "equity": round(float(val), 5),
        }
        for idx, val in list(equity.items())[::step]
    ]
    # Always keep the final point (the ending equity).
    last_idx, last_val = list(equity.items())[-1]
    if not points or points[-1]["date"] != (
        last_idx.date().isoformat() if hasattr(last_idx, "date") else str(last_idx)
    ):
        points.append(
            {
                "date": last_idx.date().isoformat() if hasattr(last_idx, "date") else str(last_idx),
                "equity": round(float(last_val), 5),
            }
        )
    return points


async def run_and_persist_backtest(
    session,
    *,
    market: str,
    strategy: str = DEFAULT_STRATEGY,
    days: int = 365 * 3,
) -> dict[str, Any]:
    """Run + persist a walk-forward backtest for ``market`` (a symbol).

    Returns a dict with the persisted run id + headline metrics, or an
    ``error`` key when there isn't enough data. Never raises on empty data.
    """
    if strategy not in _BENCHMARKS:
        return {"error": f"unknown strategy {strategy!r}", "available": list(AVAILABLE_STRATEGIES)}
    df = await _load_ohlcv(session, market, days)
    if df.empty or len(df) < 120:
        return {
            "error": "insufficient price history (need >=120 daily bars)",
            "market": market,
            "bars": int(len(df)),
        }

    strat_fn = _BENCHMARKS[strategy]
    market_kind = _market_kind(market)
    cost_bps = transaction_cost_bps(market_kind)

    result = run_walk_forward(market=market, df=df, strategy=strat_fn, market_kind=market_kind)
    wf = result.summary()
    metrics = {
        "walkforward": wf,
        "fold_metrics": [
            {
                "fold": f.fold,
                "sharpe": round(f.sharpe, 4),
                "max_drawdown": round(f.max_drawdown, 4),
                "hit_rate": round(f.hit_rate, 4),
                "n_trades": f.n_trades,
            }
            for f in result.fold_metrics
        ],
        "benchmarks": benchmark_comparison(pd.Series(dtype=float), df=df, market_kind=market_kind),
        "equity_curve": _equity_curve(df, strat_fn, cost_bps),
        "note": (
            "Headline metrics are out-of-sample (walk-forward + CPCV + embargo); "
            "the equity curve is the full-sample net-of-cost path for visualization."
        ),
    }

    start_date = df.index[0].date() if hasattr(df.index[0], "date") else datetime.now(tz=UTC).date()
    end_date = df.index[-1].date() if hasattr(df.index[-1], "date") else datetime.now(tz=UTC).date()
    row = BacktestRunRow(
        market=market,
        strategy=strategy,
        model_name="rule_strategy",
        model_version=strategy,
        start_date=start_date,
        end_date=end_date,
        metrics=metrics,
        params={
            "strategy": strategy,
            "market_kind": market_kind,
            "days": days,
            "cost_bps": cost_bps,
        },
        lookahead_ok=bool(result.lookahead_ok),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return {
        "id": str(row.id),
        "market": market,
        "strategy": strategy,
        "lookahead_ok": bool(result.lookahead_ok),
        "sharpe": wf.get("sharpe"),
        "max_drawdown": wf.get("max_drawdown"),
        "hit_rate": wf.get("hit_rate"),
        "total_return": wf.get("total_return"),
        "n_folds": len(result.fold_metrics),
        "equity_points": len(metrics["equity_curve"]),
    }


__all__ = ["run_and_persist_backtest", "AVAILABLE_STRATEGIES", "DEFAULT_STRATEGY"]
