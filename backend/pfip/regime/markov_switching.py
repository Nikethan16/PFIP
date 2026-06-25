"""Markov-switching (Hamilton 1989) regime baseline.

Uses ``statsmodels.tsa.regime_switching.markov_regression.MarkovRegression``
(a.k.a. the MS-AR / Hamilton model) to estimate filtered regime probabilities.
This is the *regime baseline* for Phase 2: any fancier regime method (ruptures
change-point, upgraded HMM) must produce more stable, more useful labels than
this clean, well-understood model.

Two outputs for the scoring harness:
  1. ``filtered_probs`` — per-bar probability of being in each state (the rich
     signal; the HMM currently exposes only the hard label).
  2. ``regime_label`` — majority-state label mapped to the same ``Regime`` enum
     the HMM uses, so downstream callers need no adapter.

Design mirrors ``hmm_detector.py``:
  * optional heavy dep (``statsmodels``) with a dead-simple fallback (rolling
    mean sign = bull/bear/sideways);
  * frozen result dataclass;
  * ``fit`` / ``predict`` / ``score_per_bar`` trio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pfip.core.contracts import Regime

log = logging.getLogger(__name__)

try:  # pragma: no cover
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression  # type: ignore[import-untyped]

    _STATSMODELS_OK = True
except Exception as exc:  # pragma: no cover
    log.warning("statsmodels MS unavailable (%s); using rule-based fallback", exc)
    MarkovRegression = None  # type: ignore[assignment]
    _STATSMODELS_OK = False

# State ordering convention: state 0 = low-vol/bull, state 1 = mid, state 2 = bear/high-vol.
# Three states balances expressiveness vs. over-parameterisation for daily returns.
_DEFAULT_K = 3
_MIN_OBS = 100


@dataclass
class MSRegimeResult:
    """Per-bar Markov-switching output."""

    regime: pd.Series  # Regime enum values, time-indexed
    confidence: pd.Series  # max filtered probability, time-indexed
    filtered_probs: pd.DataFrame  # k columns of P(state_k | data_1..t), time-indexed
    method: str  # "markov_switching" or "rule_based"


def _state_to_regime(state_means: np.ndarray) -> dict[int, Regime]:
    """Map states to Regime labels by ordering their mean return.

    Lowest mean → bear_trend, highest → bull_trend, middle → sideways.
    If there is only one middle state it is sideways.  If more than 3 states
    exist the extras map to their nearest neighbour (shouldn't happen with
    _DEFAULT_K=3 but guard anyway).
    """
    order = np.argsort(state_means)  # ascending
    mapping: dict[int, Regime] = {}
    n = len(order)
    mapping[int(order[0])] = Regime.BEAR_TREND
    mapping[int(order[-1])] = Regime.BULL_TREND
    for i in range(1, n - 1):
        mapping[int(order[i])] = Regime.SIDEWAYS
    # Any unset extras default to sideways.
    for s in range(n):
        mapping.setdefault(s, Regime.SIDEWAYS)
    return mapping


class MarkovSwitchingDetector:
    """Hamilton-style Markov-switching regime detector.

    Args:
        k_regimes: number of latent states (default 3).
        switching_variance: if True, each state gets its own variance
            (a.k.a. MS-ARCH(0); recommended for daily returns).
        ar_order: AR lags in the switching mean equation (0 = switching mean
            only, which is the honest baseline — no fitted dynamics).
    """

    def __init__(
        self,
        *,
        k_regimes: int = _DEFAULT_K,
        switching_variance: bool = True,
        ar_order: int = 0,
    ) -> None:
        self.k_regimes = k_regimes
        self.switching_variance = switching_variance
        self.ar_order = ar_order
        self._result: MSRegimeResult | None = None
        self._state_map: dict[int, Regime] | None = None
        self._fitted: object | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _log_returns(prices: pd.Series) -> pd.Series:
        r = np.log(prices / prices.shift(1)).dropna()
        return r.replace([np.inf, -np.inf], np.nan).dropna()

    @staticmethod
    def _rule_based(returns: pd.Series, k: int = 3) -> MSRegimeResult:
        """Dead-simple fallback: rolling percentile thresholds."""
        roll_ret = returns.rolling(20, min_periods=5).mean()
        roll_vol = returns.rolling(20, min_periods=5).std()
        states = pd.Series(1, index=returns.index)  # default sideways
        high_vol = roll_vol > roll_vol.quantile(0.70)
        states[high_vol] = 2
        states[(~high_vol) & (roll_ret > roll_ret.quantile(0.60))] = 0
        states[(~high_vol) & (roll_ret < roll_ret.quantile(0.40))] = 1

        state_means = np.array(
            [float(returns[states == s].mean()) if (states == s).any() else 0.0 for s in range(k)]
        )
        mapping = _state_to_regime(state_means)
        regime = states.map(mapping)
        probs = pd.DataFrame(
            {s: (states == s).astype(float) for s in range(k)},
            index=returns.index,
        )
        return MSRegimeResult(
            regime=regime,
            confidence=pd.Series(1.0, index=returns.index),
            filtered_probs=probs,
            method="rule_based",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fit(self, prices: pd.Series) -> "MarkovSwitchingDetector":
        """Fit on a price series (log-returns computed internally)."""
        returns = self._log_returns(prices)
        if len(returns) < _MIN_OBS:
            log.info("MS: only %d obs (<%d); using rule-based fallback", len(returns), _MIN_OBS)
            self._result = self._rule_based(returns, k=self.k_regimes)
            return self

        if not _STATSMODELS_OK:
            self._result = self._rule_based(returns, k=self.k_regimes)
            return self

        try:  # pragma: no cover
            mod = MarkovRegression(
                returns,
                k_regimes=self.k_regimes,
                trend="c",
                switching_variance=self.switching_variance,
            )
            res = mod.fit(disp=False, maxiter=200)
            self._fitted = res

            # Filtered probabilities P(state_k | data_1..t): shape (n, k).
            filt = pd.DataFrame(
                np.asarray(res.filtered_marginal_probabilities),
                index=returns.index,
                columns=list(range(self.k_regimes)),
            )
            hard_state = filt.idxmax(axis=1).astype(int)

            # Map states to Regime labels by their mean return.
            state_means = np.array(
                [
                    float(returns[hard_state == s].mean()) if (hard_state == s).any() else 0.0
                    for s in range(self.k_regimes)
                ]
            )
            self._state_map = _state_to_regime(state_means)
            regime_labels = hard_state.map(self._state_map)
            confidence = filt.max(axis=1)

            self._result = MSRegimeResult(
                regime=regime_labels,
                confidence=confidence,
                filtered_probs=filt,
                method="markov_switching",
            )
        except Exception as exc:  # pragma: no cover
            log.warning("MS fit failed (%s); falling back to rule-based", exc)
            r_fallback = self._log_returns(prices)
            self._result = self._rule_based(r_fallback, k=self.k_regimes)
        return self

    def score_per_bar(self, prices: pd.Series | None = None) -> MSRegimeResult:
        """Return the fitted result (re-runs fit if not yet called)."""
        if self._result is None:
            if prices is None:
                raise RuntimeError("call fit(prices) first or pass prices here")
            self.fit(prices)
        assert self._result is not None
        return self._result

    def latest_regime(self) -> tuple[Regime, float]:
        """Return (regime, confidence) for the most recent bar."""
        r = self.score_per_bar()
        return Regime(r.regime.iloc[-1]), float(r.confidence.iloc[-1])

    def filtered_prob_feature(self) -> pd.DataFrame:
        """Return filtered probabilities as a feature DataFrame for the harness.

        The probability of being in each state is more informative than the hard
        label — it lets downstream models see *how confident* the regime is.
        """
        r = self.score_per_bar()
        cols = {f"ms_prob_state{s}": r.filtered_probs[s] for s in r.filtered_probs.columns}
        return pd.DataFrame(cols, index=r.filtered_probs.index)
