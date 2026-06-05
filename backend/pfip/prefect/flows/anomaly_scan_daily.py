"""Prefect flow: daily anomaly scan over OHLCV.

Pulls the last 120 days of OHLCV across every watchlist symbol, runs
:mod:`pfip.ingest._common.anomaly`, and persists flagged rows to
``data/anomaly_log/<date>.jsonl``. If the anomaly ratio crosses 1% in a
single batch, fires a Telegram WARN via :func:`alert_if_excessive`.

Why a JSONL file rather than a new SQL table:

- The anomaly log is append-only audit data; we don't query it from
  hot paths.
- It dodges an Alembic migration on day-1; the file can be tailed,
  grepped, and rotated trivially.
- A future migration can import these files in batch if we decide we
  need joins on `anomaly_log` from the UI.

Schedule binding is in ``pfip/prefect/deploy.py``; this module exposes
only the flow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prefect import flow, get_run_logger, task
from sqlalchemy import select

from pfip.db.session import get_sessionmaker
from pfip.ingest._common.anomaly import (
    AnomalyRow,
    alert_if_excessive,
    detect_anomalies,
)
from pfip.models.ohlcv import OHLCVRow
from pfip.models.watchlist import WatchlistRow

_OUT_DIR = Path("data/anomaly_log")
_LOOKBACK_DAYS = 120


@task(name="anomaly-fetch-ohlcv")
async def _fetch_ohlcv() -> tuple[list[dict], int]:
    """Pull last `_LOOKBACK_DAYS` of OHLCV for every watchlist symbol."""
    factory = get_sessionmaker()
    since = datetime.now(tz=timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    async with factory() as session:
        symbols_q = await session.execute(select(WatchlistRow.symbol).distinct())
        symbols = [s for (s,) in symbols_q.all()]
        if not symbols:
            return ([], 0)
        rows_q = await session.execute(
            select(OHLCVRow)
            .where(OHLCVRow.symbol.in_(symbols))
            .where(OHLCVRow.ts >= since)
        )
        rows = rows_q.scalars().all()

    payload = [
        {
            "symbol": r.symbol,
            "ts": r.ts,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for r in rows
    ]
    return (payload, len(payload))


@task(name="anomaly-persist")
def _persist(anomalies: list[AnomalyRow]) -> Path | None:
    if not anomalies:
        return None
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    out = _OUT_DIR / f"{today}.jsonl"
    with out.open("a", encoding="utf-8") as fp:
        for a in anomalies:
            fp.write(
                json.dumps(
                    {
                        "symbol": a.symbol,
                        "ts": a.ts.isoformat(),
                        "score": a.score,
                        "reason": a.reason,
                        "features": a.features,
                    }
                )
                + "\n"
            )
    return out


@flow(name="anomaly-scan-daily", log_prints=True)
async def anomaly_scan_daily() -> dict[str, int | str | None]:
    """End-to-end daily scan."""
    logger = get_run_logger()
    rows, total = await _fetch_ohlcv()
    if total == 0:
        logger.warning("No OHLCV rows to scan — skipping")
        return {"total_rows": 0, "n_anomalies": 0, "log_path": None}

    anomalies = detect_anomalies(rows)
    path = _persist(anomalies)
    await alert_if_excessive(anomalies, total_rows=total, threshold=0.01)

    logger.info(
        "Anomaly scan complete: {} flagged / {} total rows ({:.2f}%) → {}",
        len(anomalies),
        total,
        (len(anomalies) / total) * 100 if total else 0.0,
        path,
    )
    return {
        "total_rows": total,
        "n_anomalies": len(anomalies),
        "log_path": str(path) if path else None,
    }


if __name__ == "__main__":
    import asyncio

    asyncio.run(anomaly_scan_daily())
