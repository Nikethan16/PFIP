"""On-chain feature derivation for crypto.

Computes MVRV (market-value-to-realised-value), exchange netflow z-score, and
hash-rate-derived features (24h delta + 30d z-score) from rows in the optional
``onchain_metrics`` table. If that table doesn't exist yet (still M3-ingest
work) the helpers return ``None`` for every field — callers carry on.

Hash-rate features only apply to PoW chains (BTC). For ETH/SOL the relevant
fields will simply be ``None``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Canonical field names we read out of the on-chain store. The crypto ingest
# pipelines (glassnode-equivalent / blockchair) normalise to these.
FIELD_MARKET_VALUE = "market_value"
FIELD_REALISED_VALUE = "realised_value"
FIELD_EXCHANGE_NETFLOW = "exchange_netflow"
FIELD_HASH_RATE = "hash_rate"
FIELD_ACTIVE_ADDRESSES = "active_addresses"

ON_CHAIN_FEATURE_COLS: tuple[str, ...] = (
    "mvrv",
    "exchange_netflow_z30",
    "hash_rate_delta_24h",
    "hash_rate_z30",
    "active_addresses_z30",
)


@dataclass(frozen=True)
class OnChainSnapshot:
    """One PIT bundle of on-chain features for a crypto symbol."""

    symbol: str
    as_of: datetime
    mvrv: float | None
    exchange_netflow_z30: float | None
    hash_rate_delta_24h: float | None
    hash_rate_z30: float | None
    active_addresses_z30: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "mvrv": self.mvrv,
            "exchange_netflow_z30": self.exchange_netflow_z30,
            "hash_rate_delta_24h": self.hash_rate_delta_24h,
            "hash_rate_z30": self.hash_rate_z30,
            "active_addresses_z30": self.active_addresses_z30,
        }


def empty_snapshot(symbol: str, as_of: datetime) -> OnChainSnapshot:
    return OnChainSnapshot(
        symbol=symbol,
        as_of=as_of,
        mvrv=None,
        exchange_netflow_z30=None,
        hash_rate_delta_24h=None,
        hash_rate_z30=None,
        active_addresses_z30=None,
    )


def _z_score(series: pd.Series, window: int = 30) -> float | None:
    s = series.dropna().astype(float)
    if len(s) < window // 2:
        return None
    tail = s.iloc[-window:]
    if len(tail) < 2:
        return None
    std = tail.std(ddof=1)
    if std == 0 or np.isnan(std):
        return None
    return float((tail.iloc[-1] - tail.mean()) / std)


def derive_from_history(
    history: pd.DataFrame,
    symbol: str,
    as_of: datetime,
) -> OnChainSnapshot:
    """Compute the canonical on-chain features from a long-form history.

    ``history`` is expected to have columns ``time``, ``field``, ``value`` and
    cover at least 30 days for z-scores to be meaningful. Rows after ``as_of``
    are dropped (PIT discipline).
    """
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
        if s.empty:
            return None
        return float(s.iloc[-1])

    mv = _latest(FIELD_MARKET_VALUE)
    rv = _latest(FIELD_REALISED_VALUE)
    mvrv = (mv / rv) if (mv is not None and rv) else None

    netflow_z = (
        _z_score(wide[FIELD_EXCHANGE_NETFLOW], 30)
        if FIELD_EXCHANGE_NETFLOW in wide.columns
        else None
    )

    hr_delta = None
    hr_z = None
    if FIELD_HASH_RATE in wide.columns:
        hr = wide[FIELD_HASH_RATE].dropna()
        if len(hr) >= 2:
            hr_delta = float((hr.iloc[-1] / hr.iloc[-2]) - 1.0)
        hr_z = _z_score(hr, 30)

    aa_z = (
        _z_score(wide[FIELD_ACTIVE_ADDRESSES], 30)
        if FIELD_ACTIVE_ADDRESSES in wide.columns
        else None
    )

    return OnChainSnapshot(
        symbol=symbol,
        as_of=as_of,
        mvrv=mvrv,
        exchange_netflow_z30=netflow_z,
        hash_rate_delta_24h=hr_delta,
        hash_rate_z30=hr_z,
        active_addresses_z30=aa_z,
    )


async def load_on_chain_history(
    session, symbol: str, as_of: datetime, lookback_days: int = 90
) -> pd.DataFrame:
    """Load on-chain metric rows for ``symbol`` from the DB.

    Tolerant of a missing ``onchain_metrics`` table — returns an empty frame.
    """
    try:
        from sqlalchemy import text

        since = as_of - timedelta(days=lookback_days)
        stmt = text("""
            SELECT time, field, value
            FROM onchain_metrics
            WHERE symbol = :symbol AND time >= :since AND time <= :as_of
            ORDER BY time ASC
            """)
        res = await session.execute(stmt, {"symbol": symbol, "since": since, "as_of": as_of})
        rows = res.all()
    except Exception:
        # A missing ``onchain_metrics`` table raises UndefinedTable, which aborts
        # the current Postgres transaction. Roll back so the shared session stays
        # usable for the rest of the feature pipeline (derivatives/macro/upserts).
        try:
            await session.rollback()
        except Exception:
            pass
        return pd.DataFrame(columns=["time", "field", "value"])

    if not rows:
        return pd.DataFrame(columns=["time", "field", "value"])
    return pd.DataFrame(rows, columns=["time", "field", "value"])
