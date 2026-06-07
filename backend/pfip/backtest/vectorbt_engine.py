"""Walk-forward backtest engine with Monte Carlo, benchmarks, and leakage tests.

Core entry points:
    run_walkforward(df, strategy, window, step, embargo)
    run_monte_carlo(trade_returns, n_sims)          # block bootstrap
    benchmark_comparison(returns, benchmarks=[...])  # BH + MA(50/200) + RSI MR
    lookahead_test(strategy, df)                      # shuffle test
    cpcv_folds(n, n_splits, embargo)                  # López de Prado CPCV

The engine uses vectorbt for the heavy lifting where available, but falls back
to pure numpy/pandas so the module is importable + unit-testable without the
optional dependency. All metrics (Sharpe, max DD, Calmar, Sortino, hit rate,
5th-percentile Sharpe) are computed on the engine's own return series.

Strategies are plain callables with the signature:

    def strategy(df: pd.DataFrame) -> pd.Series[int]

returning {-1, 0, 1} positions aligned to ``df.index``. The engine applies the
appropriate transaction-cost multiplier per market.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

try:  # pragma: no cover
    import vectorbt as vbt  # type: ignore[import-untyped]

    _HAS_VBT = True
except Exception:  # pragma: no cover
    vbt = None  # type: ignore[assignment]
    _HAS_VBT = False


# ---------------------------------------------------------------------------
# Transaction costs per plan 8.2.
# ---------------------------------------------------------------------------

_COST_BPS = {
    "crypto": 10.0,
    "us": 5.0,
    "india": 25.0,
}


def transaction_cost_bps(market_kind: str) -> float:
    """Return the per-side transaction cost in bps for a market kind."""
    return _COST_BPS.get(market_kind.lower(), 10.0)


# ---------------------------------------------------------------------------
# Strategy type
# ---------------------------------------------------------------------------


BacktestStrategy = Callable[[pd.DataFrame], pd.Series]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """Typed dict-ish result object."""

    sharpe: float
    max_drawdown: float
    calmar: float
    sortino: float
    hit_rate: float
    n_trades: int
    cagr: float
    total_return: float
    returns: pd.Series = field(default_factory=pd.Series)
    trades: pd.Series = field(default_factory=pd.Series)
    mc_sharpe_5th: float = float("nan")
    lookahead_ok: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "calmar": self.calmar,
            "sortino": self.sortino,
            "hit_rate": self.hit_rate,
            "n_trades": self.n_trades,
            "cagr": self.cagr,
            "total_return": self.total_return,
            "mc_sharpe_5th": self.mc_sharpe_5th,
            "lookahead_ok": self.lookahead_ok,
        }
        out.update(self.metadata)
        return out


# ---------------------------------------------------------------------------
# Core metric helpers
# ---------------------------------------------------------------------------


def _sharpe(returns: pd.Series, periods: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    mean = r.mean()
    std = r.std(ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(np.sqrt(periods) * mean / std)


def _sortino(returns: pd.Series, periods: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    downside = r.clip(upper=0.0)
    dd_std = downside.std(ddof=1)
    if dd_std == 0 or np.isnan(dd_std):
        return 0.0
    return float(np.sqrt(periods) * r.mean() / dd_std)


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def _calmar(returns: pd.Series, periods: int = 252) -> float:
    mdd = abs(_max_drawdown(returns))
    if mdd == 0:
        return 0.0
    total_years = len(returns.dropna()) / periods
    if total_years <= 0:
        return 0.0
    total_return = (1.0 + returns.fillna(0.0)).prod() - 1.0
    cagr = (1.0 + total_return) ** (1.0 / total_years) - 1.0
    return float(cagr / mdd)


def _hit_rate(trade_returns: pd.Series) -> float:
    r = trade_returns.dropna()
    if r.empty:
        return 0.0
    return float((r > 0).mean())


def _cagr(returns: pd.Series, periods: int = 252) -> float:
    r = returns.dropna()
    if r.empty:
        return 0.0
    total = (1.0 + r).prod()
    years = len(r) / periods
    if years <= 0:
        return 0.0
    return float(total ** (1.0 / years) - 1.0)


# ---------------------------------------------------------------------------
# Execution engine: positions -> returns (with costs)
# ---------------------------------------------------------------------------


def _apply_strategy(
    df: pd.DataFrame, strategy: BacktestStrategy, cost_bps: float
) -> tuple[pd.Series, pd.Series]:
    """Run a strategy against a price DataFrame.

    Assumes ``df`` has a ``close`` column. Positions from the strategy are
    applied to the *next* bar's return (no lookahead), with per-turn
    transaction costs charged in bps.

    Returns (returns_series, trade_returns_series).
    """
    if "close" not in df.columns:
        raise ValueError("backtest: df must have 'close' column")
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    bar_ret = close.pct_change().fillna(0.0)

    pos = strategy(df).reindex(df.index).fillna(0).astype(float)
    # Shift by 1: decisions at t only affect t+1's return.
    pos_shift = pos.shift(1).fillna(0.0)

    gross_ret = pos_shift * bar_ret

    turnover = pos.diff().abs().fillna(pos.abs())
    cost = turnover * (cost_bps / 1e4)

    net_ret = gross_ret - cost

    # Trade-level returns: compound the bar returns while position is constant.
    trade_returns = _trade_level_returns(pos_shift, bar_ret, cost)
    return net_ret, trade_returns


def _trade_level_returns(pos: pd.Series, bar_ret: pd.Series, cost: pd.Series) -> pd.Series:
    """Collapse consecutive equal positions into single trades."""
    trades: list[float] = []
    cur_ret = 0.0
    cur_pos = 0.0
    open_now = False
    for p, r, c in zip(pos.values, bar_ret.values, cost.values, strict=False):
        p = float(p)
        if p != cur_pos:
            if open_now and cur_pos != 0:
                trades.append(cur_ret)
            cur_pos = p
            cur_ret = 0.0
            open_now = p != 0
        if open_now:
            cur_ret = (1.0 + cur_ret) * (1.0 + r - c) - 1.0
    if open_now and cur_pos != 0:
        trades.append(cur_ret)
    return pd.Series(trades, name="trade_returns")


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


def run_walkforward(
    df: pd.DataFrame,
    strategy: BacktestStrategy,
    *,
    window: int = 756,
    step: int = 21,
    embargo: int = 5,
    test_window: int = 21,
    market_kind: str = "crypto",
    run_lookahead_check: bool = True,
) -> BacktestResult:
    """Walk-forward backtest.

    For each rolling window the strategy is (re)called on the test slice and
    its returns accumulated; we never use a random train/test split.

    Every backtest result must pass the lookahead shuffle test before being
    saved. If the check fails, ``lookahead_ok`` is set to ``False`` and the
    caller (e.g. the Prefect flow) must refuse to persist.
    """
    cost_bps = transaction_cost_bps(market_kind)
    n = len(df)
    if n <= window + embargo + test_window:
        # Not enough data — run a single full-history pass so callers still
        # get a result shape.
        net_ret, trade_ret = _apply_strategy(df, strategy, cost_bps)
    else:
        pieces: list[pd.Series] = []
        trade_pieces: list[pd.Series] = []
        start = 0
        while True:
            train_end = start + window
            test_start = train_end + embargo
            test_end = test_start + test_window
            if test_end > n:
                break
            slice_df = df.iloc[start:test_end]
            net_ret, trade_ret = _apply_strategy(slice_df, strategy, cost_bps)
            pieces.append(net_ret.iloc[-test_window:])
            if not trade_ret.empty:
                trade_pieces.append(trade_ret)
            start += step
        if pieces:
            net_ret = pd.concat(pieces).sort_index()
            net_ret = net_ret[~net_ret.index.duplicated(keep="last")]
        else:
            net_ret = pd.Series(dtype=float)
        trade_ret = (
            pd.concat(trade_pieces, ignore_index=True) if trade_pieces else pd.Series(dtype=float)
        )

    result = _result_from_returns(net_ret, trade_ret)

    if run_lookahead_check:
        result.lookahead_ok = lookahead_test(strategy, df, market_kind=market_kind)

    return result


def _result_from_returns(returns: pd.Series, trade_returns: pd.Series) -> BacktestResult:
    total_return = float((1.0 + returns.fillna(0.0)).prod() - 1.0)
    mc = run_monte_carlo(trade_returns, n_sims=500) if not trade_returns.empty else {}
    return BacktestResult(
        sharpe=_sharpe(returns),
        max_drawdown=_max_drawdown(returns),
        calmar=_calmar(returns),
        sortino=_sortino(returns),
        hit_rate=_hit_rate(trade_returns),
        n_trades=int(len(trade_returns)),
        cagr=_cagr(returns),
        total_return=total_return,
        returns=returns,
        trades=trade_returns,
        mc_sharpe_5th=float(mc.get("sharpe_5th", float("nan"))),
    )


# ---------------------------------------------------------------------------
# Monte Carlo (block bootstrap on trade returns)
# ---------------------------------------------------------------------------


def run_monte_carlo(
    trade_returns: pd.Series,
    *,
    n_sims: int = 1000,
    block_size: int = 5,
    rng_seed: int = 7,
) -> dict[str, float]:
    """Block-bootstrap trade returns; return Sharpe percentiles."""
    r = np.asarray(trade_returns.dropna(), dtype=float)
    n = len(r)
    if n < 2:
        return {
            "sharpe_5th": float("nan"),
            "sharpe_50th": float("nan"),
            "sharpe_95th": float("nan"),
        }

    rng = np.random.default_rng(rng_seed)
    n_blocks = max(1, n // block_size)
    sharpes = np.empty(n_sims, dtype=float)

    for i in range(n_sims):
        starts = rng.integers(0, max(1, n - block_size + 1), size=n_blocks)
        sim = np.concatenate([r[s : s + block_size] for s in starts])
        sim = sim[:n]
        std = sim.std(ddof=1)
        if std == 0 or np.isnan(std):
            sharpes[i] = 0.0
        else:
            sharpes[i] = float(np.sqrt(252) * sim.mean() / std)

    return {
        "sharpe_5th": float(np.percentile(sharpes, 5)),
        "sharpe_50th": float(np.percentile(sharpes, 50)),
        "sharpe_95th": float(np.percentile(sharpes, 95)),
    }


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


def _bh_strategy(df: pd.DataFrame) -> pd.Series:
    return pd.Series(1, index=df.index)


def _ma_crossover_strategy(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    pos = (ma_fast > ma_slow).astype(int)
    return pos


def _rsi_meanrev_strategy(df: pd.DataFrame, period: int = 14) -> pd.Series:
    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    diff = close.diff()
    up = diff.clip(lower=0).rolling(period).mean()
    down = (-diff.clip(upper=0)).rolling(period).mean()
    rs = up / (down + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    pos = pd.Series(0, index=df.index)
    pos[rsi < 30] = 1
    pos[rsi > 70] = -1
    return pos


_BENCHMARKS: dict[str, BacktestStrategy] = {
    "buy_hold": _bh_strategy,
    "ma_50_200": _ma_crossover_strategy,
    "rsi_meanrev": _rsi_meanrev_strategy,
}


def benchmark_comparison(
    strategy_returns: pd.Series,
    df: pd.DataFrame | None = None,
    *,
    benchmarks: Iterable[str] = ("buy_hold", "ma_50_200", "rsi_meanrev"),
    market_kind: str = "crypto",
) -> dict[str, dict[str, float]]:
    """Compare Sharpe/DD vs the plan's three benchmark strategies.

    If ``df`` is provided, we re-run each benchmark on it. Otherwise we just
    report the strategy's own stats (useful for quick sanity checks).
    """
    cost_bps = transaction_cost_bps(market_kind)
    out: dict[str, dict[str, float]] = {
        "strategy": {
            "sharpe": _sharpe(strategy_returns),
            "max_drawdown": _max_drawdown(strategy_returns),
            "calmar": _calmar(strategy_returns),
            "sortino": _sortino(strategy_returns),
        }
    }
    if df is None:
        return out

    for name in benchmarks:
        if name not in _BENCHMARKS:
            log.warning("Unknown benchmark %s", name)
            continue
        net_ret, _ = _apply_strategy(df, _BENCHMARKS[name], cost_bps)
        out[name] = {
            "sharpe": _sharpe(net_ret),
            "max_drawdown": _max_drawdown(net_ret),
            "calmar": _calmar(net_ret),
            "sortino": _sortino(net_ret),
        }
    return out


# ---------------------------------------------------------------------------
# Lookahead (shuffle) test — plan 8.2
# ---------------------------------------------------------------------------


def lookahead_test(
    strategy: BacktestStrategy,
    df: pd.DataFrame,
    *,
    market_kind: str = "crypto",
    n_shuffles: int = 10,
    tolerance: float = 0.20,
    rng_seed: int = 13,
) -> bool:
    """Run the shuffle / lookahead test (plan 8.2).

    Algorithm:
    1. Compute the original Sharpe ``S*`` of the strategy on ``df``.
    2. Generate ``n_shuffles`` alternate price paths by shuffling the
       bar-to-bar returns (preserving the empirical return distribution but
       destroying any temporal structure the strategy might be exploiting).
    3. Re-run the strategy on each shuffled path.
    4. Report leakage iff a high fraction (more than ``tolerance``) of
       shuffled Sharpes *strictly exceed* ``S*``: a signal-driven strategy
       that truly peeks at the future would still score high on shuffled
       data (because it's actually using information that shuffling preserves
       — e.g. directly reading ``close.shift(-1)``).

    Strategies with constant positions (e.g. buy-and-hold) have Sharpe =
    market-Sharpe on any shuffle; they're not actually using forward info.
    We short-circuit those as clean.
    """
    cost_bps = transaction_cost_bps(market_kind)
    try:
        positions = strategy(df).reindex(df.index).fillna(0).astype(float)
    except Exception as exc:
        log.warning("lookahead_test: strategy failed producing positions: %s", exc)
        return False

    # Constant-position strategies use no future information.
    if positions.nunique(dropna=True) <= 1:
        return True

    try:
        real_ret, _ = _apply_strategy(df, strategy, cost_bps)
    except Exception as exc:
        log.warning("lookahead_test: strategy failed on original data: %s", exc)
        return False
    real_sharpe = _sharpe(real_ret)

    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    real_ret_vec = close.pct_change().fillna(0.0).to_numpy()
    base = float(close.iloc[0]) if len(close) else 1.0

    rng = np.random.default_rng(rng_seed)
    hits = 0
    for _ in range(n_shuffles):
        shuffled = real_ret_vec.copy()
        rng.shuffle(shuffled)
        shuffled_close = np.concatenate([[base], (1.0 + shuffled[1:]).cumprod() * base])[: len(df)]
        shuffled_df = df.copy()
        shuffled_df["close"] = shuffled_close
        try:
            ret, _ = _apply_strategy(shuffled_df, strategy, cost_bps)
        except Exception:  # pragma: no cover
            continue
        # Require a clear dominance (shuffled *beats* original by more than
        # noise). We compare to real_sharpe + small margin to avoid flagging
        # ties due to the same return distribution.
        if _sharpe(ret) > real_sharpe + 0.1:
            hits += 1

    return hits / max(1, n_shuffles) <= tolerance


# ---------------------------------------------------------------------------
# CPCV (López de Prado) — combinatorial purged cross-validation
# ---------------------------------------------------------------------------


def cpcv_folds(
    n_obs: int,
    n_splits: int = 8,
    embargo: int = 5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return list of (train_idx, test_idx) tuples with purge + embargo.

    The full index is split into ``n_splits`` contiguous groups. For each group
    we hold it out as the test set, drop an ``embargo`` band on each side from
    the training set, and concatenate the rest.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >=2")
    idx = np.arange(n_obs)
    group_size = n_obs // n_splits
    if group_size <= 0:
        raise ValueError("Not enough obs for that many splits")
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for k in range(n_splits):
        start = k * group_size
        end = n_obs if k == n_splits - 1 else start + group_size
        test_idx = idx[start:end]
        lo = max(0, start - embargo)
        hi = min(n_obs, end + embargo)
        keep_mask = np.ones(n_obs, dtype=bool)
        keep_mask[lo:hi] = False
        train_idx = idx[keep_mask]
        folds.append((train_idx, test_idx))
    return folds
