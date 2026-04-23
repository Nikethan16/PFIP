"""Technical features computed from OHLCV.

Pure function: takes a price DataFrame indexed (or with a column) by time with
OHLCV columns and returns a DataFrame of the canonical feature set.

Canonical features:
    rsi_14, macd, macd_signal, macd_hist, atr_14, return_7d, volatility_30d
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Prefer the actively-maintained `ta` library (pure Python, wheels for 3.12).
# Fallback to manual implementations if `ta` is unavailable so the feature
# pipeline still runs in minimal environments.
try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD
    from ta.volatility import AverageTrueRange

    _TA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TA_AVAILABLE = False


_FEATURE_COLS = (
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "return_7d",
    "volatility_30d",
)


def _rsi_manual(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI without external deps."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd_manual(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr_manual(
    high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14
) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute canonical technical features from an OHLCV DataFrame.

    Expected columns (case-insensitive): ``open``, ``high``, ``low``, ``close``,
    ``volume``. Time should be the index or a ``time`` column; the result
    preserves the input's row ordering.

    Args:
        df: OHLCV DataFrame with at least ``high``, ``low``, ``close``.

    Returns:
        A DataFrame indexed like the input with columns listed in
        ``_FEATURE_COLS``. Warm-up periods produce ``NaN``.
    """
    if df.empty:
        return pd.DataFrame(columns=list(_FEATURE_COLS))

    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    for col in ("high", "low", "close"):
        if col not in work.columns:
            raise ValueError(f"compute_features: missing required column '{col}'")

    high = pd.to_numeric(work["high"], errors="coerce")
    low = pd.to_numeric(work["low"], errors="coerce")
    close = pd.to_numeric(work["close"], errors="coerce")

    out = pd.DataFrame(index=work.index)

    if _TA_AVAILABLE:
        out["rsi_14"] = RSIIndicator(close=close, window=14).rsi()
        macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        out["macd"] = macd_ind.macd()
        out["macd_signal"] = macd_ind.macd_signal()
        out["macd_hist"] = macd_ind.macd_diff()
        out["atr_14"] = AverageTrueRange(
            high=high, low=low, close=close, window=14
        ).average_true_range()
    else:
        out["rsi_14"] = _rsi_manual(close, length=14)
        macd_line, signal_line, hist = _macd_manual(close)
        out["macd"] = macd_line
        out["macd_signal"] = signal_line
        out["macd_hist"] = hist
        out["atr_14"] = _atr_manual(high, low, close, length=14)

    # 7-day log return
    out["return_7d"] = np.log(close / close.shift(7))

    # 30-day realized volatility (std of daily log returns, not annualized)
    log_ret = np.log(close / close.shift(1))
    out["volatility_30d"] = log_ret.rolling(window=30).std()

    return out[list(_FEATURE_COLS)]
