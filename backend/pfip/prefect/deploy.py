"""Register Prefect deployments for the flows.

Run once (inside the backend container, after the Prefect server is up):
    python -m pfip.prefect.deploy
"""

from __future__ import annotations

import asyncio

from prefect.client.schemas.schedules import CronSchedule

from pfip.prefect.flows.compute_features import compute_features_flow
from pfip.prefect.flows.ingest_btc_daily import ingest_btc_daily
from pfip.prefect.flows.ragas_eval_monthly import ragas_eval_monthly
from pfip.prefect.flows.weekly_review import weekly_review
from pfip.prefect.flows.anomaly_scan_daily import anomaly_scan_daily
from pfip.prefect.flows.regime_detect_daily import regime_detect_daily_flow
from pfip.prefect.flows.train_lgbm_per_regime import train_lgbm_per_regime
from pfip.prefect.flows.reconcile_daily import reconcile_daily
from pfip.prefect.flows.backtest_walk_forward import backtest_walk_forward
from pfip.prefect.flows.market_close_summary import market_close_summary
from pfip.prefect.flows.shadow_rollup_monthly import shadow_rollup_monthly
from pfip.prefect.flows.skipped_task_alerter import skipped_task_alerter
from pfip.prefect.flows.annual_itr_drill import annual_itr_drill
from pfip.prefect.flows.escalate_unacked import escalate_unacked


