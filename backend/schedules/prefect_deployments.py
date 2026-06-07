"""PFIP Prefect deployment catalogue — revised cadences per WHY_AND_WHAT.md §0b.

All cron expressions are UTC (Prefect default). IST offsets shown in comments.

Usage (inside the pfip-backend container):

    python -m schedules.prefect_deployments apply        # register/update all
    python -m schedules.prefect_deployments plan         # dry-run summary
    python -m schedules.prefect_deployments pause        # pause all
    python -m schedules.prefect_deployments resume       # resume all

`apply` skips any deployment whose flow import fails (logs the miss) so the
catalogue can be applied incrementally as flows come online.

Time-conversion quick reference (IST = UTC + 5:30):
    07:00 IST = 01:30 UTC
    16:30 IST = 11:00 UTC
    17:30 IST = 12:00 UTC
    22:00 IST = 16:30 UTC
    22:30 IST = 17:00 UTC
    23:30 IST = 18:00 UTC
    03:00 IST = 21:30 UTC (previous day)
    06:00 IST = 00:30 UTC
    06:30 IST = 01:00 UTC
    Sat 09:00 IST = Sat 03:30 UTC
    Sat 04:00 IST = Fri 22:30 UTC
    Sun 19:00 IST = Sun 13:30 UTC
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, List

LOG = logging.getLogger("pfip.schedules")


@dataclass(frozen=True)
class DeploymentSpec:
    name: str
    flow_path: str  # "module.path:callable"
    cron: str  # UTC cron
    description: str
    stage: int = 1
    tags: tuple = field(default_factory=tuple)
    work_pool: str = "default-agent-pool"


# -----------------------------------------------------------------------------
# Catalogue — revised cadences (FEATURES.md M1, WHY_AND_WHAT.md §0b).
# -----------------------------------------------------------------------------

DEPLOYMENTS: List[DeploymentSpec] = [
    # =================== HIGH-FREQUENCY INGEST ===================
    DeploymentSpec(
        name="ingest-crypto-hourly/prod",
        flow_path="pfip.prefect.flows.ingest_crypto_hourly:ingest_crypto_hourly",
        cron="5 * * * *",  # every hour at :05 UTC
        description="Hourly OHLCV (Coinbase/Kraken/Bybit/OKX) + on-chain refresh.",
        stage=1,
        tags=("ingest", "crypto"),
    ),
    DeploymentSpec(
        name="ingest-news-15min/prod",
        flow_path="pfip.prefect.flows.ingest_news_15min:ingest_news_15min",
        cron="*/15 * * * *",  # every 15 min
        description="News + social ingest (RSS, GDELT, Google News, CryptoPanic, ...).",
        stage=1,
        tags=("ingest", "news"),
    ),
    DeploymentSpec(
        name="ingest-self-custody-6h/prod",
        flow_path="pfip.prefect.flows.ingest_self_custody_6h:ingest_self_custody_6h",
        cron="30 0,6,12,18 * * *",  # 06/12/18/00 IST = 00:30/06:30/12:30/18:30 UTC
        description="Self-custody wallet balances (BTC/ETH/SOL) — every 6 hours.",
        stage=2,
        tags=("ingest", "self_custody"),
    ),
    # =================== DAILY MARKET DATA ===================
    DeploymentSpec(
        name="ingest-us-eod/prod",
        flow_path="pfip.prefect.flows.ingest_us_eod:ingest_us_eod",
        cron="0 17 * * 1-5",  # 22:30 IST weekdays — close + a bit
        description="US EOD: yfinance/Stooq/Tiingo OHLCV + SEC EDGAR + Finnhub.",
        stage=1,
        tags=("ingest", "us"),
    ),
    DeploymentSpec(
        name="ingest-india-eod/prod",
        flow_path="pfip.prefect.flows.ingest_india_eod:ingest_india_eod",
        cron="0 11 * * 1-5",  # 16:30 IST weekdays
        description="India EOD: jugaad/NSE+BSE bhavcopy/FII-DII/F&O/PIT.",
        stage=1,
        tags=("ingest", "in"),
    ),
    DeploymentSpec(
        name="ingest-mf-daily/prod",
        flow_path="pfip.prefect.flows.ingest_mf_daily:ingest_mf_daily",
        cron="30 16 * * *",  # 22:00 IST daily
        description="AMFI mutual fund NAVs.",
        stage=1,
        tags=("ingest", "mf"),
    ),
    DeploymentSpec(
        name="ingest-fx-daily/prod",
        flow_path="pfip.prefect.flows.ingest_fx_daily:ingest_fx_daily",
        cron="0 12 * * *",  # 17:30 IST daily
        description="FX rates: Frankfurter ECB + RBI reference + FRED FX.",
        stage=1,
        tags=("ingest", "fx"),
    ),
    DeploymentSpec(
        name="ingest-macro-daily/prod",
        flow_path="pfip.prefect.flows.ingest_macro_daily:ingest_macro_daily",
        cron="30 21 * * *",  # 03:00 IST next day = 21:30 UTC same day
        description="Macro: FRED + DBnomics + World Bank + MOSPI.",
        stage=1,
        tags=("ingest", "macro"),
    ),
    # =================== WEEKLY ===================
    DeploymentSpec(
        name="ingest-fundamentals-weekly/prod",
        flow_path="pfip.prefect.flows.ingest_fundamentals_weekly:ingest_fundamentals_weekly",
        cron="30 22 * * 5",  # Sat 04:00 IST = Fri 22:30 UTC
        description="Weekly fundamentals: SEC EDGAR + Screener + Finnhub + NDL.",
        stage=2,
        tags=("ingest", "fundamentals"),
    ),
    DeploymentSpec(
        name="ingest-arxiv-weekly/prod",
        flow_path="pfip.prefect.flows.ingest_arxiv_weekly:ingest_arxiv_weekly",
        cron="30 3 * * 6",  # Saturday 09:00 IST = Sat 03:30 UTC
        description="arXiv q-fin weekly digest.",
        stage=3,
        tags=("ingest", "research"),
    ),
    # =================== COMPUTE PIPELINES ===================
    DeploymentSpec(
        name="compute-features-daily/prod",
        flow_path="pfip.prefect.flows.compute_features_daily:compute_features_daily",
        cron="30 0 * * *",  # 06:00 IST daily
        description="Compute daily features (RSI/MACD/vol/etc.).",
        stage=2,
        tags=("features",),
    ),
    DeploymentSpec(
        name="regime-detect-daily/prod",
        flow_path="pfip.prefect.flows.regime_detect_daily:regime_detect_daily_flow",
        cron="0 1 * * *",  # 06:30 IST daily
        description="Daily HMM regime detection.",
        stage=2,
        tags=("regime", "ml"),
    ),
    DeploymentSpec(
        name="signals-generate-daily/prod",
        flow_path="pfip.prefect.flows.signals_generate_daily:signals_generate_daily",
        cron="15 1 * * *",  # 06:45 IST daily (after regime)
        description="Generate signals after features + regime.",
        stage=3,
        tags=("signals", "ml"),
    ),
    DeploymentSpec(
        name="classify-news-backlog/prod",
        flow_path="pfip.prefect.flows.classify_news_backlog:classify_news_backlog_flow",
        cron="*/30 * * * *",  # every 30 min — drain sentiment queue
        description="Score un-scored news rows via FinBERT/CryptoBERT.",
        stage=2,
        tags=("news", "ml"),
    ),
    # =================== USER-FACING DIGESTS ===================
    DeploymentSpec(
        name="morning-brief/prod",
        flow_path="pfip.prefect.flows.morning_brief:morning_brief",
        cron="30 1 * * *",  # 07:00 IST daily
        description="Morning brief to dashboard + Telegram.",
        stage=2,
        tags=("brief",),
    ),
    DeploymentSpec(
        name="market-close-summary/prod",
        flow_path="pfip.prefect.flows.market_close_summary:market_close_summary",
        cron="0 12 * * 1-5",  # 17:30 IST weekdays
        description="End-of-day market close summary (weekdays only).",
        stage=2,
        tags=("brief",),
    ),
    # =================== PORTFOLIO + REVIEW ===================
    DeploymentSpec(
        name="shadow-reconcile-daily/prod",
        flow_path="pfip.prefect.flows.shadow_reconcile_daily:shadow_reconcile_daily_flow",
        cron="0 18 * * *",  # 23:30 IST daily
        description="Shadow portfolio daily reconciliation.",
        stage=4,
        tags=("shadow",),
    ),
    DeploymentSpec(
        name="weekly-post-mortem/prod",
        flow_path="pfip.prefect.flows.weekly_review:weekly_review",
        cron="30 13 * * 0",  # Sunday 19:00 IST
        description="Weekly decision-journal post-mortem.",
        stage=3,
        tags=("review",),
    ),
    # =================== MONTHLY ROLLUPS ===================
    DeploymentSpec(
        name="monthly-calibration/prod",
        flow_path="pfip.prefect.flows.calibration_monthly:calibration_monthly_flow",
        cron="30 4 1-7 * 6",  # First Saturday 10:00 IST
        description="Monthly confidence calibration report (Brier/ECE).",
        stage=4,
        tags=("calibration", "ml"),
    ),
    DeploymentSpec(
        name="monthly-shadow-rollup/prod",
        flow_path="pfip.prefect.flows.shadow_rollup_monthly:shadow_rollup_monthly",
        cron="30 13 25-31 * 0",  # Last Sunday 19:00 IST
        description="Monthly shadow-vs-actual portfolio reconciliation.",
        stage=4,
        tags=("shadow", "review"),
    ),
    # =================== OPS / DISASTER RECOVERY ===================
    DeploymentSpec(
        name="backup-daily/prod",
        flow_path="pfip.prefect.flows.backup_daily:backup_daily",
        cron="0 19 * * *",  # 00:30 IST daily (after the day's writes)
        description="Nightly pg_dump + Qdrant snapshot + retention prune.",
        stage=1,
        tags=("ops", "backup"),
    ),
]


# -----------------------------------------------------------------------------
# Implementation
# -----------------------------------------------------------------------------


def _resolve_flow(flow_path: str) -> Callable:
    if ":" not in flow_path:
        raise ValueError(f"flow_path must be 'module:callable' (got {flow_path!r})")
    module_name, attr = flow_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _require_prefect() -> None:
    try:
        import prefect  # noqa: F401
        from prefect.client.schemas.schedules import CronSchedule  # noqa: F401
        from prefect.deployments import Deployment  # noqa: F401
    except ImportError as e:
        LOG.error("Prefect not installed in this env: %s", e)
        LOG.error("Run inside the backend container: docker exec pfip-backend python …")
        sys.exit(2)


def cmd_plan(args: argparse.Namespace) -> int:
    print(f"{'NAME':46s} {'STAGE':5s} {'CRON':16s} DESCRIPTION")
    print("-" * 110)
    for d in DEPLOYMENTS:
        print(f"{d.name:46s} {d.stage:<5d} {d.cron:16s} {d.description}")
    print(f"\nTotal deployments: {len(DEPLOYMENTS)}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    _require_prefect()
    from prefect.client.schemas.schedules import CronSchedule
    from prefect.deployments import Deployment

    active_stage: int = args.stage
    applied = 0
    skipped = 0

    for d in DEPLOYMENTS:
        try:
            flow_fn = _resolve_flow(d.flow_path)
        except Exception as e:  # noqa: BLE001
            LOG.warning("skip %s — flow import failed (%s)", d.name, e)
            skipped += 1
            continue

        is_paused = active_stage < d.stage
        try:
            schedule = CronSchedule(cron=d.cron, timezone="UTC")
            _flow_name, deploy_name = d.name.split("/", 1)
            Deployment.build_from_flow(
                flow=flow_fn,
                name=deploy_name,
                schedule=schedule,
                tags=list(d.tags),
                description=d.description,
                work_pool_name=d.work_pool,
                is_schedule_active=not is_paused,
                apply=True,
            )
            state = "PAUSED" if is_paused else "ACTIVE"
            LOG.info("applied %s [%s] cron=%s", d.name, state, d.cron)
            applied += 1
        except Exception as e:  # noqa: BLE001
            LOG.error("failed to apply %s: %s", d.name, e)
            skipped += 1

    print(f"applied={applied} skipped={skipped}")
    return 0 if applied > 0 else 1


def _flip_active(active: bool) -> int:
    _require_prefect()
    from prefect.client.orchestration import get_client

    async def _run() -> None:
        touched = 0
        async with get_client() as client:
            for d in DEPLOYMENTS:
                flow_name, deploy_name = d.name.split("/", 1)
                try:
                    dep = await client.read_deployment_by_name(name=f"{flow_name}/{deploy_name}")
                    await client.update_deployment(deployment_id=dep.id, is_schedule_active=active)
                    touched += 1
                except Exception as e:  # noqa: BLE001
                    LOG.warning("skip %s — %s", d.name, e)
        print(f"{'resumed' if active else 'paused'}={touched}")

    import asyncio

    asyncio.run(_run())
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    return _flip_active(active=False)


def cmd_resume(args: argparse.Namespace) -> int:
    return _flip_active(active=True)


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="PFIP Prefect deployment registry.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="List deployments (no writes).")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="Create/update all deployments.")
    p_apply.add_argument(
        "--stage",
        type=int,
        default=4,
        help="Active PFIP stage. Deployments whose stage > this value register PAUSED.",
    )
    p_apply.set_defaults(func=cmd_apply)

    sub.add_parser("pause", help="Pause all PFIP deployments.").set_defaults(func=cmd_pause)
    sub.add_parser("resume", help="Resume all PFIP deployments.").set_defaults(func=cmd_resume)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
