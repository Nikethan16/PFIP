"""Macro features: VIX, DXY, 10Y yield, yield-curve spread, USD/INR.

Derived from OHLCV rows for the canonical macro symbols. The ingest agent
populates these via the FRED / Stooq / yfinance pipelines (Source enum).

Symbols (canonical):
    VIX     -> ``^VIX`` (yfinance)
    DXY     -> ``DX-Y.NYB`` (yfinance) or ``DTWEXBGS`` (FRED)
    UST10Y  -> ``^TNX`` (yfinance) or ``DGS10`` (FRED)
    UST2Y   -> ``^IRX`` (yfinance) or ``DGS2`` (FRED)
    USDINR  -> ``USDINR=X`` (yfinance) or ``DEXINUS`` (FRED)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


MACRO_FEATURE_COLS: tuple[str, ...] = (
    "vix_level",
    "vix_change_5d",
    "dxy_level",
    "dxy_change_5d",
    "us10y_yield",
    "yield_curve_2s10s",
    "usdinr_level",
    "usdinr_change_5d",
)


MACRO_SYMBOLS = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "us10y": "^TNX",
    "us2y": "^IRX",
    "usdinr": "USDINR=X",
}


@dataclass(frozen=True)
class MacroSnapshot:
    """A PIT bundle of macro features (one per as-of timestamp)."""

    as_of: datetime
    vix_level: float | None
    vix_change_5d: float | None
    dxy_level: float | None
    dxy_change_5d: float | None
    us10y_yield: float | None
    yield_curve_2s10s: float | None
    usdinr_level: float | None
    usdinr_change_5d: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "vix_level": self.vix_level,
            "vix_change_5d": self.vix_change_5d,
            "dxy_level": self.dxy_level,
            "dxy_change_5d": self.dxy_change_5d,
            "us10y_yield": self.us10y_yield,
            "yield_curve_2s10s": self.yield_curve_2s10s,
            "usdinr_level": self.usdinr_level,
            "usdinr_change_5d": self.usdinr_change_5d,
        }


def empty_snapshot(as_of: datetime) -> MacroSnapshot:
    return MacroSnapshot(
        as_of=as_of,
        vix_level=None,
        vix_change_5d=None,
        dxy_level=None,
        dxy_change_5d=None,
        us10y_yield=None,
        yield_curve_2s10s=None,
        usdinr_level=None,
        usdinr_change_5d=None,
    )


def _pct_change(series: pd.Series, n: int) -> float | None:
    s = series.dropna().astype(float)
    if len(s) <= n:
        return None
    try:
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0)
    except Exception:
        return None


def derive_from_panel(
    closes: dict[str, pd.Series], as_of: datetime
) -> MacroSnapshot:
    """Take a dict of ``{macro_key: close_series}`` and build a snapshot.

    Each series must be ascending in time and cover at least the last 10 days
    for the change features to be available.
    """
    def _last(key: str) -> float | None:
        s = closes.get(key)
        if s is None or s.empty:
            return None
        s = s[s.index <= as_of] if hasattr(s.index, "tz_convert") or hasattr(s.index, "tz_localize") else s
        if s.empty:
            return None
        return float(s.dropna().iloc[-1])

    vix = _last("vix")
    vix_chg = _pct_change(closes.get("vix", pd.Series(dtype=float)), 5)
    dxy = _last("dxy")
    dxy_chg = _pct_change(closes.get("dxy", pd.Series(dtype=float)), 5)
    us10y = _last("us10y")
    us2y = _last("us2y")
    yield_curve = (us10y - us2y) if (us10y is not None and us2y is not None) else None
    usdinr = _last("usdinr")
    usdinr_chg = _pct_change(closes.get("usdinr", pd.Series(dtype=float)), 5)

    return MacroSnapshot(
        as_of=as_of,
        vix_level=vix,
        vix_change_5d=vix_chg,
        dxy_level=dxy,
        dxy_change_5d=dxy_chg,
        us10y_yield=us10y,
        yield_curve_2s10s=yield_curve,
        usdinr_level=usdinr,
        usdinr_change_5d=usdinr_chg,
    )


async def load_macro_closes(
    session, as_of: datetime, lookback_days: int = 60
) -> dict[str, pd.Series]:
    """Load close-price series for each macro symbol from the OHLCV table.

    Returns a dict keyed by short macro name (``vix``, ``dxy``, ``us10y``,
    ``us2y``, ``usdinr``) → close pd.Series indexed by ``time``.
    """
    try:
        from sqlalchemy import select

        from pfip.models.ohlcv import OHLCVRow
    except Exception:  # pragma: no cover
        return {}

    since = as_of - timedelta(days=lookback_days)
    out: dict[str, pd.Series] = {}
    for key, symbol in MACRO_SYMBOLS.items():
        try:
            stmt = (
                select(OHLCVRow.time, OHLCVRow.close)
                .where(
                    OHLCVRow.symbol == symbol,
                    OHLCVRow.time >= since,
                    OHLCVRow.time <= as_of,
                )
                .order_by(OHLCVRow.time.asc())
            )
            res = await session.execute(stmt)
            rows = res.all()
        except Exception:
            rows = []
        if not rows:
            out[key] = pd.Series(dtype=float)
            continue
        df = pd.DataFrame(rows, columns=["time", "close"])
        df["close"] = df["close"].astype(float)
        out[key] = df.set_index("time")["close"]
    return out
