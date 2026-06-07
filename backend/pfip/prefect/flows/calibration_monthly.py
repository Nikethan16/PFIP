"""Prefect flow: monthly calibration report (first Saturday of the month).

For every distinct (model_name, model_version) that has emitted signals in
the last 3 months, compute Brier / ECE / reliability / sharpness over the
realised labels. Persist into ``calibration_reports``. If ECE > 0.15 for two
consecutive months, emit a ``suspend`` event into ``model_events``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from prefect import flow, get_run_logger, task
from sqlalchemy import desc, select

from pfip.calibration.brier_ece import (
    check_suspension_rule,
    compute_brier_score,
    compute_ece,
    reliability_diagram,
    sharpness,
)
from pfip.db.session import get_sessionmaker
from pfip.models.calibration_reports import CalibrationReportRow, ModelEventRow
from pfip.models.ohlcv import OHLCVRow
from pfip.models.signals import SignalRow


@task(name="load-signals-3mo")
async def _load_signals(months: int = 3) -> list[SignalRow]:
    since = datetime.now(tz=timezone.utc) - timedelta(days=months * 31)
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(SignalRow)
            .where(SignalRow.generated_at >= since)
            .order_by(SignalRow.generated_at.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


@task(name="load-prices")
async def _load_prices_for(symbol: str) -> pd.DataFrame:
    since = datetime.now(tz=timezone.utc) - timedelta(days=120)
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(OHLCVRow.time, OHLCVRow.close)
            .where(OHLCVRow.symbol == symbol, OHLCVRow.time >= since)
            .order_by(OHLCVRow.time.asc())
        )
        res = await session.execute(stmt)
        rows = res.all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, columns=["time", "close"]).set_index("time")


def _realised_outcome(
    price_df: pd.DataFrame, generated_at: datetime, horizon_hours: int, direction: str
) -> float | None:
    """Return 1.0 if the direction is correct ``horizon_hours`` later, else 0.0."""
    if price_df.empty:
        return None
    tgt = generated_at + timedelta(hours=horizon_hours)
    try:
        t_now = price_df.index.asof(generated_at)
        t_fut = price_df.index.asof(tgt)
    except Exception:
        return None
    if pd.isna(t_now) or pd.isna(t_fut) or t_now == t_fut:
        return None
    price_now = float(price_df.loc[t_now, "close"])
    price_fut = float(price_df.loc[t_fut, "close"])
    if direction == "BUY":
        return 1.0 if price_fut > price_now else 0.0
    if direction == "SELL":
        return 1.0 if price_fut < price_now else 0.0
    # HOLD -> outcome = close ≈ neutral; treat as 0.5 probability neutral skip
    return None


@task(name="write-report")
async def _write_report(
    *,
    model_name: str,
    model_version: str,
    market: str,
    period_start: datetime,
    period_end: datetime,
    brier: float,
    ece: float,
    sharp: float,
    reliability: list[dict],
    n_samples: int,
) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        row = CalibrationReportRow(
            model_name=model_name,
            model_version=model_version,
            market=market,
            period_start=period_start,
            period_end=period_end,
            brier=float(brier),
            ece=float(ece),
            sharpness=float(sharp),
            n_samples=int(n_samples),
            reliability=reliability,
        )
        session.add(row)
        await session.commit()


async def _history_ece(model_name: str, model_version: str, market: str) -> list[float]:
    factory = get_sessionmaker()
    async with factory() as session:
        stmt = (
            select(CalibrationReportRow.ece)
            .where(
                CalibrationReportRow.model_name == model_name,
                CalibrationReportRow.model_version == model_version,
                CalibrationReportRow.market == market,
            )
            .order_by(CalibrationReportRow.period_end.asc())
        )
        res = await session.execute(stmt)
        return [float(x) for x in res.scalars().all()]


async def _emit_event(
    model_name: str, model_version: str, event_type: str, reason: str, payload: dict
) -> None:
    factory = get_sessionmaker()
    async with factory() as session:
        session.add(
            ModelEventRow(
                model_name=model_name,
                model_version=model_version,
                event_type=event_type,
                reason=reason,
                payload=payload,
            )
        )
        await session.commit()


@flow(name="calibration-monthly", log_prints=True)
async def calibration_monthly_flow() -> dict[str, int]:
    """Compute per-(model,market) calibration over the trailing 3 months."""
    log = get_run_logger()
    signal_rows = await _load_signals(months=3)
    if not signal_rows:
        log.info("calibration: no signals to score")
        return {"reports": 0, "suspensions": 0}

    df = pd.DataFrame(
        [
            {
                "model_name": s.model_name,
                "model_version": s.model_version,
                "market": s.asset,
                "direction": s.direction,
                "confidence": int(s.confidence),
                "horizon_hours": int(s.horizon_hours),
                "generated_at": s.generated_at,
            }
            for s in signal_rows
        ]
    )

    reports = 0
    suspensions = 0
    period_end = datetime.now(tz=timezone.utc)
    period_start = period_end - timedelta(days=93)

    for (model_name, model_version, market), group in df.groupby(
        ["model_name", "model_version", "market"]
    ):
        price_df = await _load_prices_for(market)
        y_true: list[float] = []
        y_prob: list[float] = []
        for _, r in group.iterrows():
            outcome = _realised_outcome(
                price_df, r["generated_at"], int(r["horizon_hours"]), str(r["direction"])
            )
            if outcome is None:
                continue
            # Confidence is stored 0..100 — convert to [0,1] probability of being correct.
            p = max(0.0, min(1.0, float(r["confidence"]) / 100.0))
            y_true.append(float(outcome))
            y_prob.append(p)

        if len(y_true) < 10:
            log.info(f"calibration: skipping {model_name}/{market} (n={len(y_true)})")
            continue

        brier = compute_brier_score(y_true, y_prob)
        ece = compute_ece(y_true, y_prob, n_bins=10)
        sharp = sharpness(y_prob)
        rel = reliability_diagram(y_true, y_prob, n_bins=10)
        rel_dicts = [
            {
                "lower": b.lower,
                "upper": b.upper,
                "predicted_mean": b.predicted_mean,
                "observed_freq": b.observed_freq,
                "count": b.count,
            }
            for b in rel
        ]

        await _write_report(
            model_name=str(model_name),
            model_version=str(model_version),
            market=str(market),
            period_start=period_start,
            period_end=period_end,
            brier=brier,
            ece=ece,
            sharp=sharp,
            reliability=rel_dicts,
            n_samples=len(y_true),
        )
        reports += 1

        # Suspension check
        hist = await _history_ece(str(model_name), str(model_version), str(market))
        if check_suspension_rule(hist, threshold=0.15, n_consecutive=2):
            await _emit_event(
                model_name=str(model_name),
                model_version=str(model_version),
                event_type="suspend",
                reason=f"ECE > 0.15 for 2 consecutive months (market={market})",
                payload={"ece_history": hist, "market": str(market)},
            )
            suspensions += 1
            log.warning(f"calibration: suspending {model_name}/{model_version} for {market}")

    log.info(f"calibration: wrote {reports} reports, {suspensions} suspensions")
    return {"reports": reports, "suspensions": suspensions}


if __name__ == "__main__":
    asyncio.run(calibration_monthly_flow())
