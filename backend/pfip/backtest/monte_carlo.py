"""Monte-Carlo robustness checks on backtest trade returns.

Wraps :func:`pfip.backtest.vectorbt_engine.run_monte_carlo` and adds a richer
summary (5th/50th/95th-percentile Sharpe, max-DD distribution, hit-rate band)
that the tearsheet / UI render directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from pfip.backtest.vectorbt_engine import _max_drawdown, _sharpe


@dataclass(frozen=True)
class MonteCarloSummary:
    n_sims: int
    block_size: int
    sharpe_p5: float
    sharpe_p50: float
    sharpe_p95: float
    max_dd_p5: float
    max_dd_p50: float
    max_dd_p95: float
    hit_rate_mean: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n_sims": self.n_sims,
            "block_size": self.block_size,
            "sharpe_p5": self.sharpe_p5,
            "sharpe_p50": self.sharpe_p50,
            "sharpe_p95": self.sharpe_p95,
            "max_dd_p5": self.max_dd_p5,
            "max_dd_p50": self.max_dd_p50,
            "max_dd_p95": self.max_dd_p95,
            "hit_rate_mean": self.hit_rate_mean,
        }


def block_bootstrap(
    trade_returns: pd.Series,
    *,
    n_sims: int = 1000,
    block_size: int = 5,
    rng_seed: int = 7,
) -> MonteCarloSummary:
    """Block-bootstrap a trade-return series and summarise the distribution.

    ``trade_returns`` is the per-trade fractional return (e.g. ``+0.012`` for a
    +1.2% trade).
    """
    r = np.asarray(trade_returns.dropna(), dtype=float)
    n = len(r)
    if n < 2:
        nan = float("nan")
        return MonteCarloSummary(
            n_sims=n_sims,
            block_size=block_size,
            sharpe_p5=nan,
            sharpe_p50=nan,
            sharpe_p95=nan,
            max_dd_p5=nan,
            max_dd_p50=nan,
            max_dd_p95=nan,
            hit_rate_mean=nan,
        )

    rng = np.random.default_rng(rng_seed)
    n_blocks = max(1, n // block_size)
    sharpes = np.empty(n_sims, dtype=float)
    max_dds = np.empty(n_sims, dtype=float)
    hits = np.empty(n_sims, dtype=float)

    for i in range(n_sims):
        starts = rng.integers(0, max(1, n - block_size + 1), size=n_blocks)
        sim = np.concatenate([r[s : s + block_size] for s in starts])[:n]
        sim_series = pd.Series(sim)
        sharpes[i] = _sharpe(sim_series)
        max_dds[i] = _max_drawdown(sim_series)
        hits[i] = float((sim > 0).mean())

    return MonteCarloSummary(
        n_sims=n_sims,
        block_size=block_size,
        sharpe_p5=float(np.percentile(sharpes, 5)),
        sharpe_p50=float(np.percentile(sharpes, 50)),
        sharpe_p95=float(np.percentile(sharpes, 95)),
        max_dd_p5=float(np.percentile(max_dds, 5)),
        max_dd_p50=float(np.percentile(max_dds, 50)),
        max_dd_p95=float(np.percentile(max_dds, 95)),
        hit_rate_mean=float(hits.mean()),
    )
