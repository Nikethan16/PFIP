"""Cross-asset correlation features.

Rolling 30-day return-correlation between an asset and a small set of
benchmarks (BTC vs SPY, BTC vs gold, target vs bond index, target vs DXY).
Caller passes in the relevant close-price panels; we compute correlations on
the intersection of dates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# Canonical pairs to track. Keys are output feature names.
DEFAULT_PAIRS: dict[str, tuple[str, str]] = {
    "corr_btc_spy_30d": ("BTC/USD", "SPY"),
    "corr_btc_gold_30d": ("BTC/USD", "GLD"),
    "corr_target_dxy_30d": ("__target__", "DX-Y.NYB"),
    "corr_target_us10y_30d": ("__target__", "^TNX"),
}


CROSS_ASSET_FEATURE_COLS: tuple[str, ...] = (
    "corr_btc_spy_30d",
    "corr_btc_gold_30d",
    "corr_target_dxy_30d",
    "corr_target_us10y_30d",
)


@dataclass(frozen=True)
class CrossAssetSnapshot:
    """Cross-asset correlation snapshot for one target symbol."""

    target_symbol: str
    as_of: datetime
    corr_btc_spy_30d: float | None
    corr_btc_gold_30d: float | None
    corr_target_dxy_30d: float | None
    corr_target_us10y_30d: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "corr_btc_spy_30d": self.corr_btc_spy_30d,
            "corr_btc_gold_30d": self.corr_btc_gold_30d,
            "corr_target_dxy_30d": self.corr_target_dxy_30d,
            "corr_target_us10y_30d": self.corr_target_us10y_30d,
        }


def empty_snapshot(target_symbol: str, as_of: datetime) -> CrossAssetSnapshot:
    return CrossAssetSnapshot(
        target_symbol=target_symbol,
        as_of=as_of,
        corr_btc_spy_30d=None,
        corr_btc_gold_30d=None,
        corr_target_dxy_30d=None,
        corr_target_us10y_30d=None,
    )


def _rolling_corr_last(a: pd.Series, b: pd.Series, window: int = 30) -> float | None:
    if a is None or b is None or a.empty or b.empty:
        return None
    al = a.astype(float).pct_change()
    bl = b.astype(float).pct_change()
    df = pd.concat([al, bl], axis=1, join="inner").dropna()
    if len(df) < max(5, window // 2):
        return None
    tail = df.iloc[-window:]
    if tail.iloc[:, 0].std(ddof=1) == 0 or tail.iloc[:, 1].std(ddof=1) == 0:
        return None
    return float(tail.iloc[:, 0].corr(tail.iloc[:, 1]))


def derive_from_panel(
    closes: Mapping[str, pd.Series],
    target_symbol: str,
    as_of: datetime,
) -> CrossAssetSnapshot:
    """Compute cross-asset correlations.

    ``closes`` keys are symbols (e.g. ``BTC/USD``, ``SPY``, ``GLD``,
    ``DX-Y.NYB``, ``^TNX``) plus the target symbol itself.
    """

    def _get(sym: str) -> pd.Series:
        s = closes.get(sym, pd.Series(dtype=float))
        if s.empty:
            return s
        try:
            return s[s.index <= as_of]
        except Exception:
            return s

    target = _get(target_symbol)

    return CrossAssetSnapshot(
        target_symbol=target_symbol,
        as_of=as_of,
        corr_btc_spy_30d=_rolling_corr_last(_get("BTC/USD"), _get("SPY"), 30),
        corr_btc_gold_30d=_rolling_corr_last(_get("BTC/USD"), _get("GLD"), 30),
        corr_target_dxy_30d=_rolling_corr_last(target, _get("DX-Y.NYB"), 30),
        corr_target_us10y_30d=_rolling_corr_last(target, _get("^TNX"), 30),
    )


async def load_cross_asset_panel(
    session, target_symbol: str, as_of: datetime, lookback_days: int = 90
) -> dict[str, pd.Series]:
    """Load close series for every symbol involved in the cross-asset pairs."""
    try:
        from sqlalchemy import select

        from pfip.models.ohlcv import OHLCVRow
    except Exception:  # pragma: no cover
        return {}

    symbols = {target_symbol}
    for a, b in DEFAULT_PAIRS.values():
        symbols.add(target_symbol if a == "__target__" else a)
        symbols.add(target_symbol if b == "__target__" else b)

    since = as_of - timedelta(days=lookback_days)
    out: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            stmt = (
                select(OHLCVRow.time, OHLCVRow.close)
                .where(
                    OHLCVRow.symbol == sym,
                    OHLCVRow.time >= since,
                    OHLCVRow.time <= as_of,
                )
                .order_by(OHLCVRow.time.asc())
            )
            res = await session.execute(stmt)
            rows = res.all()
        except Exception:
            rows = []
        if rows:
            df = pd.DataFrame(rows, columns=["time", "close"])
            df["close"] = df["close"].astype(float)
            out[sym] = df.set_index("time")["close"]
        else:
            out[sym] = pd.Series(dtype=float)
    return out
