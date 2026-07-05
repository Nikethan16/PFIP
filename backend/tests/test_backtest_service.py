"""Pure-function coverage for the on-demand backtest service
(pfip.backtest.service). DB-backed paths are exercised via the API integration
tests; here we lock the equity-curve builder + market-kind mapping.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pfip.backtest import service as S
from pfip.backtest.vectorbt_engine import _BENCHMARKS, transaction_cost_bps


def test_market_kind_mapping():
    assert S._market_kind("BTC-USDT") == "crypto"
    assert S._market_kind("ETH-USD") == "crypto"
    assert S._market_kind("RELIANCE.NS") == "equity"
    assert S._market_kind("SPY") == "equity"


def _synth_df(n: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    # Gentle uptrend + noise so a long strategy produces a real, finite curve.
    rng = np.random.default_rng(0)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1_000}, index=idx
    )


def test_equity_curve_is_bounded_and_ends_on_last_bar():
    df = _synth_df()
    curve = S._equity_curve(df, _BENCHMARKS["ma_50_200"], transaction_cost_bps("equity"))
    assert 0 < len(curve) <= 301  # downsampled to ~300 points + final
    # Every point is a {date, equity>0} and monotonic dates.
    dates = [p["date"] for p in curve]
    assert dates == sorted(dates)
    assert all(p["equity"] > 0 for p in curve)
    # Ends on the last bar's date.
    assert curve[-1]["date"] == df.index[-1].date().isoformat()


def test_equity_curve_empty_on_empty_df():
    assert S._equity_curve(pd.DataFrame({"close": []}), _BENCHMARKS["buy_hold"], 5.0) == []
