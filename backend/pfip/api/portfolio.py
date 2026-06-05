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
from pfip.portfolio.marking import build_marking, fetch_return_series
from pfip.portfolio.risk_manager import RiskManager
from pfip.portfolio.service import (
    HoldingNotFoundError,
    HoldingValidationError,
    PortfolioService,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


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
    return await svc.portfolio_summary(mark_prices=marking.mark_prices)


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
        "exposure_pct": {
            k: (float(v / total) if total else 0.0) for k, v in exp.items()
        },
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
# Pre-trade risk gate
# ---------------------------------------------------------------------------


@router.post("/pre-trade")
async def pre_trade(body: PreTradeRequest, _user: CurrentUser) -> dict:
    """Run the 10-item Appendix B pre-trade checklist (automatable subset)."""
    rm = RiskManager()
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
        "daily_positions_remaining": rm.daily_new_positions_remaining(
            body.positions_added_today
        ),
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
    """Import a portfolio CSV. Returns ``{imported, rejected, errors}``.

    When ``dry_run`` is False (default True for safety), the parsed rows are
    persisted as portfolio_tx rows. Holdings inference for new symbols is
    deferred — the user maps symbols to holdings in a follow-up step.
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
    if not dry_run and result.imported:
        # Persist each row as a PortfolioTxRow; holding_id is None until the
        # user maps it.
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
                note=f"[{r.broker}:{r.symbol}] {r.note or ''}".strip(),
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

    summary = result.summary()
    summary["persisted"] = persisted
    summary["dry_run"] = dry_run
    summary["disclaimer"] = DISCLAIMER
    return summary
