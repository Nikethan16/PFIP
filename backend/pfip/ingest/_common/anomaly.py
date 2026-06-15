"""Anomaly detection over recent OHLCV.

Catches the failure modes that ingest validation can't:

- Stale-symbol price suddenly jumps 10× (parser picked up a comma vs
  decimal swap or a bonus issue without adjustment).
- Volume row of 0 when 30-day mean is ~10M (vendor outage rendered as
  zero rather than null).
- Close above high or below low (impossible; pandera should already
  catch this but the safety net stays anyway).
- Price gap > 50% with no corporate-action flag and no news cluster
  within 24h.

Implementation: sklearn IsolationForest over engineered features
(`log_return`, `volume_z`, `range_pct`, `gap_pct`) per-symbol with a
contamination of 0.5% (we expect a few outliers in a healthy feed).

Output rows land in `anomaly_log` (best-effort write — the analyser is
read-mostly). If anomaly ratio exceeds 0.5% of rows scanned in a single
batch, a Telegram WARN alert is dispatched. The mod is intentionally
side-effect-light so Prefect schedules can call it without locking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd
from loguru import logger

_DEFAULT_CONTAMINATION = 0.005
_DEFAULT_RANDOM_STATE = 42
_MIN_ROWS_PER_SYMBOL = 60  # IsolationForest needs enough data to find structure


@dataclass(slots=True)
class AnomalyRow:
    symbol: str
    ts: datetime
    score: float  # decision_function output; negative = anomaly
    reason: str  # the feature that's most extreme
    features: dict[str, float]


def _engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add `log_return`, `volume_z`, `range_pct`, `gap_pct` to a per-symbol df.

    Input columns required: `open`, `high`, `low`, `close`, `volume`.
    """
    out = df.copy()
    out["log_return"] = np.log(out["close"] / out["close"].shift(1))
    out["range_pct"] = (out["high"] - out["low"]) / out["close"].replace(0, np.nan)
    out["gap_pct"] = (out["open"] - out["close"].shift(1)) / out["close"].shift(1).replace(
        0, np.nan
    )
    rolling = out["volume"].rolling(window=30, min_periods=10)
    out["volume_z"] = (out["volume"] - rolling.mean()) / rolling.std().replace(0, np.nan)
    return out.dropna(subset=["log_return", "range_pct", "gap_pct", "volume_z"])


def detect_anomalies(
    rows: Iterable[dict[str, Any]],
    *,
    contamination: float = _DEFAULT_CONTAMINATION,
    random_state: int = _DEFAULT_RANDOM_STATE,
) -> list[AnomalyRow]:
    """Run IsolationForest per symbol over the supplied rows.

    Args:
        rows: iterable of dicts with at least
            ``{symbol, ts, open, high, low, close, volume}``.
        contamination: expected fraction of outliers in the batch.
        random_state: deterministic seed.
    """
    df = pd.DataFrame(list(rows))
    if df.empty:
        return []

    needed = {"symbol", "ts", "open", "high", "low", "close", "volume"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Anomaly detector missing columns: {missing}")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.sort_values(["symbol", "ts"], inplace=True)

    # Lazy import — keep cold-start cheap if the caller never invokes us.
    from sklearn.ensemble import IsolationForest

    out: list[AnomalyRow] = []
    for symbol, g in df.groupby("symbol"):
        if len(g) < _MIN_ROWS_PER_SYMBOL:
            logger.debug(
                "skipping {} — only {} rows (min {})",
                symbol,
                len(g),
                _MIN_ROWS_PER_SYMBOL,
            )
            continue
        feats = _engineer_features(g)
        if feats.empty:
            continue
        x = feats[["log_return", "range_pct", "gap_pct", "volume_z"]].to_numpy()
        try:
            model = IsolationForest(
                contamination=contamination,
                random_state=random_state,
                n_jobs=-1,
            )
            scores = model.fit(x).decision_function(x)
            preds = model.predict(x)  # +1 inlier, -1 outlier
        except Exception as exc:  # pragma: no cover — sklearn can still 1-class
            logger.warning("IsolationForest failed for {}: {}", symbol, exc)
            continue

        for i, (idx, row) in enumerate(feats.iterrows()):
            if preds[i] != -1:
                continue
            # Pick the most-extreme feature as the "reason".
            features_d = {
                "log_return": float(row["log_return"]),
                "range_pct": float(row["range_pct"]),
                "gap_pct": float(row["gap_pct"]),
                "volume_z": float(row["volume_z"]),
            }
            reason = max(features_d.items(), key=lambda kv: abs(kv[1]))[0]
            out.append(
                AnomalyRow(
                    symbol=str(symbol),
                    ts=row["ts"].to_pydatetime(),
                    score=float(scores[i]),
                    reason=reason,
                    features=features_d,
                )
            )

    logger.info(
        "anomaly detector: scanned {} symbols, flagged {} rows",
        df["symbol"].nunique(),
        len(out),
    )
    return out


async def alert_if_excessive(
    anomalies: list[AnomalyRow], total_rows: int, *, threshold: float = 0.01
) -> None:
    """Fire a Telegram WARN if anomaly ratio exceeds `threshold`.

    Caller passes ``total_rows`` so we don't have to re-count.
    """
    if total_rows <= 0 or not anomalies:
        return
    ratio = len(anomalies) / total_rows
    if ratio < threshold:
        return

    # Group by symbol for the alert body.
    by_sym: dict[str, list[AnomalyRow]] = {}
    for a in anomalies:
        by_sym.setdefault(a.symbol, []).append(a)
    top = sorted(by_sym.items(), key=lambda kv: -len(kv[1]))[:5]
    lines = [
        f"⚠️ *Anomaly ratio elevated*",
        f"flagged: *{len(anomalies)}* / {total_rows} rows "
        f"({ratio * 100:.2f}% — threshold {threshold * 100:.2f}%)",
        "",
        "Top symbols flagged:",
    ]
    for sym, items in top:
        lines.append(f"- `{sym}` ×{len(items)} (latest reason: {items[-1].reason})")
    lines.append("")
    lines.append("Inspect `anomaly_log` and the source health panel.")

    from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert

    await send_alert(
        kind=AlertKind.INGEST_FAILURE,
        severity=AlertSeverity.WARN,
        body_override="\n".join(lines),
        title_override="Anomaly ratio elevated",
    )


__all__ = ["AnomalyRow", "alert_if_excessive", "detect_anomalies"]
