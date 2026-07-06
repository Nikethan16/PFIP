"""User-defined alerts API.

``POST /alerts/evaluate`` takes a list of alert rules (the frontend persists
them locally) and evaluates each against the latest prices, returning which are
currently triggered. ``GET /alerts/kinds`` lists the supported rule kinds.

This is the on-demand / live-check half of alerts. Background firing to the
bell + Telegram (which needs a server-side rules table + the scheduler) reuses
the same :mod:`pfip.alerts.rules` engine and is a logged follow-up.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from pfip.alerts.rules import RULE_LABELS, AlertEval, AlertRule, evaluate_rule
from pfip.api.deps import CurrentUser, DbSession
from pfip.models.ohlcv import OHLCVRow

router = APIRouter(prefix="/alerts", tags=["alerts"])


class KindInfo(BaseModel):
    key: str
    label: str


class KindsResponse(BaseModel):
    kinds: list[KindInfo]


class EvaluateRequest(BaseModel):
    rules: list[AlertRule]


class EvaluateResponse(BaseModel):
    results: list[AlertEval]
    n_triggered: int
    evaluated_at: datetime
    disclaimer: str = (
        "Live check against the latest stored close — informational, not a trade "
        "instruction. Background firing to Telegram is a separate setting."
    )


@router.get("/kinds", response_model=KindsResponse)
async def kinds(_user: CurrentUser) -> KindsResponse:
    return KindsResponse(kinds=[KindInfo(key=k, label=v) for k, v in RULE_LABELS.items()])


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(body: EvaluateRequest, db: DbSession, _user: CurrentUser) -> EvaluateResponse:
    """Evaluate every rule against the latest price snapshot for its symbol."""
    symbols = {r.symbol for r in body.rules}
    snapshots = {s: await _price_snapshot(db, s) for s in symbols}

    results: list[AlertEval] = []
    for rule in body.rules:
        last_close, move = snapshots.get(rule.symbol, (None, None))
        results.append(evaluate_rule(rule, last_close=last_close, move_pct_1d=move))

    return EvaluateResponse(
        results=results,
        n_triggered=sum(1 for r in results if r.triggered),
        evaluated_at=datetime.now(tz=timezone.utc),
    )


async def _price_snapshot(db: DbSession, symbol: str) -> tuple[float | None, float | None]:
    """(last_close, 1-day move %) for a symbol from the freshest daily source."""
    try:
        freshest = (
            select(OHLCVRow.source)
            .where(OHLCVRow.symbol == symbol, OHLCVRow.timeframe == "1d")
            .order_by(OHLCVRow.time.desc())
            .limit(1)
            .scalar_subquery()
        )
        since = datetime.now(tz=timezone.utc) - timedelta(days=10)
        rows = (
            await db.execute(
                select(OHLCVRow.close)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.timeframe == "1d",
                    OHLCVRow.source == freshest,
                    OHLCVRow.time >= since,
                )
                .order_by(OHLCVRow.time.desc())
                .limit(2)
            )
        ).all()
    except Exception:  # noqa: BLE001
        return None, None
    if not rows:
        return None, None
    last_close = float(rows[0][0])
    move = None
    if len(rows) >= 2:
        prev = float(rows[1][0])
        if prev > 0:
            move = (last_close - prev) / prev * 100.0
    return last_close, move
