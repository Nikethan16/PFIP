"""Monthly calibration runner.

For each ``(model_name, model_version)`` that emitted signals in the trailing
3 months, compute Brier / ECE / reliability / sharpness over the realised
labels and persist into ``calibration_reports``. Also invoke
:func:`pfip.calibration.rules.evaluate_rules` to maybe emit a ``suspend``
event.

This module wraps the same logic the existing
:mod:`pfip.prefect.flows.calibration_monthly` flow runs, but as a single
async function callable from any orchestrator (Prefect, FastAPI, CLI, tests).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from pfip.calibration.metrics import (
    compute_brier_score,
    compute_ece,
    reliability_diagram,
    sharpness,
)
from pfip.calibration.rules import RuleResult, evaluate_rules

log = logging.getLogger(__name__)


@dataclass
class CalibrationReport:
    """One persisted calibration row + the rule outcomes for it."""

    model_name: str
    model_version: str
    market: str
    period_start: datetime
    period_end: datetime
    brier: float
    ece: float
    sharpness: float
    n_samples: int
    rule_result: RuleResult


def _realised_outcome(
    price_df: pd.DataFrame, generated_at: datetime, horizon_hours: int, direction: str
) -> float | None:
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
    return None


async def _load_signals(session, months: int = 3) -> list:
    from pfip.models.signals import SignalRow

    since = datetime.now(tz=timezone.utc) - timedelta(days=months * 31)
    stmt = (
        select(SignalRow)
        .where(SignalRow.generated_at >= since)
        .order_by(SignalRow.generated_at.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def _load_prices(session, symbol: str, days: int = 120) -> pd.DataFrame:
    try:
        from pfip.models.ohlcv import OHLCVRow
    except Exception:
        return pd.DataFrame()
    since = datetime.now(tz=timezone.utc) - timedelta(days=days)
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


async def _ece_history(session, model_name: str, model_version: str, market: str) -> list[float]:
    from pfip.models.calibration_reports import CalibrationReportRow

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


async def _persist_report(
    session,
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
    from pfip.models.calibration_reports import CalibrationReportRow

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


async def run_monthly_calibration(
    session,
    *,
    months: int = 3,
    confidence_floor: int = 65,
) -> list[CalibrationReport]:
    """End-to-end monthly calibration run. Returns one report per (model, market)."""
    signals = await _load_signals(session, months=months)
    if not signals:
        log.info("calibration: no signals to score")
        return []

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
            for s in signals
        ]
    )

    reports: list[CalibrationReport] = []
    period_end = datetime.now(tz=timezone.utc)
    period_start = period_end - timedelta(days=months * 31)

    for (model_name, model_version, market), group in df.groupby(
        ["model_name", "model_version", "market"]
    ):
        price_df = await _load_prices(session, str(market))
        y_true: list[float] = []
        y_prob: list[float] = []
        for _, r in group.iterrows():
            outcome = _realised_outcome(
                price_df,
                r["generated_at"],
                int(r["horizon_hours"]),
                str(r["direction"]),
            )
            if outcome is None:
                continue
            y_true.append(float(outcome))
            y_prob.append(max(0.0, min(1.0, float(r["confidence"]) / 100.0)))

        if len(y_true) < 10:
            log.info(
                "calibration: skipping %s/%s (n=%d)",
                model_name,
                market,
                len(y_true),
            )
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

        await _persist_report(
            session,
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

        ece_hist = await _ece_history(session, str(model_name), str(model_version), str(market))
        # Compute the 65-bucket win rate (= calibrated hit-rate for the
        # current month) to feed the confidence-floor rule.
        bucket = [
            yt for yt, yp in zip(y_true, y_prob, strict=False) if yp >= confidence_floor / 100.0
        ]
        bucket_win_rate = float(sum(bucket) / len(bucket)) if bucket else None

        rule_result = evaluate_rules(
            ece_history=ece_hist,
            bucket_win_rates=[bucket_win_rate] if bucket_win_rate is not None else [],
        )

        if rule_result.suspend:
            await _emit_event(
                session,
                model_name=str(model_name),
                model_version=str(model_version),
                event_type="suspend",
                reason=rule_result.reason,
                payload={"ece_history": ece_hist, "market": str(market)},
            )

        if rule_result.raise_floor_to is not None:
            await _emit_event(
                session,
                model_name=str(model_name),
                model_version=str(model_version),
                event_type="raise_floor",
                reason=rule_result.reason,
                payload={"new_floor": rule_result.raise_floor_to, "market": str(market)},
            )

        reports.append(
            CalibrationReport(
                model_name=str(model_name),
                model_version=str(model_version),
                market=str(market),
                period_start=period_start,
                period_end=period_end,
                brier=brier,
                ece=ece,
                sharpness=sharp,
                n_samples=len(y_true),
                rule_result=rule_result,
            )
        )

    return reports


async def _emit_event(
    session,
    *,
    model_name: str,
    model_version: str,
    event_type: str,
    reason: str,
    payload: dict,
) -> None:
    from pfip.models.calibration_reports import ModelEventRow

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
