"""Portfolio router — holdings CRUD + summary + CSV import + correlations.

Uses ``pfip.portfolio.service.PortfolioService`` for all DB operations so the
routes stay thin. Every structured response carries the tax/portfolio
advisory ``DISCLAIMER``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from pfip.api.deps import CurrentUser, DbSession
from pfip.brokers.csv_adapters import UnknownSchemaError
from pfip.brokers.csv_adapters.router import (
    list_supported,
    route_and_parse,
)
from pfip.core.contracts import Holding, PortfolioSummary
from pfip.models.holdings import HoldingRow
from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.portfolio.allocation import (
    StrategicTargets,
    rebalance_suggestions,
    suggestions_to_dict,
    tactical_adjust,
)
from pfip.portfolio.benchmark import run_benchmark
from pfip.portfolio.goals import project_goal, required_monthly_contribution
from pfip.portfolio.whatif import run_what_if
from pfip.portfolio.marking import build_marking, fetch_return_series
from pfip.portfolio.risk_manager import RiskManager
from pfip.portfolio.rollup import (
    asset_class_for,
    encode_tx_note,
    rebuild_holdings_from_tx,
)
from pfip.portfolio.service import (
    HoldingNotFoundError,
    HoldingValidationError,
    PortfolioService,
    trailing_sharpe,
)
from pfip.tax.indian_rules import DISCLAIMER

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CloseHoldingRequest(BaseModel):
    """Body for ``POST /portfolio/holdings/{id}/close``."""

    exit_price_inr: Decimal
    when: Optional[datetime] = None
    qty: Optional[Decimal] = None


class PreTradeRequest(BaseModel):
    """Body for ``POST /portfolio/pre-trade``."""

    symbol: str
    qty: Decimal
    price: Decimal
    portfolio_value_inr: Decimal
    stop_distance_pct: Optional[float] = None
    regime: Optional[str] = None
    signal_confidence: Optional[int] = None
    news_count_24h: Optional[int] = None
    event_calendar_conflict: bool = False
    positions_added_today: int = 0
    current_drawdown_pct: float = 0.0
    existing_symbols: list[str] = []


class RebalanceRequest(BaseModel):
    """Body for ``POST /portfolio/rebalance``."""

    strategic: dict[str, float]
    current_allocation: dict[str, float]  # bucket -> inr
    regime_per_market: dict[str, str] | None = None
    sentiment: float | None = None
    drift_threshold: float = 0.05


class GoalProjectRequest(BaseModel):
    """Body for ``POST /portfolio/goals/project``.

    All monetary values are INR. ``expected_annual_return`` / ``annual_volatility``
    are fractions (0.10 = 10%). When ``target_inr`` is given, the response also
    reports the probability of reaching it and the monthly contribution needed to
    hit it at the median.
    """

    current_corpus_inr: float
    monthly_contribution_inr: float = 0.0
    years: float
    expected_annual_return: float = 0.10
    annual_volatility: float = 0.15
    target_inr: float | None = None
    n_sims: int = 10_000


class WhatIfRequest(BaseModel):
    """Body for ``POST /portfolio/what-if``.

    ``mark_prices`` maps symbol → current INR price per unit (used to value the
    book before/after); missing symbols fall back to cost basis.
    """

    action: str  # BUY or SELL
    symbol: str
    qty: Decimal
    price: Decimal
    mark_prices: dict[str, Decimal] | None = None


# ---------------------------------------------------------------------------
# Holdings CRUD
# ---------------------------------------------------------------------------


@router.get("/holdings", response_model=list[Holding])
async def list_holdings(
    db: DbSession,
    _user: CurrentUser,
    category: str | None = Query(None),
    active: bool | None = Query(True),
) -> list[Holding]:
    """List all open (or closed) holdings, optionally filtered by category."""
    svc = PortfolioService(db)
    return await svc.list_holdings(category=category, active=active)


@router.post("/holdings", response_model=Holding, status_code=status.HTTP_201_CREATED)
async def add_holding(body: Holding, db: DbSession, _user: CurrentUser) -> Holding:
    """Add a manual holding. Records an opening BUY tx for audit."""
    svc = PortfolioService(db)
    try:
        return await svc.add_holding(body)
    except HoldingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/holdings/{holding_id}", response_model=Holding)
async def get_holding(holding_id: UUID, db: DbSession, _user: CurrentUser) -> Holding:
    svc = PortfolioService(db)
    h = await svc.get_holding(holding_id)
    if h is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    return h


@router.post("/holdings/{holding_id}/close")
async def close_holding(
    holding_id: UUID,
    body: CloseHoldingRequest,
    db: DbSession,
    _user: CurrentUser,
) -> dict:
    """Close a holding fully or partially. Triggers mandatory post-mortem flag."""
    svc = PortfolioService(db)
    try:
        result = await svc.close_holding(
            holding_id,
            body.exit_price_inr,
            body.when,
            qty=body.qty,
        )
    except HoldingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HoldingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Contract: closed holding returns post_mortem_required=True
    # Serialise the Holding cleanly
    return {
        "holding": result["holding"].model_dump(mode="json"),
        "sell_tx": result["sell_tx"],
        "post_mortem_required": True,
        "journal_entry_id": result["journal_entry_id"],
        "disclaimer": DISCLAIMER,
    }


@router.post("/holdings/rebuild")
async def rebuild_holdings(
    db: DbSession,
    _user: CurrentUser,
    asset_class: str | None = Query(
        None,
        description="Optional filter: only rebuild this asset class "
        "(equity / us_stock / vda / equity_mf / debt_mf / gold).",
    ),
) -> dict:
    """Materialize ``holdings`` from the ``portfolio_tx`` ledger.

    Groups import-originated ledger rows by position, computes net quantity and
    weighted-average cost basis, and UPSERTs the still-open positions into
    ``holdings``. Idempotent — re-running recomputes from the ledger and replaces
    the rollup-owned rows (manual holdings are never touched). This is what makes
    a broker-CSV import show up in the portfolio.

    Response::

        {"rebuilt": int, "holdings": [Holding, ...], "disclaimer": str}
    """
    holdings = await rebuild_holdings_from_tx(db, asset_class=asset_class)
    return {
        "rebuilt": len(holdings),
        "holdings": [h.model_dump(mode="json") for h in holdings],
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Summary + analytics
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=PortfolioSummary)
async def summary(db: DbSession, _user: CurrentUser) -> PortfolioSummary:
    """Aggregate portfolio summary (contracts.PortfolioSummary).

    Marked to market using the latest OHLCV close per symbol (USD assets
    converted via the ``fx_rates`` table). Holdings we can't confidently price
    fall back to cost basis — see ``GET /portfolio/marking`` for coverage.
    """
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    marking = await build_marking(db, holdings)
    # NAV history (cumulative-net-flow proxy from the ledger) drives the
    # peak-to-current drawdown. Empty ⇒ drawdown stays 0.0.
    nav_history = await svc.nav_history()
    return await svc.portfolio_summary(mark_prices=marking.mark_prices, nav_history=nav_history)


@router.get("/marking")
async def marking(db: DbSession, _user: CurrentUser) -> dict:
    """Mark-to-market coverage: which holdings are live-priced vs cost-basis.

    Lets the UI show a freshness/coverage indicator and explains why any
    holding fell back to cost basis (no_price / unknown_currency / no_fx_rate).
    """
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    result = await build_marking(db, holdings)
    return {
        "as_of": result.as_of.isoformat() if result.as_of else None,
        "usdinr": str(result.usdinr) if result.usdinr is not None else None,
        "marked": result.marked,
        "unmarked": result.unmarked,
        "mark_prices_inr": {k: str(v) for k, v in result.mark_prices.items()},
        "coverage": {
            "marked": len(result.marked),
            "total": len(result.marked) + len(result.unmarked),
        },
        "disclaimer": DISCLAIMER,
    }


@router.get("/exposure")
async def exposure(db: DbSession, _user: CurrentUser) -> dict:
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    mark_prices = (await build_marking(db, holdings)).mark_prices
    exp = await svc.exposure_by_category(mark_prices=mark_prices)
    total = sum(exp.values(), Decimal("0"))
    return {
        "total_inr": str(total),
        "exposure_inr": {k: str(v) for k, v in exp.items()},
        "exposure_pct": {k: (float(v / total) if total else 0.0) for k, v in exp.items()},
        "disclaimer": DISCLAIMER,
    }


@router.get("/concentration")
async def concentration(db: DbSession, _user: CurrentUser) -> dict:
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    mark_prices = (await build_marking(db, holdings)).mark_prices
    result = await svc.concentration_score(mark_prices=mark_prices)
    result["disclaimer"] = DISCLAIMER
    return result


@router.get("/correlations")
async def correlations(
    db: DbSession,
    _user: CurrentUser,
    window_days: int = Query(90, ge=10, le=365),
) -> dict:
    """Return the correlation matrix across open holdings.

    Return series are daily log-returns derived from each symbol's own OHLCV
    history over ``window_days`` — currency-agnostic, so no FX is involved.
    Symbols with fewer than 2 bars in the window are dropped; the matrix is
    empty only if no holding has enough history.
    """
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    symbols = sorted({h.symbol for h in holdings if h.symbol})
    series = await fetch_return_series(db, symbols, window_days)
    matrix_map = await svc.correlation_matrix(return_series=series, window_days=window_days)
    # The frontend contract (CorrelationMatrixSchema) expects `symbols: string[]`
    # plus `matrix: number[][]` aligned to that order — not a nested dict.
    ordered = list(matrix_map.keys())
    matrix_2d = [[matrix_map[r].get(c, 0.0) for c in ordered] for r in ordered]
    note = (
        "Insufficient price history for any holding in the window."
        if not matrix_2d
        else f"Pearson correlation of daily log-returns over {window_days}d."
    )
    return {
        "window_days": window_days,
        "symbols": ordered,
        "matrix": matrix_2d,
        "note": note,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# VaR / risk panel (dashboard HeroKpis)
# ---------------------------------------------------------------------------


@router.get("/var")
async def var_panel(
    db: DbSession,
    _user: CurrentUser,
    window_days: int = Query(90, ge=10, le=365),
    positions_added_today: int = Query(0, ge=0),
) -> dict:
    """Historical-VaR + risk panel for the dashboard HeroKpis.

    Composes existing building blocks:
      * ``PortfolioService.historical_var`` over a portfolio-level daily
        log-return series (value-weighted blend of each holding's own OHLCV
        returns). With fewer than 30 returns we return a graceful zero shape
        (no fabricated numbers).
      * ``concentration_score`` HHI.
      * ``RiskManager.daily_new_positions_remaining``.
      * ``nav_history`` for the drawdown series + day change.

    Every field is a plain JSON number to match the frontend ``VarPanelSchema``.
    """
    svc = PortfolioService(db)
    holdings = await svc.list_holdings(active=True)
    marking = await build_marking(db, holdings)
    mark_prices = marking.mark_prices

    # Per-symbol value weights (market value where marked, else cost basis).
    weights: dict[str, Decimal] = {}
    total_value = Decimal("0")
    for h in holdings:
        sym = h.symbol
        if not sym:
            continue
        mp = mark_prices.get(sym)
        val = (mp * h.qty).quantize(Decimal("0.01")) if mp else h.cost_basis_inr
        weights[sym] = weights.get(sym, Decimal("0")) + val
        total_value += val

    # Value-weighted portfolio daily log-return series.
    symbols = sorted(weights.keys())
    series = await fetch_return_series(db, symbols, window_days)
    portfolio_returns: list[float] = []
    if series and total_value > 0:
        aligned = {s: series[s] for s in symbols if series.get(s)}
        if aligned:
            n = min(len(v) for v in aligned.values())
            for i in range(n):
                day_ret = 0.0
                for s, rs in aligned.items():
                    w = float(weights[s] / total_value)
                    day_ret += w * rs[-n:][i]
                portfolio_returns.append(day_ret)

    pv_inr = total_value if total_value > 0 else None
    var95 = svc.historical_var(portfolio_returns, confidence=0.95, portfolio_value_inr=pv_inr)
    var99 = svc.historical_var(portfolio_returns, confidence=0.99, portfolio_value_inr=pv_inr)

    def _abs_pct(v: dict) -> float:
        return abs(float(v.get("var_pct", 0.0)))

    def _abs_inr(v: dict) -> float:
        return abs(float(v.get("var_inr", 0.0))) if "var_inr" in v else 0.0

    # Concentration HHI.
    conc = await svc.concentration_score(mark_prices=mark_prices)
    hhi = float(conc.get("hhi", 0.0))

    # Daily new-positions remaining (honours the operator's persisted cap).
    rm = await RiskManager.from_prefs(db)
    remaining = rm.daily_new_positions_remaining(positions_added_today)

    # 30d Sharpe from the same portfolio return series.
    sharpe = trailing_sharpe(portfolio_returns, window=30) if portfolio_returns else 0.0

    # NAV history → drawdown series + day change.
    nav_history = await svc.nav_history(days=window_days + 7)
    drawdown_series: list[dict] = []
    day_change_inr = 0.0
    day_change_pct = 0.0
    if nav_history:
        running_peak = nav_history[0][1]
        for d, nav in nav_history:
            if nav > running_peak:
                running_peak = nav
            dd_pct = float((Decimal("1") - nav / running_peak)) * 100.0 if running_peak > 0 else 0.0
            drawdown_series.append({"date": d.isoformat(), "drawdown_pct": round(dd_pct, 4)})
        if len(nav_history) >= 2:
            prev_nav = nav_history[-2][1]
            last_nav = nav_history[-1][1]
            day_change_inr = float((last_nav - prev_nav))
            if prev_nav != 0:
                day_change_pct = float((last_nav - prev_nav) / prev_nav) * 100.0

    return {
        "var_95_inr": _abs_inr(var95),
        "var_99_inr": _abs_inr(var99),
        "var_95_pct": round(_abs_pct(var95) * 100.0, 4),
        "var_99_pct": round(_abs_pct(var99) * 100.0, 4),
        "window_days": window_days,
        "concentration_hhi": round(hhi, 6),
        "drawdown_series": drawdown_series,
        "daily_new_positions_remaining": int(remaining),
        "sharpe_30d": round(float(sharpe), 4),
        "day_change_inr": round(day_change_inr, 2),
        "day_change_pct": round(day_change_pct, 4),
    }


# ---------------------------------------------------------------------------
# Pre-trade risk gate
# ---------------------------------------------------------------------------


@router.post("/pre-trade")
async def pre_trade(body: PreTradeRequest, db: DbSession, _user: CurrentUser) -> dict:
    """Run the 10-item Appendix B pre-trade checklist (automatable subset)."""
    rm = await RiskManager.from_prefs(db)
    verdict = rm.check_pre_trade(
        symbol=body.symbol,
        qty=body.qty,
        price=body.price,
        existing_holdings=[{"symbol": s} for s in body.existing_symbols],
        portfolio_value_inr=body.portfolio_value_inr,
        stop_distance_pct=body.stop_distance_pct,
        regime=body.regime,
        signal_confidence=body.signal_confidence,
        news_count_24h=body.news_count_24h,
        event_calendar_conflict=body.event_calendar_conflict,
        positions_added_today=body.positions_added_today,
        current_drawdown_pct=body.current_drawdown_pct,
    )
    sizing = None
    if body.stop_distance_pct is not None and body.stop_distance_pct > 0:
        sizing = rm.position_size_recommend(
            stop_distance_pct=body.stop_distance_pct,
            portfolio_value_inr=body.portfolio_value_inr,
            price_per_unit_inr=body.price,
        )
    return {
        "pass_all": verdict.pass_all,
        "reasons": verdict.reasons,
        "per_item": verdict.per_item,
        "sizing": sizing,
        "daily_positions_remaining": rm.daily_new_positions_remaining(body.positions_added_today),
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Rebalance / allocation
# ---------------------------------------------------------------------------


@router.post("/rebalance")
async def rebalance(body: RebalanceRequest, _user: CurrentUser) -> dict:
    """Advisory rebalance suggestions."""
    strategic = StrategicTargets(
        equity_pct=body.strategic.get("equity", 0.5),
        debt_pct=body.strategic.get("debt", 0.25),
        gold_pct=body.strategic.get("gold", 0.1),
        crypto_pct=body.strategic.get("crypto", 0.1),
        cash_pct=body.strategic.get("cash", 0.05),
    )
    strategic.validate()
    adjusted = tactical_adjust(strategic, body.regime_per_market, body.sentiment)
    current = {k: Decimal(str(v)) for k, v in body.current_allocation.items()}
    suggestions = rebalance_suggestions(current, adjusted, body.drift_threshold)
    return {
        "tactical_targets": adjusted,
        **suggestions_to_dict(suggestions),
    }


# ---------------------------------------------------------------------------
# Goal-based planning
# ---------------------------------------------------------------------------


@router.post("/goals/project")
async def goals_project(body: GoalProjectRequest, _user: CurrentUser) -> dict:
    """Monte Carlo net-worth projection for a savings goal.

    Stateless: takes the plan parameters and returns the terminal-value
    distribution. With a ``target_inr`` it also reports the probability of
    reaching the goal and the monthly contribution required to hit it at the
    median. Advisory only — the figures are a distribution, not a promise.
    """
    if body.years <= 0:
        raise HTTPException(status_code=422, detail="years must be > 0")
    n_sims = max(1000, min(body.n_sims, 50_000))
    projection = project_goal(
        current_corpus_inr=body.current_corpus_inr,
        monthly_contribution_inr=body.monthly_contribution_inr,
        years=body.years,
        expected_annual_return=body.expected_annual_return,
        annual_volatility=body.annual_volatility,
        target_inr=body.target_inr,
        n_sims=n_sims,
    )
    out = projection.as_dict()
    if body.target_inr is not None:
        out["required_monthly_contribution_inr"] = required_monthly_contribution(
            current_corpus_inr=body.current_corpus_inr,
            target_inr=body.target_inr,
            years=body.years,
            expected_annual_return=body.expected_annual_return,
            annual_volatility=body.annual_volatility,
            n_sims=n_sims,
        )
    out["disclaimer"] = DISCLAIMER
    return out


@router.post("/what-if")
async def what_if(body: WhatIfRequest, db: DbSession, _user: CurrentUser) -> dict:
    """Simulate a proposed BUY/SELL against the live book.

    Returns before/after exposure-by-category + concentration (HHI) and, for a
    SELL, the Indian capital-gains tax it would realise. Nothing is executed.
    """
    action = body.action.upper()
    if action not in ("BUY", "SELL"):
        raise HTTPException(status_code=422, detail="action must be BUY or SELL")
    if body.qty <= 0:
        raise HTTPException(status_code=422, detail="qty must be > 0")
    service = PortfolioService(db)
    result = await run_what_if(
        service,
        action=action,
        symbol=body.symbol,
        qty=body.qty,
        price=body.price,
        mark_prices=body.mark_prices,
    )
    return result.as_dict()


@router.get("/benchmark")
async def benchmark(
    db: DbSession,
    _user: CurrentUser,
    symbol: str = Query(default="NIFTY 50"),
) -> dict:
    """Compare the live portfolio's return vs a benchmark over 1M/YTD/1Y/Max.

    ``symbol`` accepts friendly names (NIFTY 50, SENSEX, S&P 500, SPY). Returns
    per-window portfolio return, benchmark return, and excess; values are null
    where history is missing.
    """
    out = await run_benchmark(db, symbol=symbol)
    out["disclaimer"] = DISCLAIMER
    return out


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------


@router.get("/import/supported")
async def import_supported(_user: CurrentUser) -> dict:
    """List supported broker adapters + pinned schema versions."""
    return {"brokers": list_supported(), "disclaimer": DISCLAIMER}


@router.post("/import")
async def import_csv(
    db: DbSession,
    _user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008
    broker: str | None = Form(default=None),
    dry_run: bool = Form(default=True),
) -> dict:
    """Import a portfolio CSV.

    When ``dry_run`` is False (default True for safety), the parsed rows are
    persisted as ``portfolio_tx`` ledger rows **and** immediately rolled up into
    ``holdings`` so the import → portfolio/dashboard path is one step. Each
    persisted tx stamps its symbol + asset class into ``note`` (via
    ``encode_tx_note``) so the rollup can group the ledger by position; see
    ``pfip.portfolio.rollup``.

    Response (superset of the parser summary)::

        {
          "broker": str, "schema_version": str,
          "imported": int, "rejected": int,
          "rows": [{symbol, time, kind, qty, amount_inr, cost_basis_ccy}, ...],
          "errors": [...],
          "persisted": int,            # tx rows written (0 on dry_run)
          "dry_run": bool,
          "holdings_rebuilt": int,     # holdings materialized (0 on dry_run)
          "holdings": [Holding, ...],  # the materialized open holdings
          "disclaimer": str
        }
    """
    payload = await file.read()
    try:
        result = route_and_parse(payload, broker)
    except UnknownSchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_schema", "message": str(exc)},
        ) from exc

    persisted = 0
    rebuilt: list[Holding] = []
    if not dry_run and result.imported:
        # Persist each row as a PortfolioTxRow. ``holding_id`` stays None — the
        # rollup materializes holdings from the ledger rather than pinning rows.
        for r in result.imported:
            tx = PortfolioTxRow(
                holding_id=None,
                time=r.time,
                kind=r.kind,
                qty=r.qty,
                price=r.price,
                amount_inr=r.amount_inr,
                fx_rate=r.fx_rate,
                tax_withheld=r.tax_withheld,
                note=encode_tx_note(
                    broker=r.broker,
                    symbol=r.symbol,
                    asset_class=asset_class_for(r.broker, None),
                    free=r.note,
                ),
            )
            db.add(tx)
            persisted += 1
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Commit failed: {exc}",
            ) from exc

        # Materialize holdings from the (now-persisted) ledger so the portfolio
        # is populated in a single import call. Idempotent — safe to re-run.
        try:
            rebuilt = await rebuild_holdings_from_tx(db)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Holdings rebuild failed after import: {exc}",
            ) from exc

    summary = result.summary()
    summary["persisted"] = persisted
    summary["dry_run"] = dry_run
    summary["holdings_rebuilt"] = len(rebuilt)
    summary["holdings"] = [h.model_dump(mode="json") for h in rebuilt]
    summary["disclaimer"] = DISCLAIMER
    return summary
