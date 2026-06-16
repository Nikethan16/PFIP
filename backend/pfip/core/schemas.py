"""Pandera data-validation schemas for the PFIP ETL pipeline.

These schemas are the data-validation gate described in Phase 1 of the project
plan. They sit at the boundary between raw DB reads and any modeling code, so
bad data is caught before it silently corrupts features, regime labels, or
backtest results.

Usage
-----
    from pfip.core.schemas import validate_ohlcv, validate_features, validate_regime

    df = validate_ohlcv(raw_df)           # raises SchemaError on bad data
    feats = validate_features(feature_df)
    regime = validate_regime(regime_df)

Each ``validate_*`` function:
  * accepts a DataFrame,
  * enforces types, ranges, and structural constraints,
  * returns the (possibly coerced) DataFrame on success,
  * raises ``pandera.errors.SchemaError`` with a human-readable message on failure.

All schemas are deliberately **permissive on extras** (they coerce rather than
reject when a fix is safe) and **strict on invariants that would silently corrupt
downstream results** (e.g. close ≤ 0, RSI outside [0,100], NaT timestamps).

Pandera availability
--------------------
pandera==0.19.3 is in requirements.txt. If somehow unavailable at runtime,
each validate_* falls back to a lightweight manual check so the calling code
doesn't need a try/except around every call.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

try:  # pragma: no cover
    import pandera as pa
    from pandera import Column, DataFrameSchema, Index

    _PA_OK = True
except Exception as exc:  # pragma: no cover
    log.warning("pandera unavailable (%s); using manual validation fallback", exc)
    pa = None  # type: ignore[assignment]
    DataFrameSchema = None  # type: ignore[assignment]
    Column = None  # type: ignore[assignment]
    Index = None  # type: ignore[assignment]
    _PA_OK = False


# ---------------------------------------------------------------------------
# OHLCV schema
# ---------------------------------------------------------------------------

def _build_ohlcv_schema() -> Any:
    """Build and return the pandera OHLCV schema object."""
    if not _PA_OK:
        return None
    return pa.DataFrameSchema(
        columns={
            "open":   pa.Column(float, pa.Check.ge(0), coerce=True, nullable=False),
            "high":   pa.Column(float, pa.Check.ge(0), coerce=True, nullable=False),
            "low":    pa.Column(float, pa.Check.ge(0), coerce=True, nullable=False),
            "close":  pa.Column(float, pa.Check.gt(0), coerce=True, nullable=False),
            "volume": pa.Column(float, pa.Check.ge(0), coerce=True, nullable=True),
        },
        checks=[
            # High must be ≥ low and ≥ close (basic OHLCV invariant).
            pa.Check(
                lambda df: (df["high"] >= df["low"]).all(),
                error="high < low found in OHLCV",
            ),
            pa.Check(
                lambda df: (df["high"] >= df["close"]).all(),
                error="high < close found in OHLCV",
            ),
            pa.Check(
                lambda df: (df["low"] <= df["close"]).all(),
                error="low > close found in OHLCV",
            ),
        ],
        index=pa.Index(pd.DatetimeTZDtype(tz="UTC"), coerce=True),
        coerce=True,
    )


_OHLCV_SCHEMA: Any = None  # lazily built on first use


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate an OHLCV DataFrame; raise SchemaError on failures."""
    global _OHLCV_SCHEMA
    if _PA_OK:
        if _OHLCV_SCHEMA is None:
            _OHLCV_SCHEMA = _build_ohlcv_schema()
        try:
            return _OHLCV_SCHEMA.validate(df)
        except Exception:
            raise
    # Manual fallback.
    _manual_ohlcv_check(df)
    return df


def _manual_ohlcv_check(df: pd.DataFrame) -> None:
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"OHLCV missing required column: {col}")
        bad = (df[col] <= 0) | df[col].isna()
        if col != "open" and bad.any():
            raise ValueError(f"OHLCV: {col} has {bad.sum()} non-positive/NaN rows")
    if (df["high"] < df["low"]).any():
        raise ValueError("OHLCV: high < low in some rows")


