"""
PFIP Prefect deployment registration — Section 12.2 of the plan.

Registers every scheduled task as a Prefect 2.x deployment with a CronSchedule.
All cron expressions are UTC (Prefect default). IST offsets are shown in
comments so the target local time is self-documenting.

Usage (from inside the `pfip-backend` container where Prefect is installed):

    # Create / update every deployment
    python /app/schedules/prefect_deployments.py apply

    # List what WOULD be applied, without writing
    python /app/schedules/prefect_deployments.py plan

    # Pause all PFIP deployments (e.g. during a multi-day absence)
    python /app/schedules/prefect_deployments.py pause

    # Resume all
    python /app/schedules/prefect_deployments.py resume

The module references flows that live in the `pfip.*` Python package. Not every
flow exists yet at Stage 0 — that is expected. `apply` skips any flow whose
import fails and logs the miss; register it on the stage it becomes real.

IMPORTANT: this file MUST be importable without Prefect's server being up. It
performs deployment registration only when `apply`/`pause`/`resume` is invoked.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, List

LOG = logging.getLogger("pfip.schedules")

# -----------------------------------------------------------------------------
# Deployment spec
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DeploymentSpec:
    """Declarative spec for one Prefect deployment."""

    name: str
    """Deployment name. Referenced by scripts/ingest_btc.sh as `<flow>/<name>`."""

    flow_path: str
    """Dotted path to the flow function, e.g. `pfip.ingest.crypto.btc_daily:btc_daily_flow`.

    Prefect convention: `module.path:callable_name`.
    """

    cron: str
    """UTC cron expression."""

    description: str
    """Human-readable purpose."""

    stage: int
    """Stage this deployment goes live. Until then we register it PAUSED."""

    tags: tuple = field(default_factory=tuple)
    """Prefect tags for filtering in the UI."""

    work_pool: str = "default-agent-pool"


# -----------------------------------------------------------------------------
# The PFIP deployment catalogue — Section 12.2 verbatim.
#
#   IST = UTC + 5:30
#   07:00 IST = 01:30 UTC   -> cron: 30 1 * * *
#   17:30 IST = 12:00 UTC   -> cron: 0 12 * * *   (weekdays only -> * * 1-5)
#   23:30 IST = 18:00 UTC   -> cron: 0 18 * * *
#   Sunday 19:00 IST = Sunday 13:30 UTC -> cron: 30 13 * * 0
#   Saturday 09:00 IST = Saturday 03:30 UTC -> cron: 30 3 * * 6
#   First Saturday 10:00 IST = first Saturday 04:30 UTC
#     -> cron: 30 4 1-7 * 6   (day 1-7 that is a Saturday = first Saturday)
#   Last Sunday 19:00 IST = last Sunday 13:30 UTC
#     -> cron: 30 13 25-31 * 0  (day 25-31 that is a Sunday = last Sunday)
# -----------------------------------------------------------------------------

DEPLOYMENTS: List[DeploymentSpec] = [
    DeploymentSpec(
        name="ingest-btc-daily/prod",
        flow_path="pfip.flows.ingest_btc_daily:ingest_btc_daily",
        cron="5 0 * * *",  # 00:05 UTC daily
        description="Daily BTC OHLCV + on-chain + F&G ingest.",
        stage=1,
        tags=("ingest", "crypto"),
    ),
    DeploymentSpec(
        name="compute-features-daily/prod",
        flow_path="pfip.flows.compute_features_daily:compute_features_daily",
        cron="10 0 * * *",  # 00:10 UTC daily
        description="Daily feature engineering for active assets.",
        stage=1,
        tags=("features",),
    ),
    DeploymentSpec(
        name="morning-brief/prod",
        flow_path="pfip.flows.morning_brief:morning_brief",
        cron="30 1 * * *",  # 07:00 IST daily
        description="Daily morning brief to dashboard + Telegram.",
        stage=1,
        tags=("brief",),
    ),
    DeploymentSpec(
        name="market-close-summary/prod",
        flow_path="pfip.flows.market_close_summary:market_close_summary",
        cron="0 12 * * 1-5",  # 17:30 IST weekdays
        description="End-of-day market close summary (weekdays only).",
        stage=1,
        tags=("brief",),
    ),
    DeploymentSpec(
        name="shadow-reconcile-daily/prod",
        flow_path="pfip.flows.shadow_reconcile_daily:shadow_reconcile_daily",
        cron="0 18 * * *",  # 23:30 IST daily
        description="Shadow portfolio daily reconciliation (stub until Stage 4).",
        stage=4,
        tags=("shadow",),
    ),
    DeploymentSpec(
        name="weekly-post-mortem/prod",
        flow_path="pfip.flows.weekly_post_mortem:weekly_post_mortem",
        cron="30 13 * * 0",  # Sunday 19:00 IST
        description="Weekly decision-journal post-mortem (agent-drafted).",
        stage=3,
        tags=("review",),
    ),
    DeploymentSpec(
        name="arxiv-digest/prod",
        flow_path="pfip.flows.arxiv_digest:arxiv_digest",
        cron="30 3 * * 6",  # Saturday 09:00 IST
        description="Weekly arXiv q-fin 'papers worth reading' digest.",
        stage=3,
        tags=("research",),
    ),
    DeploymentSpec(
        name="monthly-calibration/prod",
        flow_path="pfip.flows.monthly_calibration:monthly_calibration",
        cron="30 4 1-7 * 6",  # First Saturday 10:00 IST
        description="Monthly confidence calibration report + Sharpe rollup.",
        stage=4,
        tags=("calibration", "ml"),
    ),
    DeploymentSpec(
        name="monthly-shadow-rollup/prod",
        flow_path="pfip.flows.monthly_shadow_rollup:monthly_shadow_rollup",
        cron="30 13 25-31 * 0",  # Last Sunday 19:00 IST
        description="Monthly shadow-vs-actual portfolio reconciliation.",
        stage=4,
        tags=("shadow", "review"),
    ),
]


# -----------------------------------------------------------------------------
# Implementation
# -----------------------------------------------------------------------------


def _resolve_flow(flow_path: str) -> Callable:
    """Import `module:callable`; raise ModuleNotFoundError on any failure."""
    if ":" not in flow_path:
        raise ValueError(f"flow_path must be 'module:callable' (got {flow_path!r})")
    module_name, attr = flow_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _require_prefect():
    try:
        import prefect  # noqa: F401
        from prefect.client.schemas.schedules import CronSchedule  # noqa: F401
        from prefect.deployments import Deployment  # noqa: F401
    except ImportError as e:
        LOG.error("Prefect not installed in this env: %s", e)
        LOG.error("Run inside the backend container: docker exec pfip-backend python …")
        sys.exit(2)


def cmd_plan(args: argparse.Namespace) -> int:
    """List every deployment that would be applied."""
    print(f"{'NAME':48s} {'STAGE':5s} {'CRON':18s} DESCRIPTION")
    print("-" * 110)
    for d in DEPLOYMENTS:
        print(f"{d.name:48s} {d.stage:<5d} {d.cron:18s} {d.description}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Register or update each deployment with Prefect."""
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

        # A deployment becomes active at `d.stage`; until then we register it PAUSED.
        is_paused = active_stage < d.stage

        try:
            schedule = CronSchedule(cron=d.cron, timezone="UTC")
            flow_name, deploy_name = d.name.split("/", 1)
            dep = Deployment.build_from_flow(
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

    async def _run():
        touched = 0
        async with get_client() as client:
            for d in DEPLOYMENTS:
                flow_name, deploy_name = d.name.split("/", 1)
                try:
                    dep = await client.read_deployment_by_name(
                        name=f"{flow_name}/{deploy_name}"
                    )
                    await client.update_deployment(
                        deployment_id=dep.id, is_schedule_active=active
                    )
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

    parser = argparse.ArgumentParser(
        description="Register PFIP Prefect deployments (Section 12.2)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="List deployments (no writes).")
    p_plan.set_defaults(func=cmd_plan)

    p_apply = sub.add_parser("apply", help="Create/update all deployments.")
    p_apply.add_argument(
        "--stage",
        type=int,
        default=0,
        help="Active PFIP stage. Deployments whose stage > this value register PAUSED.",
    )
    p_apply.set_defaults(func=cmd_apply)

    sub.add_parser("pause", help="Pause all PFIP deployments.").set_defaults(
        func=cmd_pause
    )
    sub.add_parser("resume", help="Resume all PFIP deployments.").set_defaults(
        func=cmd_resume
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
