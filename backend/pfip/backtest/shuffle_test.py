"""Shuffle / leakage test.

Wraps :func:`pfip.backtest.vectorbt_engine.lookahead_test` and adds a richer
``run_shuffle_test`` that returns both the boolean pass-fail and the
distribution of shuffled Sharpes (useful for the tearsheet / debugger).

Spec wording: "shuffle target, retrain, performance should collapse". The
engine implements this by shuffling the bar returns (which directly translate
into shuffled forward returns) and re-evaluating the strategy. A clean
strategy's Sharpe collapses to the market Sharpe; a leaking strategy retains
its edge because the shuffle preserves the future-info it was reading.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import (
    BacktestStrategy,
    _apply_strategy,
    _sharpe,
    lookahead_test as _engine_lookahead_test,
    transaction_cost_bps,
)


@dataclass
class ShuffleTestResult:
    ok: bool
    original_sharpe: float
    shuffled_sharpes: list[float]
    n_shuffles: int

    def summary(self) -> dict[str, float | int | bool]:
        return {
            "ok": self.ok,
            "original_sharpe": self.original_sharpe,
            "n_shuffles": self.n_shuffles,
            "shuffled_mean_sharpe": float(np.mean(self.shuffled_sharpes))
            if self.shuffled_sharpes
            else float("nan"),
            "shuffled_max_sharpe": float(np.max(self.shuffled_sharpes))
            if self.shuffled_sharpes
            else float("nan"),
        }


def run_shuffle_test(
    strategy: BacktestStrategy,
    df: pd.DataFrame,
    *,
    market_kind: str = "crypto",
    n_shuffles: int = 20,
    tolerance: float = 0.2,
    rng_seed: int = 13,
) -> ShuffleTestResult:
    """Run the shuffle test and return both verdict + distribution.

    ``ok = True`` iff fewer than ``tolerance`` fraction of shuffled paths
    strictly exceed the original Sharpe.
    """
    cost_bps = transaction_cost_bps(market_kind)
    try:
        real_ret, _ = _apply_strategy(df, strategy, cost_bps)
        real_sharpe = _sharpe(real_ret)
    except Exception:
        return ShuffleTestResult(False, float("nan"), [], n_shuffles)

    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    rets = close.pct_change().fillna(0.0).to_numpy()
    base = float(close.iloc[0]) if len(close) else 1.0
    rng = np.random.default_rng(rng_seed)
    shuffled_sharpes: list[float] = []

    for _ in range(n_shuffles):
        shuf = rets.copy()
        rng.shuffle(shuf)
        shuffled_close = np.concatenate([[base], (1.0 + shuf[1:]).cumprod() * base])[: len(df)]
        sh_df = df.copy()
        sh_df["close"] = shuffled_close
        try:
            ret, _ = _apply_strategy(sh_df, strategy, cost_bps)
            shuffled_sharpes.append(_sharpe(ret))
        except Exception:
            continue

    if not shuffled_sharpes:
        return ShuffleTestResult(False, real_sharpe, [], n_shuffles)

    # Number of shuffles strictly beating the original.
    hits = sum(1 for s in shuffled_sharpes if s > real_sharpe + 0.1)
    ok = (hits / len(shuffled_sharpes)) <= tolerance

    # Also fall back to the engine's stricter check (constant-position guard).
    engine_ok = _engine_lookahead_test(
        strategy, df, market_kind=market_kind, n_shuffles=min(10, n_shuffles)
    )
    ok = ok and engine_ok

    return ShuffleTestResult(
        ok=ok,
        original_sharpe=real_sharpe,
        shuffled_sharpes=shuffled_sharpes,
        n_shuffles=len(shuffled_sharpes),
    )