async def main() -> None:
    """Register deployments with a cron schedule."""
    # BTC daily ingest — 00:05 UTC every day.
    await ingest_btc_daily.serve(  # type: ignore[attr-defined]
        name="ingest-btc-daily",
        tags=["ingest", "crypto"],
        schedule=CronSchedule(cron="5 0 * * *", timezone="UTC"),
        parameters={"exchange": "coinbase", "symbol": "BTC/USD", "timeframe": "1d"},
        pause_on_shutdown=False,
    )
    await compute_features_flow.serve(  # type: ignore[attr-defined]
        name="compute-features-btc-daily",
        tags=["features", "crypto"],
        schedule=CronSchedule(cron="15 0 * * *", timezone="UTC"),
        parameters={"symbol": "BTC/USD", "source": "coinbase", "timeframe": "1d"},
        pause_on_shutdown=False,
    )
    # Monthly RAG evaluation — first Saturday of every month at 10:00 IST
    # (04:30 UTC). Mirrors the calibration_monthly schedule cadence.
    await ragas_eval_monthly.serve(  # type: ignore[attr-defined]
        name="ragas-eval-monthly",
        tags=["kb", "eval", "monthly"],
        schedule=CronSchedule(cron="30 4 1-7 * 6", timezone="UTC"),
        parameters={"k": 5},
        pause_on_shutdown=False,
    )
    # Weekly review — every Sunday at 19:00 IST (13:30 UTC).
    await weekly_review.serve(  # type: ignore[attr-defined]
        name="weekly-review",
        tags=["journal", "weekly"],
        schedule=CronSchedule(cron="30 13 * * 0", timezone="UTC"),
        parameters={"days": 7},
        pause_on_shutdown=False,
    )
    # Daily anomaly scan — 18:30 UTC ≈ 00:00 IST (catch the day's vendor
    # data after all closes). Cheap; the IsolationForest fit is sub-second.
    await anomaly_scan_daily.serve(  # type: ignore[attr-defined]
        name="anomaly-scan-daily",
        tags=["ingest", "anomaly", "daily"],
        schedule=CronSchedule(cron="30 18 * * *", timezone="UTC"),
        pause_on_shutdown=False,
    )
    # HMM regime detection — daily at 01:00 UTC for BTC (other symbols can
    # be added by duplicating the .serve() call with a different parameters
    # dict; we want a separate deployment per symbol so they can fail
    # independently).
    await regime_detect_daily_flow.serve(  # type: ignore[attr-defined]
        name="regime-detect-btc-daily",
        tags=["ml", "regime", "daily"],
        schedule=CronSchedule(cron="0 1 * * *", timezone="UTC"),
        parameters={"symbol": "BTC/USD", "source": "coinbase", "timeframe": "1d"},
        pause_on_shutdown=False,
    )
    # Cross-source reconciliation — 18:45 UTC, just after anomaly scan.
    await reconcile_daily.serve(  # type: ignore[attr-defined]
        name="reconcile-daily",
        tags=["ingest", "quality", "daily"],
        schedule=CronSchedule(cron="45 18 * * *", timezone="UTC"),
        parameters={"threshold_pct": 0.005},
        pause_on_shutdown=False,
    )
    # Walk-forward backtest — every Saturday 02:00 UTC (just ahead of the
    # weekly retrain on Sunday so backtest metrics inform the next week's
    # pin/keep decision).
    await backtest_walk_forward.serve(  # type: ignore[attr-defined]
        name="backtest-walk-forward-btc-weekly",
        tags=["ml", "backtest", "weekly"],
        schedule=CronSchedule(cron="0 2 * * 6", timezone="UTC"),
        parameters={
            "symbol": "BTC/USD",
            "source": "coinbase",
            "timeframe": "1d",
            "strategy_name": "ma_50_200",
            "market_kind": "crypto",
        },
        pause_on_shutdown=False,
    )
    # Market-close summary — weekdays 17:30 IST = 12:00 UTC.
    await market_close_summary.serve(  # type: ignore[attr-defined]
        name="market-close-summary",
        tags=["digest", "daily"],
        schedule=CronSchedule(cron="0 12 * * 1-5", timezone="UTC"),
        pause_on_shutdown=False,
    )
    # Monthly shadow rollup — last Sunday of each month 19:00 IST = 13:30 UTC.
    # We approximate "last Sunday" via cron "30 13 25-31 * 0".
    await shadow_rollup_monthly.serve(  # type: ignore[attr-defined]
        name="shadow-rollup-monthly",
        tags=["shadow", "monthly"],
        schedule=CronSchedule(cron="30 13 25-31 * 0", timezone="UTC"),
        parameters={"days": 30},
        pause_on_shutdown=False,
    )
    # Skipped-task alerter — hourly watchdog.
    await skipped_task_alerter.serve(  # type: ignore[attr-defined]
        name="skipped-task-alerter",
        tags=["ops", "watchdog"],
        schedule=CronSchedule(cron="15 * * * *", timezone="UTC"),
        pause_on_shutdown=False,
    )
    # Escalate unacked WARN alerts every 30 minutes.
    await escalate_unacked.serve(  # type: ignore[attr-defined]
        name="escalate-unacked",
        tags=["alerts", "watchdog"],
        schedule=CronSchedule(cron="*/30 * * * *", timezone="UTC"),
        parameters={"escalation_after_minutes": 120},
        pause_on_shutdown=False,
    )
    # Annual ITR calibration drill — June 15 (advance-tax milestone) 09:00 IST.
    await annual_itr_drill.serve(  # type: ignore[attr-defined]
        name="annual-itr-drill",
        tags=["tax", "annual"],
        schedule=CronSchedule(cron="30 3 15 6 *", timezone="UTC"),
        pause_on_shutdown=False,
    )
    # Per-regime LightGBM retraining — every Sunday 03:00 UTC.
    # Models land in the file-backed registry; existing champion pins
    # are NOT silently demoted.
    await train_lgbm_per_regime.serve(  # type: ignore[attr-defined]
        name="train-lgbm-btc-weekly",
        tags=["ml", "training", "weekly"],
        schedule=CronSchedule(cron="0 3 * * 0", timezone="UTC"),
        parameters={"symbol": "BTC/USD", "horizons": [1, 5, 21]},
        pause_on_shutdown=False,
    )


if __name__ == "__main__":
    asyncio.run(main())
