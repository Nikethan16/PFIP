"""Derivatives features for crypto: funding rate, OI, long/short skew.

These come from the perpetuals book on Bybit / OKX and the futures venues; the
ingest agent persists rows in an optional ``derivatives_metrics`` table. We
read the latest values point-in-time and derive a small bundle of features the
signal model can consume.

Like ``on_chain.py`` this degrades to ``None`` everywhere when the upstream
table doesn't exist yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


FIELD_FUNDING_RATE = "funding_rate"  # 8h rate
FIELD_OPEN_INTEREST = "open_interest"
FIELD_LONG_SHORT_RATIO = "long_short_ratio"


DERIVATIVES_FEATURE_COLS: tuple[str, ...] = (
    "funding_rate",
    "funding_rate_8h_mean",
    "open_interest_usd",
    "open_interest_z30",
    "long_short_ratio",
)


@dataclass(frozen=True)
class DerivativesSnapshot:
    """One PIT bundle of derivatives features."""

    symbol: str
    as_of: datetime
    funding_rate: float | None
    funding_rate_8h_mean: float | None
    open_interest_usd: float | None
    open_interest_z30: float | None
    long_short_ratio: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "funding_rate": self.funding_rate,
            "funding_rate_8h_mean": self.funding_rate_8h_mean,
            "open_interest_usd": self.open_interest_usd,
            "open_interest_z30": self.open_interest_z30,
            "long_short_ratio": self.long_short_ratio,
        }


def empty_snapshot(symbol: str, as_of: datetime) -> DerivativesSnapshot:
    return DerivativesSnapshot(
        symbol=symbol,
        as_of=as_of,
        funding_rate=None,
        funding_rate_8h_mean=None,
        open_interest_usd=None,
        open_interest_z30=None,
        long_short_ratio=None,
    )


def _z_score(series: pd.Series, window: int = 30) -> float | None:
    s = series.dropna().astype(float)
    if len(s) < 5:
        return None
    tail = s.iloc[-window:]
    std = tail.std(ddof=1)
    if std == 0 or np.isnan(std):
        return None
    return float((tail.iloc[-1] - tail.mean()) / std)


def derive_from_history(
    history: pd.DataFrame, symbol: str, as_of: datetime
) -> DerivativesSnapshot:
    """Reduce a long-form (time, field, value) history into a derivatives snapshot."""
    if history is None or history.empty:
        return empty_snapshot(symbol, as_of)
    h = history.copy()
    h["time"] = pd.to_datetime(h["time"], utc=True, errors="coerce")
    h = h[h["time"] <= as_of].sort_values("time")
    if h.empty:
        return empty_snapshot(symbol, as_of)

    wide = h.pivot_table(index="time", columns="field", values="value", aggfunc="last")

    def _latest(field: str) -> float | None:
        if field not in wide.columns:
            return None
        s = wide[field].dropna()
        return float(s.iloc[-1]) if not s.empty else None

    funding_rate = _latest(FIELD_FUNDING_RATE)
    funding_mean = None
    if FIELD_FUNDING_RATE in wide.columns:
        recent = wide[FIELD_FUNDING_RATE].dropna().iloc[-3:]
        if not recent.empty:
            funding_mean = float(recent.mean())

    oi = _latest(FIELD_OPEN_INTEREST)
    oi_z = (
        _z_score(wide[FIELD_OPEN_INTEREST], 30)
        if FIELD_OPEN_INTEREST in wide.columns
        else None
    )
    lsr = _latest(FIELD_LONG_SHORT_RATIO)

    return DerivativesSnapshot(
        symbol=symbol,
        as_of=as_of,
        funding_rate=funding_rate,
        funding_rate_8h_mean=funding_mean,
        open_interest_usd=oi,
        open_interest_z30=oi_z,
        long_short_ratio=lsr,
    )


async def load_derivatives_history(
    session, symbol: str, as_of: datetime, lookback_days: int = 60
) -> pd.DataFrame:
    """Load (time, field, value) for derivatives metrics. Tolerant of missing table."""
    try:
        from sqlalchemy import text

        since = as_of - timedelta(days=lookback_days)
        stmt = text(
            """
            SELECT time, field, value
            FROM derivatives_metrics
            WHERE symbol = :symbol AND time >= :since AND time <= :as_of
            ORDER BY time ASC
            """
        )
        res = await session.execute(
            stmt, {"symbol": symbol, "since": since, "as_of": as_of}
        )
        rows = res.all()
    except Exception:
        return pd.DataFrame(columns=["time", "field", "value"])
    if not rows:
        return pd.DataFrame(columns=["time", "field", "value"])
    return pd.DataFrame(rows, columns=["time", "field", "value"])
