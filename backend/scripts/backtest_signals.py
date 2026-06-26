"""Historical walk-forward backtest of the LightGBM signal model.

Answers the only question that matters once ``FEATURE_ML_SIGNALS`` is on: **does
the directional model have out-of-sample edge?** Unlike the live-signal
calibration (which needs signals to mature past the t+3 horizon), this scores the
*model* over all available history, so it's runnable the moment data exists.

For each watchlist symbol it replays the exact production path —
``compute_features`` -> regime-routed ``LGBMBaselineModel`` ->
``walk_forward_train`` (21-day step / 21-day test / 5-day embargo) — and collects
every out-of-sample ``(proba_up, y)`` holdout pair, then reports:

* **n** — holdout predictions scored.
* **hit_rate** — directional accuracy (proba>0.5 vs realised up/down at t+3).
* **base_rate** — the naive majority-class accuracy (always predict the more
  common direction) — the bar to beat.
* **edge** — ``hit_rate - base_rate`` (the honest out-of-sample edge; ~0 or
  negative means no demonstrated skill).
* **brier** — calibration error of the probabilities (lower is better; 0.25 is
  the coin-flip reference).

No leakage: every prediction is from a model fit only on data before its test
window (the walk-forward + embargo guarantee this). No vectorbt / no matured
signals required.

Run on the VM:
    cd ~/pfip/backend && PYTHONPATH=$PWD ./.venv/bin/python -m scripts.backtest_signals
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from pfip.core.contracts import Regime
from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.db.sources import resolve_ohlcv_source
from pfip.features.technicals import compute_features
from pfip.models.watchlist import WatchlistRow
from pfip.signals.lgbm_baseline import FEATURE_COLUMNS, LGBMBaselineModel, make_label
from pfip.signals.regime_router import RegimeRouter

log = get_logger("scripts.backtest_signals")


async def _load_ohlcv(session, symbol: str, source: str, timeframe: str, days: int) -> pd.DataFrame:
    from pfip.models.ohlcv import OHLCVRow

    since = datetime.now(tz=UTC) - timedelta(days=days)
    res = await session.execute(
        select(OHLCVRow)
        .where(
            OHLCVRow.symbol == symbol,
            OHLCVRow.source == source,
            OHLCVRow.timeframe == timeframe,
            OHLCVRow.time >= since,
        )
        .order_by(OHLCVRow.time.asc())
    )
    rows = res.scalars().all()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "time": r.time,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
            }
            for r in rows
        ]
    ).set_index("time")


async def _regime_for(session, symbol: str) -> Regime:
    try:
        from sqlalchemy import desc

        from pfip.models.regime import RegimeRow

        row = (
            (
                await session.execute(
                    select(RegimeRow)
                    .where(RegimeRow.symbol == symbol)
                    .order_by(desc(RegimeRow.since))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            return Regime(row.regime)
    except Exception:
        pass
    return Regime.SIDEWAYS


def _score(wf: pd.DataFrame) -> dict | None:
    if wf is None or wf.empty or "proba_up" not in wf or "y" not in wf:
        return None
    df = wf.dropna(subset=["proba_up", "y"])
    if len(df) < 40:
        return None
    proba = df["proba_up"].to_numpy(dtype=float)
    y = df["y"].to_numpy(dtype=float)
    pred_up = proba > 0.5
    hit = float(np.mean(pred_up == (y > 0.5)))
    up_rate = float(np.mean(y > 0.5))
    base = max(up_rate, 1.0 - up_rate)
    brier = float(np.mean((proba - y) ** 2))
    return {
        "n": int(len(df)),
        "hit_rate": round(hit, 4),
        "base_rate": round(base, 4),
        "edge": round(hit - base, 4),
        "brier": round(brier, 4),
        "up_rate": round(up_rate, 4),
    }


async def backtest_symbol(session, symbol: str, timeframe: str = "1d", days: int = 365 * 3):
    source = await resolve_ohlcv_source(session, symbol, timeframe)
    if not source:
        return symbol, None, "no-source"
    df = await _load_ohlcv(session, symbol, source, timeframe, days)
    if df.empty or len(df) < 120:
        return symbol, None, "insufficient-bars"
    feats = compute_features(df)
    feats = feats[[c for c in FEATURE_COLUMNS if c in feats.columns]].dropna()
    if feats.empty:
        return symbol, None, "no-features"
    regime = await _regime_for(session, symbol)
    model: LGBMBaselineModel = RegimeRouter().get(regime)
    y = make_label(df["close"], horizon=model.horizon).reindex(feats.index)
    valid = y.dropna().index
    if len(valid) < 90:
        return symbol, None, "not-enough-labels"
    # Backtest uses a 1-year (252-bar) train window so the bulk of history is
    # out-of-sample holdout — maximizing the number of scored predictions. (The
    # live signal path uses a larger ~756 window because it only needs the most
    # recent fit for *today's* call, not a long holdout series.)
    train_window = max(120, min(252, len(valid) - 100))
    try:
        wf = model.walk_forward_train(
            features=feats.loc[valid],
            close=df["close"].loc[valid],
            train_window=train_window,
            step=21,
            test_window=21,
            embargo=5,
        )
    except Exception as exc:
        return symbol, None, f"wf-error: {type(exc).__name__}"
    sc = _score(wf)
    if sc is None:
        return symbol, None, "too-few-holdout"
    sc["regime"] = regime.value
    sc["model"] = model.model_name
    return symbol, sc, "ok"


async def main() -> dict:
    factory = get_sessionmaker()
    async with factory() as s:
        symbols = [str(r.symbol) for r in (await s.execute(select(WatchlistRow))).scalars().all()]

    per_symbol: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    factory = get_sessionmaker()
    for sym in symbols:
        async with factory() as s:
            symbol, sc, status = await backtest_symbol(s, sym)
        if sc is None:
            skipped[symbol] = status
            continue
        per_symbol[symbol] = sc
        log.info(
            f"[bt] {symbol:14} n={sc['n']:4} hit={sc['hit_rate']:.3f} "
            f"base={sc['base_rate']:.3f} edge={sc['edge']:+.3f} brier={sc['brier']:.3f} "
            f"({sc['regime']})"
        )

    scored = list(per_symbol.values())
    if scored:

        def _wmean(key: str) -> float:
            num = sum(d[key] * d["n"] for d in scored)
            den = sum(d["n"] for d in scored)
            return round(num / den, 4) if den else float("nan")

        agg = {
            "symbols_scored": len(scored),
            "total_predictions": sum(d["n"] for d in scored),
            "weighted_hit_rate": _wmean("hit_rate"),
            "weighted_base_rate": _wmean("base_rate"),
            "weighted_edge": _wmean("edge"),
            "weighted_brier": _wmean("brier"),
            "symbols_with_positive_edge": sum(1 for d in scored if d["edge"] > 0),
        }
    else:
        agg = {"symbols_scored": 0}

    summary = {"aggregate": agg, "per_symbol": per_symbol, "skipped": skipped}
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    asyncio.run(main())
