"""Backtest router — read-only access to persisted walk-forward backtest runs.

Walk-forward + CPCV backtests are produced out-of-band by the
``backtest-walk-forward`` Prefect flow (see
:mod:`pfip.prefect.flows.backtest_walk_forward`) and persisted to the
``backtest_runs`` table. This router just surfaces them for the dashboard:

    GET /backtest/runs           list recent runs (newest first, bounded)
    GET /backtest/runs/{id}      one run's full detail incl. per-fold metrics

Both routes are auth-gated like every other PFIP router. The ``metrics`` and
``params`` columns are JSONB blobs produced by the engine; we pass them through
untouched so the frontend sees exactly what the engine computed (Sharpe,
Sortino, max DD, Calmar, hit rate, CPCV summary, benchmarks, Monte-Carlo, the
shuffle/lookahead test, and per-fold metrics when present).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from pfip.api.deps import CurrentUser, DbSession
from pfip.models.backtest import BacktestRunRow

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRunRequest(BaseModel):
    """Body for ``POST /backtest/run``."""

    market: str  # symbol to backtest, e.g. "BTC-USDT", "RELIANCE.NS", "SPY"
    strategy: str = "ma_50_200"  # one of AVAILABLE_STRATEGIES
    days: int = 365 * 3


@router.get("/strategies")
async def strategies(_user: CurrentUser) -> dict[str, Any]:
    """List the strategies a user can backtest (populates the run form)."""
    from pfip.backtest.service import AVAILABLE_STRATEGIES, DEFAULT_STRATEGY

    return {"strategies": list(AVAILABLE_STRATEGIES), "default": DEFAULT_STRATEGY}


@router.post("/run")
async def run_backtest(
    body: BacktestRunRequest, db: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    """Run + persist a walk-forward backtest for one symbol, then return its
    headline metrics. The persisted run is then readable via ``GET /runs``.

    Rigorous by construction: out-of-sample walk-forward + CPCV + embargo +
    a lookahead guard (``lookahead_ok``). Returns 422 on an unknown strategy
    and a structured ``error`` (200) when a symbol lacks enough history.
    """
    from pfip.backtest.service import AVAILABLE_STRATEGIES, run_and_persist_backtest

    if body.strategy not in AVAILABLE_STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"strategy must be one of {', '.join(AVAILABLE_STRATEGIES)}",
        )
    if body.days < 180:
        raise HTTPException(status_code=422, detail="days must be >= 180")
    try:
        return await run_and_persist_backtest(
            db, market=body.market.strip(), strategy=body.strategy, days=body.days
        )
    except Exception as exc:  # noqa: BLE001 — never 500 the page; return a clean error
        import logging

        logging.getLogger(__name__).warning(
            f"backtest run failed for {body.market}/{body.strategy}: {type(exc).__name__}: {exc}"
        )
        return {
            "error": f"backtest failed ({type(exc).__name__})",
            "market": body.market,
            "strategy": body.strategy,
        }


def _summary(row: BacktestRunRow) -> dict[str, Any]:
    """Flatten the headline metrics out of the ``metrics`` blob for list views.

    The persisted ``metrics`` shape is::

        {"walkforward": {sharpe, sortino, max_drawdown, calmar, hit_rate,
                         n_trades, cagr, total_return, mc_sharpe_5th,
                         cpcv_mean_sharpe, n_folds, ...},
         "benchmarks": {...}, "monte_carlo": {...}, "shuffle_test": {...}}

    For the list endpoint we hoist the walk-forward headline numbers to the top
    level so the table can render without reaching into nested objects. The
    detail endpoint returns the whole blob untouched.
    """
    metrics = row.metrics or {}
    wf = metrics.get("walkforward") or {}
    return {
        "id": str(row.id),
        "market": row.market,
        "strategy": row.strategy,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "lookahead_ok": row.lookahead_ok,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        # Headline walk-forward metrics (floats; null when the run was empty).
        "sharpe": wf.get("sharpe"),
        "sortino": wf.get("sortino"),
        "max_drawdown": wf.get("max_drawdown"),
        "calmar": wf.get("calmar"),
        "hit_rate": wf.get("hit_rate"),
        "cagr": wf.get("cagr"),
        "total_return": wf.get("total_return"),
        "n_trades": wf.get("n_trades"),
        "n_folds": wf.get("n_folds"),
        "cpcv_mean_sharpe": wf.get("cpcv_mean_sharpe"),
        "mc_sharpe_5th": wf.get("mc_sharpe_5th"),
    }


@router.get("/runs")
async def list_runs(
    db: DbSession,
    _user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    market: str | None = Query(None, description="Filter by market/symbol label"),
    strategy: str | None = Query(None, description="Filter by strategy name"),
) -> dict[str, Any]:
    """List recent backtest runs, newest first.

    Returns a flat list of headline summaries (one row per run). Use
    ``GET /backtest/runs/{id}`` for the full metrics blob of a single run.
    """
    stmt = select(BacktestRunRow).order_by(desc(BacktestRunRow.created_at)).limit(limit)
    if market:
        stmt = stmt.where(BacktestRunRow.market == market)
    if strategy:
        stmt = stmt.where(BacktestRunRow.strategy == strategy)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {"runs": [_summary(r) for r in rows], "count": len(rows)}


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Return one backtest run with its full metrics + params blobs.

    Includes per-fold metrics (under ``metrics.walkforward.fold_metrics``),
    the CPCV summary, benchmark comparison, Monte-Carlo percentiles, and the
    shuffle/lookahead test result — exactly as the engine produced them.
    """
    row = await db.get(BacktestRunRow, run_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
    out = _summary(row)
    out["metrics"] = row.metrics or {}
    out["params"] = row.params or {}
    return out
