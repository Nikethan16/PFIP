"""Manual walk-forward backtest flow.

Not on a schedule — this is the ad-hoc "run me a backtest for X" entry point
operators trigger via Prefect UI or CLI.

    python -m pfip.prefect.flows.backtest_walk_forward --symbol BTC/USD

Pulls OHLCV from the DB, picks a strategy (default: 50/200 MA crossover from
:mod:`pfip.backtest.benchmarks`), runs the full WF + CPCV + Monte Carlo +
shuffle-test pass, and emits a row into ``backtest_runs``. Tearsheet HTML is
written to /tmp by default.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import select, text

from pfip.backtest.benchmarks import BENCHMARKS, compare_to_benchmarks
from pfip.backtest.monte_carlo import block_bootstrap
from pfip.backtest.shuffle_test import run_shuffle_test
from pfip.backtest.tearsheet import generate_tearsheet
from pfip.backtest.walk_forward import WalkForwardResult, run_walk_forward
from pfip.db.session import get_sessionmaker

log = logging.getLogger(__name__)


@task(name="load-prices-for-backtest")
async def _load_prices(symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    factory = get_sessionmaker()
    async with factory() as session:
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


@task(name="persist-backtest-run")
async def _persist_run(
    *,
    market: str,
    strategy: str,
    start_date: datetime,
    end_date: datetime,
    metrics: dict[str, Any],
    params: dict[str, Any],
    lookahead_ok: bool,
) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO backtest_runs (
                    market, strategy, start_date, end_date, metrics, params, lookahead_ok
                ) VALUES (
                    :market, :strategy, :start_date, :end_date,
                    CAST(:metrics AS JSONB), CAST(:params AS JSONB), :lookahead_ok
                )
                """
            ),
            {
                "market": market,
                "strategy": strategy,
                "start_date": start_date.date(),
                "end_date": end_date.date(),
                "metrics": json.dumps(metrics),
                "params": json.dumps(params),
                "lookahead_ok": lookahead_ok,
            },
        )
        await session.commit()


@flow(name="backtest-walk-forward", log_prints=True)
async def backtest_walk_forward(
    *,
    symbol: str = "BTC/USD",
    source: str = "coinbase",
    timeframe: str = "1d",
    strategy_name: str = "ma_50_200",
    market_kind: str = "crypto",
    train_window: int = 252,
    step: int = 21,
    test_window: int = 21,
    embargo: int = 5,
    horizon: int = 3,
    tearsheet_dir: str = "/tmp/pfip_tearsheets",
) -> dict[str, Any]:
    """Run a manual walk-forward backtest end-to-end."""
    runtime_log = get_run_logger()
    df = await _load_prices(symbol, source, timeframe)
    if df.empty:
        runtime_log.warning("no OHLCV for %s/%s", symbol, source)
        return {"status": "no-data"}

    strategy = BENCHMARKS.get(strategy_name)
    if strategy is None:
        runtime_log.warning("unknown strategy '%s'; falling back to buy_hold", strategy_name)
        strategy = BENCHMARKS["buy_hold"]
        strategy_name = "buy_hold"

    wf: WalkForwardResult = run_walk_forward(
        market=symbol,
        df=df,
        strategy=strategy,
        horizon=horizon,
        train_window=train_window,
        step=step,
        test_window=test_window,
        embargo=embargo,
        market_kind=market_kind,
    )
    runtime_log.info(
        "walk-forward: %d folds, lookahead_ok=%s",
        len(wf.fold_metrics),
        wf.lookahead_ok,
    )

    bench = (
        compare_to_benchmarks(
            wf.aggregate.returns if wf.aggregate is not None else pd.Series(dtype=float),
            df,
            market_kind=market_kind,
        )
        if wf.aggregate is not None
        else {}
    )

    mc = (
        block_bootstrap(wf.aggregate.trades, n_sims=500)
        if wf.aggregate is not None and not wf.aggregate.trades.empty
        else None
    )

    shuf = run_shuffle_test(strategy, df, market_kind=market_kind, n_shuffles=10)

    # Tearsheet
    try:
        Path(tearsheet_dir).mkdir(parents=True, exist_ok=True)
        ts_name = (
            f"{symbol.replace('/', '_')}-{strategy_name}-"
            f"{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S')}.html"
        )
        ts_path = Path(tearsheet_dir) / ts_name
        if wf.aggregate is not None:
            generate_tearsheet(
                wf.aggregate.returns,
                output_path=ts_path,
                title=f"PFIP {symbol} / {strategy_name}",
                metadata={"market": symbol, "strategy": strategy_name},
            )
            runtime_log.info("tearsheet written to %s", ts_path)
    except Exception as exc:  # pragma: no cover
        runtime_log.warning("tearsheet failed: %s", exc)

    metrics_payload: dict[str, Any] = {
        "walkforward": wf.summary(),
        "benchmarks": bench,
        "monte_carlo": mc.as_dict() if mc is not None else None,
        "shuffle_test": shuf.summary(),
    }

    try:
        await _persist_run(
            market=symbol,
            strategy=strategy_name,
            start_date=(
                df.index[0].to_pydatetime()
                if hasattr(df.index[0], "to_pydatetime")
                else datetime.now(tz=timezone.utc)
            ),
            end_date=(
                df.index[-1].to_pydatetime()
                if hasattr(df.index[-1], "to_pydatetime")
                else datetime.now(tz=timezone.utc)
            ),
            metrics=metrics_payload,
            params={
                "train_window": train_window,
                "step": step,
                "test_window": test_window,
                "embargo": embargo,
                "horizon": horizon,
            },
            lookahead_ok=bool(wf.lookahead_ok),
        )
    except Exception as exc:  # pragma: no cover
        runtime_log.warning("persist_run failed: %s", exc)

    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "metrics": metrics_payload,
    }


if __name__ == "__main__":
    asyncio.run(backtest_walk_forward())