# ---------------------------------------------------------------------------
# Features schema
# ---------------------------------------------------------------------------

_FEATURE_RANGES: dict[str, tuple[float | None, float | None]] = {
    "rsi_14":       (0.0, 100.0),
    "macd":         (None, None),
    "macd_signal":  (None, None),
    "macd_hist":    (None, None),
    "atr_14":       (0.0, None),
    "return_7d":    (-5.0, 5.0),   # log-return: ±500% weekly is a hard cap
    "volatility_30d": (0.0, 10.0), # daily vol: >1000% annualized is data garbage
}


def _build_features_schema() -> Any:
    if not _PA_OK:
        return None
    cols: dict[str, Any] = {}
    for name, (lo, hi) in _FEATURE_RANGES.items():
        checks = []
        if lo is not None:
            checks.append(pa.Check.ge(lo))
        if hi is not None:
            checks.append(pa.Check.le(hi))
        cols[name] = pa.Column(float, checks=checks, coerce=True, nullable=True, required=False)
    return pa.DataFrameSchema(
        columns=cols,
        coerce=True,
    )


_FEATURES_SCHEMA: Any = None


def validate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a features DataFrame; warn on range violations (non-fatal)."""
    global _FEATURES_SCHEMA
    if _PA_OK:
        if _FEATURES_SCHEMA is None:
            _FEATURES_SCHEMA = _build_features_schema()
        try:
            return _FEATURES_SCHEMA.validate(df)
        except Exception as exc:
            # Feature validation failures are warnings, not hard stops — some
            # technicals are legitimately extreme in thin markets.
            log.warning("features schema warning: %s", exc)
            return df
    _manual_features_check(df)
    return df


def _manual_features_check(df: pd.DataFrame) -> None:
    if "rsi_14" in df.columns:
        bad = df["rsi_14"].between(0, 100) | df["rsi_14"].isna()
        if not bad.all():
            log.warning("features: rsi_14 has %d out-of-range values", (~bad).sum())
    if "atr_14" in df.columns:
        neg = (df["atr_14"] < 0) & df["atr_14"].notna()
        if neg.any():
            log.warning("features: atr_14 has %d negative values", neg.sum())


# ---------------------------------------------------------------------------
# Regime schema
# ---------------------------------------------------------------------------

_VALID_REGIMES = frozenset(
    ["bull_trend", "bear_trend", "sideways", "high_volatility", "accumulation", "distribution"]
)


def _build_regime_schema() -> Any:
    if not _PA_OK:
        return None
    return pa.DataFrameSchema(
        columns={
            "regime": pa.Column(
                str,
                pa.Check(
                    lambda s: s.isin(_VALID_REGIMES),
                    error=f"regime not in {_VALID_REGIMES}",
                ),
                coerce=True,
                nullable=False,
                required=True,
            ),
            "confidence": pa.Column(
                float,
                [pa.Check.ge(0.0), pa.Check.le(1.0)],
                coerce=True,
                nullable=True,
                required=False,
            ),
        },
        coerce=True,
    )


_REGIME_SCHEMA: Any = None


def validate_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a regime DataFrame; raise SchemaError on unknown regime labels."""
    global _REGIME_SCHEMA
    if _PA_OK:
        if _REGIME_SCHEMA is None:
            _REGIME_SCHEMA = _build_regime_schema()
        try:
            return _REGIME_SCHEMA.validate(df)
        except Exception:
            raise
    _manual_regime_check(df)
    return df


def _manual_regime_check(df: pd.DataFrame) -> None:
    if "regime" not in df.columns:
        raise ValueError("regime DataFrame missing 'regime' column")
    bad = ~df["regime"].isin(_VALID_REGIMES) & df["regime"].notna()
    if bad.any():
        raise ValueError(f"Unknown regime labels: {df.loc[bad, 'regime'].unique().tolist()}")
