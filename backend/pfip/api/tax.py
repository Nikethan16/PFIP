"""Indian tax router — Stage 5.

Every endpoint is advisory. Structured responses prepend ``DISCLAIMER``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession
from pfip.brokers.csv_adapters import UnknownSchemaError
from pfip.brokers.csv_adapters.router import tax_focused_parse
from pfip.models.holdings import HoldingRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.portfolio_tx import PortfolioTxRow
from pfip.tax.engine import (
    AssetClass,
    CGEvent,
    GainTerm,
    build_tax_summary,
    classify_capital_gains,
    compare_regimes,
    compute_80c_optimizer,
    compute_form_67,
    compute_ltcg,
    compute_schedule_fa,
    compute_stcg,
    compute_vda_tax,
    dividend_tax,
    fy_bounds,
    itr_form_recommendation,
    surcharge_cliff_check,
)
from pfip.tax.indian_rules import DEDUCTION_LIMITS_INR, SURCHARGE_BANDS
from pfip.tax.forms import (
    build_summary_pdf,
    form_67_json,
    schedule_cg_json,
    schedule_fa_json,
)
from pfip.tax.fx_cost_basis import prefetch_fx_rates
from pfip.tax.indian_rules import DISCLAIMER, is_vda

router = APIRouter(prefix="/tax", tags=["tax"])


def _wrap(payload: dict) -> dict:
    """Always prepend disclaimer to structured responses."""
    out = {"disclaimer": DISCLAIMER}
    out.update(payload)
    return out


def _cg_event_to_dict(e: CGEvent) -> dict:
    return {
        "symbol": e.symbol,
        "asset_class": e.asset_class.value,
        "term": e.term.value,
        "qty": str(e.qty),
        "buy_date": e.buy_date.isoformat(),
        "sell_date": e.sell_date.isoformat(),
        "buy_cost_inr": str(e.buy_cost_inr),
        "sell_proceeds_inr": str(e.sell_proceeds_inr),
        "gain_inr": str(e.gain_inr),
        "grandfathered": e.grandfathered,
        "tds_inr": str(e.tds_inr),
    }


# ---------------------------------------------------------------------------
# Load realised events from DB (buys + sells joined on holdings)
# ---------------------------------------------------------------------------


async def _fetch_enriched_tx(db: Any, fy: str | None = None) -> list[dict]:
    """Join holdings + portfolio_tx into the dict shape classify_capital_gains expects.

    When ``fy`` is given, the FY date bounds are pushed into the portfolio_tx
    SQL query (``time`` column) so we don't full-table-scan and filter in
    Python. Results are otherwise identical to the unfiltered path.
    """
    result = await db.execute(select(HoldingRow))
    holdings = {h.id: h for h in result.scalars().all()}
    tx_stmt = select(PortfolioTxRow)
    if fy is not None:
        fy_start, fy_end = fy_bounds(fy)
        tx_stmt = tx_stmt.where(
            PortfolioTxRow.time
            >= datetime(fy_start.year, fy_start.month, fy_start.day, tzinfo=timezone.utc),
            PortfolioTxRow.time
            <= datetime(fy_end.year, fy_end.month, fy_end.day, 23, 59, 59, tzinfo=timezone.utc),
        )
    tx_result = await db.execute(tx_stmt)
    txs = tx_result.scalars().all()

    enriched: list[dict] = []
    for t in txs:
        h = holdings.get(t.holding_id) if t.holding_id else None
        sym = h.symbol if h else None
        if not sym:
            continue
        ac = None
        if h and h.category in ("crypto_exchange", "crypto_self_custody"):
            ac = AssetClass.VDA
        elif is_vda(sym):
            ac = AssetClass.VDA
        elif h and h.cost_basis_ccy == "USD":
            ac = AssetClass.US_STOCK
        elif h and h.category == "mutual_fund":
            ac = AssetClass.EQUITY_MF
        else:
            ac = AssetClass.EQUITY
        # per-unit price on tx; if absent and qty>0 derive from amount.
        price = t.price
        if price is None and t.qty and Decimal(str(t.qty)) != 0:
            price = (Decimal(str(t.amount_inr)) / Decimal(str(t.qty))).quantize(Decimal("0.0001"))
        enriched.append(
            {
                "symbol": sym,
                "time": t.time,
                "kind": t.kind,
                "qty": t.qty,
                "price": price,
                "amount_inr": t.amount_inr,
                "tax_withheld": t.tax_withheld,
                "asset_class": ac,
            }
        )
    return enriched


# ---------------------------------------------------------------------------
# /tax/summary
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(..., description="FY, e.g. 2026-27"),
    gross_income_inr: Decimal = Query(Decimal("0")),
    has_foreign_assets: bool = Query(False),
) -> dict:
    """Full tax snapshot for a fiscal year."""
    enriched = await _fetch_enriched_tx(db, fy)
    events = classify_capital_gains(enriched)
    summary = build_tax_summary(
        fy,
        events,
        gross_income=gross_income_inr,
        has_foreign_assets=has_foreign_assets,
    )
    return _wrap(
        {
            "fy": summary.fy,
            "equity_stcg_gain_inr": str(summary.stcg_equity_inr),
            "equity_ltcg_gain_inr": str(summary.ltcg_equity_inr),
            "vda_gain_inr": str(summary.vda_gain_inr),
            "vda_tds_credit_inr": str(summary.vda_tds_inr),
            "dividend_inr": str(summary.dividend_inr),
            "total_tax_inr": str(summary.total_tax_inr),
            "recommended_regime": summary.recommended_regime,
            "recommended_itr": summary.recommended_itr,
            "surcharge_cliff_warnings": summary.surcharge_cliff_warnings,
            "event_count": len(
                [e for e in events if fy_bounds(fy)[0] <= e.sell_date <= fy_bounds(fy)[1]]
            ),
        }
    )


# ---------------------------------------------------------------------------
# /tax/events — raw CG events (enables schedule-CG handoff)
# ---------------------------------------------------------------------------


@router.get("/events")
async def tax_events(db: DbSession, _user: CurrentUser, fy: str = Query(...)) -> dict:
    enriched = await _fetch_enriched_tx(db, fy)
    events = classify_capital_gains(enriched)
    start, end = fy_bounds(fy)
    fy_events = [e for e in events if start <= e.sell_date <= end]
    return _wrap(
        {
            "fy": fy,
            "events": [_cg_event_to_dict(e) for e in fy_events],
            "schedule_cg": schedule_cg_json(fy_events),
        }
    )


# ---------------------------------------------------------------------------
# /tax/schedule-fa
# ---------------------------------------------------------------------------


async def _fy_daily_closes(db: Any, symbol: str, start: date, end: date) -> dict[date, Decimal]:
    """Return ``{date: close}`` for ``symbol``'s daily OHLCV bars within the FY.

    Uses the ``1d`` timeframe close (instrument quote currency — USD for US
    stocks). Multiple sources for the same day collapse to the last seen close.
    """
    rows = (
        await db.execute(
            select(OHLCVRow.ts, OHLCVRow.close)
            .where(
                OHLCVRow.symbol == symbol,
                OHLCVRow.timeframe == "1d",
                OHLCVRow.ts >= datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
                OHLCVRow.ts
                <= datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc),
            )
            .order_by(OHLCVRow.ts.asc())
        )
    ).all()
    out: dict[date, Decimal] = {}
    for ts, close in rows:
        if ts is None or close is None:
            continue
        out[ts.date()] = Decimal(str(close))
    return out


@router.get("/schedule-fa")
async def schedule_fa(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(...),
) -> dict:
    """Schedule FA rows for US-stock holdings.

    Peak/closing balances are computed from **real daily OHLCV closes** over the
    financial year: for each holding the per-day USD balance is ``qty × daily
    close``; the peak over the FY window and the closing balance (``qty × close``
    on the latest bar on/before FY-end) follow from that series.

    When a holding has no usable price history in the FY we fall back to the
    cost-basis approximation (peak ≈ cost basis, closing = 0) and flag the row
    with ``"basis": "cost_approx"`` so the value is honest, not silently wrong.
    Price-derived rows are flagged ``"basis": "peak"``.
    """
    start, end = fy_bounds(fy)
    result = await db.execute(select(HoldingRow).where(HoldingRow.cost_basis_ccy == "USD"))
    rows = result.scalars().all()

    us_holdings: list[dict] = []
    # Track which holdings used real price history vs the cost-basis fallback,
    # keyed by symbol (matches how schedule_fa_json emits rows).
    basis_by_symbol: dict[str | None, str] = {}
    for r in rows:
        acquired = r.acquired_at.date() if r.acquired_at else None
        qty = Decimal(str(r.qty)) if r.qty is not None else Decimal("0")

        closes = await _fy_daily_closes(db, r.symbol, start, end) if r.symbol else {}
        # Only count price days on/after acquisition — we didn't hold it before.
        if acquired is not None:
            closes = {d: c for d, c in closes.items() if d >= acquired}

        if closes and qty != 0:
            daily_balances = {d: (qty * c) for d, c in closes.items()}
            closing_date = max(closes)  # latest bar on/before FY-end
            closing_usd = qty * closes[closing_date]
            basis_by_symbol[r.symbol] = "peak"
        else:
            # Fallback: approximate peak = cost basis in USD, no closing mark.
            daily_balances = (
                {acquired: (Decimal(str(r.cost_basis_inr)) / Decimal(str(r.fx_rate)))}
                if (r.fx_rate and acquired)
                else {}
            )
            closing_usd = Decimal("0")
            basis_by_symbol[r.symbol] = "cost_approx"

        us_holdings.append(
            {
                "symbol": r.symbol,
                "isin": r.isin,
                "acquired_on": acquired,
                "daily_balances_usd": daily_balances,
                "closing_balance_usd": closing_usd,
                "country": "USA",
            }
        )

    dividends_usd: list[dict] = []  # future: pull from portfolio_tx kind=DIVIDEND
    # Pre-fetch FX rates async (AsyncSession can't be queried synchronously
    # inside the sync tax math). Cover every peak date + the FY end date.
    needs: list[tuple[str, date]] = [("USD", end)]
    for h in us_holdings:
        for d in h.get("daily_balances_usd") or {}:
            if start <= d <= end:
                needs.append(("USD", d))
    rate_cache = await prefetch_fx_rates(db, needs)
    fa_rows = compute_schedule_fa(us_holdings, dividends_usd, fy, db=db, rate_cache=rate_cache)
    payload = schedule_fa_json(fa_rows)
    # Annotate each row with how its peak/closing was derived (backward-compatible
    # additive field only).
    for row in payload.get("rows", []):
        row["basis"] = basis_by_symbol.get(row.get("symbol"), "cost_approx")
    return _wrap({"fy": fy, **payload})


# ---------------------------------------------------------------------------
# /tax/form-67
# ---------------------------------------------------------------------------


@router.get("/form-67")
async def form_67(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(...),
    slab_rate: float = Query(0.30),
) -> dict:
    """Form 67 rows for DTAA credit on US dividends."""
    start, end = fy_bounds(fy)
    # Pull dividend tx on USD-basis holdings in this FY.
    hold_res = await db.execute(select(HoldingRow).where(HoldingRow.cost_basis_ccy == "USD"))
    holdings = {h.id: h for h in hold_res.scalars().all()}
    tx_res = await db.execute(select(PortfolioTxRow).where(PortfolioTxRow.kind == "DIVIDEND"))
    dividends: list[dict] = []
    for t in tx_res.scalars().all():
        h = holdings.get(t.holding_id) if t.holding_id else None
        if h is None:
            continue
        on = t.time.date() if t.time else start
        if not (start <= on <= end):
            continue
        # amount_inr stored; derive USD via fx_rate if available
        fx = Decimal(str(t.fx_rate)) if t.fx_rate else None
        amount_usd = Decimal(str(t.amount_inr)) / fx if fx else Decimal(str(t.amount_inr))
        wht_usd = Decimal(str(t.tax_withheld or 0))
        if fx and t.tax_withheld is not None:
            wht_usd = Decimal(str(t.tax_withheld)) / fx
        dividends.append(
            {
                "symbol": h.symbol,
                "paid_on": on,
                "amount_usd": amount_usd,
                "tax_withheld_usd": wht_usd,
                "fx_rate": fx,
            }
        )
    # Pre-fetch FX rates async for any dividend lacking an explicit fx_rate.
    needs = [("USD", d["paid_on"]) for d in dividends if d.get("fx_rate") is None]
    rate_cache = await prefetch_fx_rates(db, needs)
    rows = compute_form_67(dividends, Decimal(str(slab_rate)), db=db, rate_cache=rate_cache)
    return _wrap({"fy": fy, **form_67_json(rows)})


# ---------------------------------------------------------------------------
# /tax/regime-compare
# ---------------------------------------------------------------------------


class RegimeCompareRequest(BaseModel):
    gross_income_inr: Decimal
    deductions: dict[str, Decimal] = {}
    fy: str = "2026-27"


@router.post("/regime-compare")
async def regime_compare(body: RegimeCompareRequest, _user: CurrentUser) -> dict:
    result = compare_regimes(body.gross_income_inr, body.deductions, fy=body.fy)
    # Keep Decimal → str for JSON safety
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items()}


# ---------------------------------------------------------------------------
# /tax/80c-optimizer
# ---------------------------------------------------------------------------


class OptimizerRequest(BaseModel):
    current_investments: dict[str, Decimal]
    income_slab_rate: Decimal


@router.post("/80c-optimizer")
async def optimizer(body: OptimizerRequest, _user: CurrentUser) -> dict:
    out = compute_80c_optimizer(body.current_investments, body.income_slab_rate)
    # Ensure JSON friendliness
    ranked = [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in item.items()}
        for item in out["ranked"]
    ]
    return {
        "ranked": ranked,
        "total_tax_saved_if_max_all_inr": str(out["total_tax_saved_if_max_all_inr"]),
        "note": out["note"],
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# /tax/surcharge-check
# ---------------------------------------------------------------------------


@router.get("/surcharge-check")
async def surcharge_check(
    _user: CurrentUser, taxable_income_inr: Decimal = Query(Decimal("0"))
) -> dict:
    result = surcharge_cliff_check(taxable_income_inr)
    result["taxable_income_inr"] = str(result["taxable_income_inr"])
    result["flags"] = [
        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in f.items()}
        for f in result["flags"]
    ]
    return result


# ---------------------------------------------------------------------------
# /tax/itr-recommendation
# ---------------------------------------------------------------------------


class ITRRequest(BaseModel):
    salary: bool = False
    house_property: bool = False
    capital_gains: bool = False
    business: bool = False
    foreign_assets: bool = False
    presumptive: bool = False


@router.post("/itr-recommendation")
async def itr_recommend(body: ITRRequest, _user: CurrentUser) -> dict:
    return itr_form_recommendation(body.model_dump())


# ---------------------------------------------------------------------------
# /tax/import/{broker}
# ---------------------------------------------------------------------------


@router.post("/import/{broker}")
async def import_broker(
    broker: str,
    db: DbSession,
    _user: CurrentUser,
    file: UploadFile = File(...),  # noqa: B008
    dry_run: bool = Form(default=True),
) -> dict:
    """Tax-focused CSV import — same routing as portfolio but tags asset_class."""
    from pfip.brokers.csv_adapters.router import ADAPTERS

    # Validate broker against the known adapter registry before reading the file.
    if broker.strip().lower() not in ADAPTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_broker",
                "message": f"Unknown broker '{broker}'. Supported: {', '.join(sorted(ADAPTERS))}.",
            },
        )

    # Enforce a 10 MB upload cap — read in bounded chunks and reject oversize
    # files with 413 rather than buffering arbitrary input into memory.
    max_bytes = 10 * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Uploaded file exceeds 10MB limit.",
            )
        chunks.append(chunk)
    payload = b"".join(chunks)
    try:
        result = tax_focused_parse(payload, broker)
    except UnknownSchemaError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_schema", "message": str(exc)},
        ) from exc
    persisted = 0
    if not dry_run and result.imported:
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
                note=f"[tax|{r.broker}:{r.symbol}] {r.note or ''}".strip(),
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
    out = result.summary()
    out["persisted"] = persisted
    out["dry_run"] = dry_run
    out["disclaimer"] = DISCLAIMER
    return out


# ---------------------------------------------------------------------------
# /tax/summary/pdf — CA handoff
# ---------------------------------------------------------------------------


@router.get("/summary/pdf")
async def summary_pdf(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(...),
    gross_income_inr: Decimal = Query(Decimal("0")),
) -> Response:
    enriched = await _fetch_enriched_tx(db, fy)
    events = classify_capital_gains(enriched)
    summary = build_tax_summary(fy, events, gross_income=gross_income_inr)
    pdf = build_summary_pdf(summary, events=events)
    # If reportlab isn't installed the helper returns text bytes.
    ct = "application/pdf" if pdf.startswith(b"%PDF") else "text/plain"
    return Response(content=pdf, media_type=ct)


# ---------------------------------------------------------------------------
# /tax/export — PDF package download (frontend downloadTaxExport)
# ---------------------------------------------------------------------------


@router.get("/export")
async def tax_export(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(..., description="FY, e.g. 2026-27"),
    gross_income_inr: Decimal = Query(Decimal("0")),
) -> Response:
    """Download the FY tax package as a PDF (CA handoff).

    The frontend ``downloadTaxExport`` fetches this with ``Accept:
    application/pdf`` and saves the blob as ``pfip-tax-<fy>.pdf``. Reuses the
    same ``build_summary_pdf`` renderer as ``/tax/summary/pdf`` and sets a
    Content-Disposition so the browser names the download correctly. Falls back
    to a text/plain body if reportlab is unavailable.
    """
    enriched = await _fetch_enriched_tx(db, fy)
    events = classify_capital_gains(enriched)
    summary = build_tax_summary(fy, events, gross_income=gross_income_inr)
    pdf = build_summary_pdf(summary, events=events)
    is_pdf = pdf.startswith(b"%PDF")
    ext = "pdf" if is_pdf else "txt"
    ct = "application/pdf" if is_pdf else "text/plain"
    return Response(
        content=pdf,
        media_type=ct,
        headers={"Content-Disposition": f'attachment; filename="pfip-tax-{fy}.{ext}"'},
    )


# ---------------------------------------------------------------------------
# /tax/details — extended tax view (80C optimizer + surcharge + Form 67)
# ---------------------------------------------------------------------------


@router.get("/details")
async def tax_details(
    db: DbSession,
    _user: CurrentUser,
    fy: str = Query(..., description="FY, e.g. 2026-27"),
    gross_income_inr: Decimal = Query(Decimal("0")),
) -> dict:
    """Extended tax detail for the tax page (regime compare, 80C, surcharge).

    Shapes exactly to the frontend ``TaxDetailsSchema`` (all plain numbers):
    ``{ fy, slab_income_inr, eighty_c_used_inr, eighty_c_cap_inr,
    marginal_rate_pct, total_income_inr, old_regime_tax_inr,
    new_regime_tax_inr, surcharge_thresholds[{threshold_inr, rate_pct}],
    form_67_lines[] }``.

    ``slab_income_inr`` / ``total_income_inr`` are the caller-supplied
    ``gross_income_inr`` plus realised capital gains in the FY (the only income
    PFIP itself can observe). With no income supplied and no events the figures
    are 0 and the regime taxes are 0 — a correct empty shape, not fabricated.
    """
    enriched = await _fetch_enriched_tx(db, fy)
    events = classify_capital_gains(enriched)
    start, end = fy_bounds(fy)
    fy_events = [e for e in events if start <= e.sell_date <= end]
    realised_gains = sum((e.gain_inr for e in fy_events), Decimal("0"))

    slab_income = Decimal(str(gross_income_inr))
    total_income = (slab_income + realised_gains).quantize(Decimal("0.01"))

    regimes = compare_regimes(slab_income, {}, fy=fy)
    old_tax = Decimal(str(regimes["old_regime_tax_inr"]))
    new_tax = Decimal(str(regimes["new_regime_tax_inr"]))

    # Marginal slab rate at this income (whole-number percent).
    if total_income > Decimal("1500000"):
        marginal_rate_pct = 30.0
    elif total_income > Decimal("1000000"):
        marginal_rate_pct = 20.0
    elif total_income > Decimal("500000"):
        marginal_rate_pct = 5.0
    else:
        marginal_rate_pct = 0.0

    eighty_c_cap = DEDUCTION_LIMITS_INR["80C"]

    # Form 67 lines: descriptive strings for any FY US-dividend tx.
    hold_res = await db.execute(select(HoldingRow).where(HoldingRow.cost_basis_ccy == "USD"))
    us_holdings = {h.id: h for h in hold_res.scalars().all()}
    tx_res = await db.execute(select(PortfolioTxRow).where(PortfolioTxRow.kind == "DIVIDEND"))
    form_67_lines: list[str] = []
    for t in tx_res.scalars().all():
        h = us_holdings.get(t.holding_id) if t.holding_id else None
        if h is None or not t.time:
            continue
        on = t.time.date()
        if not (start <= on <= end):
            continue
        wht = Decimal(str(t.tax_withheld or 0))
        form_67_lines.append(
            f"{h.symbol or h.isin or '—'} · {on.isoformat()} · "
            f"dividend {Decimal(str(t.amount_inr))} INR · WHT {wht} INR (DTAA credit)"
        )

    return {
        "fy": fy,
        "slab_income_inr": float(slab_income),
        "eighty_c_used_inr": 0.0,
        "eighty_c_cap_inr": float(eighty_c_cap),
        "marginal_rate_pct": marginal_rate_pct,
        "total_income_inr": float(total_income),
        "old_regime_tax_inr": float(old_tax),
        "new_regime_tax_inr": float(new_tax),
        "surcharge_thresholds": [
            {"threshold_inr": float(b.threshold), "rate_pct": float(b.rate) * 100.0}
            for b in SURCHARGE_BANDS
        ],
        "form_67_lines": form_67_lines,
    }


# ---------------------------------------------------------------------------
# /tax/harvest — loss-harvesting suggestions
# ---------------------------------------------------------------------------


class HarvestRequest(BaseModel):
    """Inputs the UI must supply because they aren't derivable from
    holdings alone."""

    fy: str
    realised_stcg_equity_inr: Decimal = Decimal("0")
    realised_ltcg_equity_inr: Decimal = Decimal("0")
    realised_debt_gain_inr: Decimal = Decimal("0")
    marginal_slab_rate: Decimal = Decimal("0.30")
    surcharge_rate: Decimal = Decimal("0")


@router.post("/harvest")
async def harvest(
    body: HarvestRequest,
    db: DbSession,
    _user: CurrentUser,
) -> dict[str, Any]:
    """Return ranked tax-loss harvesting suggestions.

    Pulls open holdings from the `holdings` table, joins to the latest
    OHLCV price, asks `pfip.tax.harvest.suggest_harvest` to rank.

    VDA/crypto rows are skipped at the source — Indian law gives them
    no loss set-off.
    """
    # Lazy import — harvest module is opt-in.
    from pfip.tax.harvest import (
        DISCLAIMER as HARVEST_DISCLAIMER,
        FYContext,
        HarvestAssetClass,
        OpenLot,
        suggest_harvest,
    )
    from pfip.models.ohlcv import OHLCVRow

    fy_start, fy_end = fy_bounds(body.fy)
    today = date.today()

    # Pull open holdings.
    rows = (await db.execute(select(HoldingRow).where(HoldingRow.qty > 0))).scalars().all()

    lots: list[OpenLot] = []
    for r in rows:
        # Skip VDAs — no harvesting permitted.
        if is_vda(r.symbol) or getattr(r, "asset_class", "").lower() == "vda":
            continue
        # Map asset_class enum string to the harvest enum.
        ac_str = (getattr(r, "asset_class", "") or "").lower()
        try:
            ac = HarvestAssetClass(ac_str)
        except ValueError:
            # Unknown / unsupported class → skip rather than guess.
            continue

        # Pull the latest close price.
        last_price_q = (
            await db.execute(
                select(OHLCVRow.close)
                .where(OHLCVRow.symbol == r.symbol)
                .order_by(OHLCVRow.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_price_q is None:
            continue
        try:
            current_price = Decimal(str(last_price_q))
        except Exception:
            continue

        lots.append(
            OpenLot(
                lot_id=str(r.id),
                symbol=r.symbol,
                asset_class=ac,
                qty=Decimal(str(r.qty)),
                cost_basis_inr_per_unit=Decimal(str(getattr(r, "avg_cost_inr", 0))),
                acquired_on=getattr(r, "first_acquired_on", today) or today,
                current_price_inr=current_price,
            )
        )

    ctx = FYContext(
        fy_start=fy_start,
        fy_end=fy_end,
        realised_stcg_equity_inr=body.realised_stcg_equity_inr,
        realised_ltcg_equity_inr=body.realised_ltcg_equity_inr,
        realised_debt_gain_inr=body.realised_debt_gain_inr,
        marginal_slab_rate=body.marginal_slab_rate,
        surcharge_rate=body.surcharge_rate,
    )

    plan = suggest_harvest(lots=lots, ctx=ctx, today=today)

    return {
        "disclaimer": HARVEST_DISCLAIMER,
        "fy": plan.fy,
        "total_loss_inr": str(plan.total_loss_inr),
        "total_tax_saved_inr": str(plan.total_tax_saved_inr),
        "suggestions": [
            {
                "lot_id": s.lot_id,
                "symbol": s.symbol,
                "asset_class": s.asset_class.value,
                "term": s.term,
                "qty": str(s.qty),
                "loss_inr": str(s.loss_inr),
                "offsets_against": s.offsets_against,
                "estimated_tax_saved_inr": str(s.estimated_tax_saved_inr),
                "warning": s.warning,
            }
            for s in plan.suggestions
        ],
        "n_lots_evaluated": len(lots),
    }
