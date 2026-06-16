"""GARCH(1,1) volatility baseline.

The honest baseline for conditional-volatility forecasting. Every fancier vol
model (TTM, Chronos, an LSTM, whatever) has to beat *this* on out-of-sample
realized-vol error before it earns a place as a risk feature — that's the whole
point of having a baseline.

Design mirrors the rest of the codebase:
* optional heavy dep (``arch``) with a pure-pandas fallback (RiskMetrics EWMA),
  so the module stays importable in minimal environments and CI;
* a small frozen result dataclass;
* a fit/forecast class plus a stateless evaluation helper the scoring harness
  can call.

Volatility convention
---------------------
We work in **daily** units throughout: inputs are daily log returns, outputs are
daily conditional standard deviations (``sigma``). Annualize downstream with
``sigma * sqrt(252)`` if a caller wants annualized vol — we deliberately keep the
raw daily number here so the harness compares like with like.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ``arch`` is the reference GARCH implementation. It's a pure-Python/Cython wheel
# (no numba), so it installs cleanly on 3.12 — but we still guard the import so a
# missing dep degrades to the EWMA fallback instead of breaking the package.
try:  # pragma: no cover — exercised with/without the dep
    from arch import arch_model

    _ARCH_OK = True
except Exception as exc:  # pragma: no cover
    log.warning("arch unavailable (%s); GARCH falls back to RiskMetrics EWMA", exc)
    arch_model = None  # type: ignore[assignment]
    _ARCH_OK = False

# arch warns (and fits poorly) when returns are tiny decimals; it recommends
# scaling to "percent" units. We scale in, fit, then scale every vol back out.
_SCALE = 100.0

# RiskMetrics 1994 decay for the EWMA fallback (daily data).
_EWMA_LAMBDA = 0.94

# Minimum observations before a GARCH fit is trustworthy.
_MIN_OBS = 100


@dataclass(frozen=True)
class VolForecast:
    """A volatility forecast plus the in-sample conditional-vol path.

    All sigmas are in **daily** return units (not percent, not annualized).
    """

    horizon: int
    sigma_forecast: float  # mean daily sigma over the forecast horizon
    sigma_path: pd.Series  # in-sample conditional sigma, time-indexed
    method: str  # "garch" or "ewma"
    params: dict[str, Any] = field(default_factory=dict)


class GarchVolForecaster:
    """GARCH(1,1) daily-volatility forecaster with an EWMA fallback.

    Args:
        p: GARCH lag order (default 1).
        q: ARCH lag order (default 1).
        dist: innovation distribution for ``arch`` ("normal", "t", "skewt").
        mean: mean model ("Zero" is the honest default for daily returns — we do
            not pretend to forecast the mean here, only the variance).
    """

    def __init__(
        self,
        *,
        p: int = 1,
        q: int = 1,
        dist: str = "normal",
        mean: str = "Zero",
    ) -> None:
        self.p = p
        self.q = q
        self.dist = dist
        self.mean = mean
        self._fitted: Any = None
        self._returns: pd.Series | None = None
        self._method: str | None = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_returns(returns: pd.Series) -> pd.Series:
        r = pd.Series(returns).astype(float)
        r = r.replace([np.inf, -np.inf], np.nan).dropna()
        return r

    def fit(self, returns: pd.Series) -> "GarchVolForecaster":
        """Fit on a series of **daily log returns**.

        Falls back to EWMA if ``arch`` is missing or the fit raises/has too few
        observations, so a caller always gets a usable forecaster.
        """
        r = self._clean_returns(returns)
        if len(r) < _MIN_OBS:
            log.info("GARCH: only %d obs (<%d); using EWMA fallback", len(r), _MIN_OBS)
            self._returns = r
            self._method = "ewma"
            self._fitted = None
            return self

        self._returns = r
        if not _ARCH_OK:
            self._method = "ewma"
            self._fitted = None
            return self

        try:  # pragma: no cover — needs the dep
            am = arch_model(
                r * _SCALE,
                mean=self.mean,
                vol="GARCH",
                p=self.p,
                q=self.q,
                dist=self.dist,
            )
            self._fitted = am.fit(disp="off")
            self._method = "garch"
        except Exception as exc:  # pragma: no cover
            log.warning("GARCH fit failed (%s); using EWMA fallback", exc)
            self._fitted = None
            self._method = "ewma"
        return self

    # ------------------------------------------------------------------
    # EWMA fallback
    # ------------------------------------------------------------------

    def _ewma_sigma_path(self, r: pd.Series) -> pd.Series:
        """RiskMetrics EWMA conditional sigma (daily units)."""
        var = r.pow(2).ewm(alpha=1 - _EWMA_LAMBDA, adjust=False).mean()
        return np.sqrt(var)

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------

    def forecast(self, horizon: int = 5) -> VolForecast:
        """Forecast mean daily sigma over the next ``horizon`` days."""
        if self._returns is None:
            raise RuntimeError("call fit() before forecast()")
        r = self._returns

        if self._method == "garch" and self._fitted is not None:  # pragma: no cover
            fc = self._fitted.forecast(horizon=horizon, reindex=False)
            # variance in percent^2 units → sigma in percent → back to decimal.
            var_pct = np.asarray(fc.variance.iloc[-1].values, dtype=float)
            sigma_daily = np.sqrt(var_pct) / _SCALE
            sigma_forecast = float(np.mean(sigma_daily))
            sigma_path = pd.Series(
                np.asarray(self._fitted.conditional_volatility, dtype=float) / _SCALE,
                index=r.index,
            )
            params = {k: float(v) for k, v in self._fitted.params.to_dict().items()}
            return VolForecast(
                horizon=horizon,
                sigma_forecast=sigma_forecast,
                sigma_path=sigma_path,
                method="garch",
                params=params,
            )

        # EWMA fallback: the last conditional sigma is the flat-ish forecast.
        sigma_path = self._ewma_sigma_path(r)
        last = float(sigma_path.iloc[-1]) if len(sigma_path) else float("nan")
        return VolForecast(
            horizon=horizon,
            sigma_forecast=last,
            sigma_path=sigma_path,
            method="ewma",
            params={"lambda": _EWMA_LAMBDA},
        )


def evaluate_vol_forecast(
    returns: pd.Series,
    *,
    horizon: int = 5,
    train_window: int = 504,
    step: int = 21,
    realized_window: int = 5,
) -> dict[str, float]:
    """Walk-forward evaluate a GARCH vol forecast against realized vol.

    The scoring-harness entry point for vol models: roll a ``train_window``
    forward in ``step`` increments, forecast mean daily sigma over ``horizon``,
    and compare to the *realized* daily sigma over the next ``realized_window``
    bars. Returns error metrics (lower is better) plus a naive-baseline error so
    a caller can see whether GARCH actually beats "tomorrow looks like today".

    Returns a dict with: ``n_folds``, ``rmse``, ``mae``, ``qlike`` (the
    likelihood-based loss standard in the vol-forecasting literature), and
    ``rmse_naive`` (last-realized-sigma carry-forward) for comparison.
    """
    r = GarchVolForecaster._clean_returns(returns)
    n = len(r)
    if n < train_window + realized_window + 1:
        return {"n_folds": 0.0}

    preds: list[float] = []
    naive: list[float] = []
    actuals: list[float] = []

    start = train_window
    while start + realized_window <= n:
        train = r.iloc[:start]
        future = r.iloc[start : start + realized_window]
        realized = float(future.std(ddof=1))
        if not np.isfinite(realized) or realized <= 0:
            start += step
            continue

        fc = GarchVolForecaster().fit(train).forecast(horizon=horizon)
        if not np.isfinite(fc.sigma_forecast) or fc.sigma_forecast <= 0:
            start += step
            continue

        # Naive baseline: realized sigma over the trailing realized_window.
        naive_sigma = float(train.iloc[-realized_window:].std(ddof=1))

        preds.append(fc.sigma_forecast)
        naive.append(naive_sigma if np.isfinite(naive_sigma) else fc.sigma_forecast)
        actuals.append(realized)
        start += step

    if not preds:
        return {"n_folds": 0.0}

    p = np.array(preds)
    a = np.array(actuals)
    nv = np.array(naive)

    rmse = float(np.sqrt(np.mean((p - a) ** 2)))
    mae = float(np.mean(np.abs(p - a)))
    # QLIKE: a / sigma^2 form (robust to vol-proxy noise); lower is better.
    var_p = np.clip(p**2, 1e-12, None)
    qlike = float(np.mean(np.log(var_p) + (a**2) / var_p))
    rmse_naive = float(np.sqrt(np.mean((nv - a) ** 2)))

    return {
        "n_folds": float(len(preds)),
        "rmse": rmse,
        "mae": mae,
        "qlike": qlike,
        "rmse_naive": rmse_naive,
        "beats_naive": float(rmse < rmse_naive),
    }
