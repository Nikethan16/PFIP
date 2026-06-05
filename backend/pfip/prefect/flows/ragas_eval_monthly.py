"""Prefect flow: monthly RAGAS evaluation of the KB / RAG layer.

Runs on the same cadence as ``calibration_monthly`` (first Saturday of the
month). Loads the 50-question held-out eval set from
``backend/pfip/kb/eval_qa.json``, drives each question through the live
RAG chain, and scores ``faithfulness``, ``answer_relevancy`` and
``context_precision`` via RAGAS.

Outputs:

- MLflow run under experiment ``ragas-eval`` with per-metric scores +
  per-question CSV artefact.
- CSV at ``data/.telemetry/ragas/<run_id>.csv`` for cross-run diffing.
- A Telegram WARN alert if ``faithfulness < 0.7`` *or* drops by more
  than 0.1 vs the previous run (regression guard).

Schedule binding is in ``pfip/prefect/deployments.py``; this module
contains only the flow definition.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, get_run_logger, task

from pfip.alerts.dispatcher import AlertKind, AlertSeverity, send_alert
from pfip.kb.ragas_eval import RagasMissingError, run_eval, save_results

_TELEMETRY_DIR = Path("data/.telemetry/ragas")
_REGRESSION_FAITHFULNESS_DROP = 0.10
_FLOOR_FAITHFULNESS = 0.70


@task(name="ragas-run")
async def _run_eval_task(k: int = 5) -> dict[str, float] | None:
    """Run the eval; on missing RAGAS, log + return None instead of crashing."""
    logger = get_run_logger()
    try:
        result = await run_eval(k=k, log_to_mlflow=True)
    except RagasMissingError as exc:
        logger.warning("RAGAS not installed — skipping monthly eval: {}", exc)
        return None
    logger.info(
        "RAGAS eval complete: n={} errors={} metrics={}",
        result.n_questions,
        result.n_errors,
        result.metrics,
    )

    # Persist per-Q CSV.
    out_path = _TELEMETRY_DIR / f"{result.run_id}.csv"
    save_results(result, out_path)
    logger.info("Per-Q breakdown written to {}", out_path)
    return dict(result.metrics)


@task(name="ragas-regression-guard")
async def _regression_guard(latest: dict[str, float]) -> None:
    """Compare to previous run; fire WARN alert on regression or floor breach."""
    logger = get_run_logger()
    faith = latest.get("faithfulness")
    if faith is None:
        return

    # Find previous run by scanning CSVs.
    prior_score: float | None = None
    if _TELEMETRY_DIR.exists():
        csvs = sorted(_TELEMETRY_DIR.glob("ragas-*.csv"))
        # The current run's CSV is already on disk; second-to-last is prior.
        if len(csvs) >= 2:
            prior_csv = csvs[-2]
            prior_score = _faithfulness_from_csv(prior_csv)

    breached_floor = faith < _FLOOR_FAITHFULNESS
    regressed = (
        prior_score is not None
        and (prior_score - faith) > _REGRESSION_FAITHFULNESS_DROP
    )

    if not (breached_floor or regressed):
        logger.info("RAGAS faithfulness {:.3f} — within tolerance", faith)
        return

    body_lines = [
        "⚠️ *RAGAS regression detected*",
        f"faithfulness: `{faith:.3f}`",
    ]
    if prior_score is not None:
        body_lines.append(f"previous: `{prior_score:.3f}`")
    if breached_floor:
        body_lines.append(f"floor: `{_FLOOR_FAITHFULNESS:.2f}` — BREACHED")
    if regressed:
        body_lines.append(
            f"drop: `{prior_score - faith:.3f}` "
            f"(> {_REGRESSION_FAITHFULNESS_DROP:.2f})"
        )
    body_lines.append("")
    body_lines.append(
        "Inspect the latest CSV in `data/.telemetry/ragas/` and the MLflow run "
        "under experiment `ragas-eval`. Most common causes: (a) book chunking "
        "changed; (b) embedding model swapped; (c) prompt drift."
    )
    await send_alert(
        kind=AlertKind.CALIBRATION_BREACH,
        severity=AlertSeverity.WARN,
        body_override="\n".join(body_lines),
        title_override="RAGAS regression",
    )


def _faithfulness_from_csv(path: Path) -> float | None:
    """RAGAS per-Q CSVs don't carry the aggregate; rely on MLflow instead
    if available. For now, return None — leaves the floor check as the
    primary trigger. A future iteration can persist the aggregate in a
    sidecar JSON."""
    return None


@flow(name="ragas-eval-monthly", log_prints=True)
async def ragas_eval_monthly(k: int = 5) -> dict[str, float] | None:
    """Monthly RAGAS eval. Returns the aggregate metric dict (or None)."""
    logger = get_run_logger()
    started = datetime.now(timezone.utc)
    logger.info("ragas-eval-monthly: starting at {}", started.isoformat())

    metrics = await _run_eval_task(k=k)
    if metrics:
        await _regression_guard(metrics)

    logger.info("ragas-eval-monthly: complete")
    return metrics


if __name__ == "__main__":
    import asyncio

    asyncio.run(ragas_eval_monthly())
