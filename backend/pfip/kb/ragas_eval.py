"""RAGAS evaluation harness for PFIP's knowledge-base RAG layer.

Reads ``backend/pfip/kb/eval_qa.json`` (50 hand-built Q&A pairs covering
Wyckoff, Lefèvre, Graham, Taleb, Dalio, Tharp, Ammous, López de Prado,
Indian tax law, regime detection, calibration, and ops). For each
question:

1. Calls :func:`pfip.kb.search.search` to retrieve the top-k chunks.
2. Asks the configured LLM to compose an answer grounded in those chunks.
3. Records the question / answer / contexts / ground-truth into a single
   pandas ``DataFrame`` that RAGAS can score.
4. Computes ``faithfulness``, ``answer_relevancy`` and
   ``context_precision`` metrics.
5. Logs the run to MLflow (params + per-metric values + per-Q breakdown
   as an artefact CSV).

The harness imports ``ragas`` and ``datasets`` lazily so that the rest of
PFIP boots even when those packages are absent. If RAGAS isn't installed,
:func:`run_eval` raises :class:`RagasMissingError` with a one-line
``pip install`` hint.

Public surface:

- :class:`RagasMissingError`
- :class:`EvalResult` — dataclass with overall scores + per-question rows.
- :func:`load_eval_set` — parse + validate the JSON file.
- :func:`run_eval` — end-to-end driver (await-able).
- :func:`save_results` — write a CSV next to ``.telemetry/`` for diffing.

This module is purposely **side-effect free at import time**. The MLflow
client is constructed inside :func:`run_eval` only.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from pfip.agent.llm_client import LLMUnavailable, get_llm_router
from pfip.core.config import get_settings
from pfip.kb.search import KBHit, search


_HERE = Path(__file__).resolve().parent
DEFAULT_EVAL_PATH = _HERE / "eval_qa.json"


class RagasMissingError(RuntimeError):
    """Raised when ``ragas`` / ``datasets`` are not installed."""


@dataclass(slots=True)
class EvalQuestion:
    """One row of the curated Q&A set."""

    id: str
    question: str
    expected_answer: str
    expected_sources: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalRow:
    """One run's output for one question."""

    qid: str
    question: str
    generated_answer: str
    retrieved_contexts: list[str]
    citations: list[str]
    expected_answer: str
    error: str | None = None


@dataclass(slots=True)
class EvalResult:
    """Aggregate result of an eval run."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    n_questions: int
    n_errors: int
    metrics: dict[str, float]  # faithfulness, answer_relevancy, context_precision, …
    rows: list[EvalRow]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_eval_set(path: Path | None = None) -> list[EvalQuestion]:
    """Parse the eval JSON. Tolerant of two shapes:

    - ``[{question, expected_answer, ...}, ...]`` — flat list.
    - ``{"questions": [...]}`` — wrapped.
    """
    src = path or DEFAULT_EVAL_PATH
    raw = json.loads(src.read_text(encoding="utf-8"))
    items = raw["questions"] if isinstance(raw, dict) and "questions" in raw else raw
    out: list[EvalQuestion] = []
    for i, row in enumerate(items):
        out.append(
            EvalQuestion(
                id=str(row.get("id") or f"q{i + 1:03d}"),
                question=row["question"],
                expected_answer=row.get("expected_answer") or row.get("answer", ""),
                expected_sources=list(row.get("expected_sources") or []),
                tags=list(row.get("tags") or []),
            )
        )
    if not out:
        raise ValueError(f"No questions in eval set at {src}")
    return out


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


_GROUNDED_PROMPT = (
    "You are answering a finance / trading / tax question using ONLY the "
    "snippets below as evidence. If the snippets don't answer the question, "
    "say so plainly — do not invent. Keep the answer under 200 words.\n\n"
    "QUESTION: {q}\n\n"
    "SNIPPETS:\n{ctx}\n\n"
    "ANSWER:"
)


def _format_contexts(hits: list[KBHit]) -> str:
    if not hits:
        return "(no snippets retrieved)"
    return "\n\n---\n\n".join(
        f"[{i + 1}] {h.text[:1500]}" for i, h in enumerate(hits)
    )


async def _answer_one(q: EvalQuestion, *, k: int) -> EvalRow:
    """Retrieve + generate one answer."""
    try:
        hits = await search(q.question, k=k)
    except Exception as exc:  # pragma: no cover — adapter errors
        return EvalRow(
            qid=q.id,
            question=q.question,
            generated_answer="",
            retrieved_contexts=[],
            citations=[],
            expected_answer=q.expected_answer,
            error=f"retrieval_failed: {exc}",
        )

    if not hits:
        return EvalRow(
            qid=q.id,
            question=q.question,
            generated_answer="(no relevant context retrieved — abstaining)",
            retrieved_contexts=[],
            citations=[],
            expected_answer=q.expected_answer,
        )

    prompt = _GROUNDED_PROMPT.format(q=q.question, ctx=_format_contexts(hits))
    try:
        router = get_llm_router()
        # KB content is non-sensitive — eligible for cloud routing via the
        # router's default QUICK_SUMMARY / PUBLIC task type.
        answer = await router.generate(prompt)
    except LLMUnavailable as exc:
        return EvalRow(
            qid=q.id,
            question=q.question,
            generated_answer="",
            retrieved_contexts=[h.text for h in hits],
            citations=[getattr(h, "citation", "?") for h in hits],
            expected_answer=q.expected_answer,
            error=f"llm_unavailable: {exc}",
        )

    return EvalRow(
        qid=q.id,
        question=q.question,
        generated_answer=answer.strip(),
        retrieved_contexts=[h.text for h in hits],
        citations=[getattr(h, "citation", "?") for h in hits],
        expected_answer=q.expected_answer,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _import_ragas() -> tuple[Any, Any, Any, Any]:
    """Late-import RAGAS bits. Raises :class:`RagasMissingError` on failure."""
    try:
        from datasets import Dataset  # type: ignore
        from ragas import evaluate  # type: ignore
        from ragas.metrics import (  # type: ignore
            answer_relevancy,
            context_precision,
            faithfulness,
        )
    except ImportError as exc:  # pragma: no cover — env-dependent
        raise RagasMissingError(
            "ragas / datasets not installed. Add to requirements:\n"
            "    ragas>=0.1.10\n    datasets>=2.18\n"
            "Then `docker compose --env-file .env build backend`."
        ) from exc
    return Dataset, evaluate, [faithfulness, answer_relevancy, context_precision], None


def _to_metric_dict(scores: Any) -> dict[str, float]:
    """RAGAS returns either a dict-like Result or a DataFrame depending on
    version. Normalize to a flat ``{metric: float}`` dict."""
    if hasattr(scores, "to_pandas"):
        df = scores.to_pandas()
        # take column means, skip non-numeric
        out: dict[str, float] = {}
        for col in df.columns:
            try:
                out[col] = float(df[col].astype(float).mean())
            except (ValueError, TypeError):
                continue
        return out
    if isinstance(scores, dict):
        return {k: float(v) for k, v in scores.items() if _is_number(v)}
    return {}


def _is_number(x: Any) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


async def run_eval(
    *,
    eval_path: Path | None = None,
    k: int = 5,
    log_to_mlflow: bool = True,
    sample: int | None = None,
) -> EvalResult:
    """Run the full eval pipeline.

    Args:
        eval_path: override path to ``eval_qa.json``.
        k: number of context chunks to retrieve per question.
        log_to_mlflow: if True, log scores + per-Q CSV as an MLflow run.
        sample: if set, run only the first ``sample`` questions (smoke test).
    """
    Dataset, evaluate, metrics, _ = _import_ragas()
    settings = get_settings()

    questions = load_eval_set(eval_path)
    if sample is not None:
        questions = questions[: max(1, sample)]

    started = datetime.now(timezone.utc)
    run_id = started.strftime("ragas-%Y%m%dT%H%M%SZ")
    logger.info("RAGAS eval starting: run={} n={} k={}", run_id, len(questions), k)

    # Concurrency is bounded because every question hits the LLM.
    sem = asyncio.Semaphore(4)

    async def _bounded(q: EvalQuestion) -> EvalRow:
        async with sem:
            return await _answer_one(q, k=k)

    rows: list[EvalRow] = await asyncio.gather(*[_bounded(q) for q in questions])

    # Build the dataset RAGAS expects.
    successful = [r for r in rows if r.generated_answer and not r.error]
    if not successful:
        finished = datetime.now(timezone.utc)
        return EvalResult(
            run_id=run_id,
            started_at=started,
            finished_at=finished,
            n_questions=len(rows),
            n_errors=len(rows),
            metrics={},
            rows=rows,
        )

    ds = Dataset.from_dict(
        {
            "question": [r.question for r in successful],
            "answer": [r.generated_answer for r in successful],
            "contexts": [r.retrieved_contexts for r in successful],
            "ground_truth": [r.expected_answer for r in successful],
        }
    )
    scores = evaluate(ds, metrics=metrics)
    metric_dict = _to_metric_dict(scores)
    finished = datetime.now(timezone.utc)

    if log_to_mlflow:
        try:
            _log_mlflow(run_id, metric_dict, rows, k=k, settings=settings)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("MLflow logging failed: {}", exc)

    return EvalResult(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        n_questions=len(rows),
        n_errors=sum(1 for r in rows if r.error),
        metrics=metric_dict,
        rows=rows,
    )


def _log_mlflow(
    run_id: str, metrics: dict[str, float], rows: list[EvalRow], *, k: int, settings: Any
) -> None:
    """Best-effort MLflow log. Quiet if MLflow tracking URI is unset."""
    import mlflow  # local import to keep cold-start fast

    tracking_uri = getattr(settings, "MLFLOW_TRACKING_URI", None) or "file:./mlruns"
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("ragas-eval")
    with mlflow.start_run(run_name=run_id):
        mlflow.log_param("k", k)
        mlflow.log_param("n_questions", len(rows))
        mlflow.log_param("n_errors", sum(1 for r in rows if r.error))
        for k_, v_ in metrics.items():
            try:
                mlflow.log_metric(k_, float(v_))
            except Exception:
                continue
        # Per-Q breakdown as artefact.
        import csv
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        ) as fp:
            writer = csv.writer(fp)
            writer.writerow(
                ["qid", "question", "answer", "expected", "n_ctx", "error"]
            )
            for r in rows:
                writer.writerow(
                    [
                        r.qid,
                        r.question,
                        r.generated_answer,
                        r.expected_answer,
                        len(r.retrieved_contexts),
                        r.error or "",
                    ]
                )
            artefact_path = fp.name
        mlflow.log_artifact(artefact_path, artifact_path="per_question.csv")


def save_results(result: EvalResult, out_path: Path) -> Path:
    """Write a flat CSV of per-question rows. Used for diffing across runs."""
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(
            [
                "run_id",
                "qid",
                "question",
                "answer",
                "expected",
                "n_ctx",
                "error",
            ]
        )
        for r in result.rows:
            writer.writerow(
                [
                    result.run_id,
                    r.qid,
                    r.question,
                    r.generated_answer,
                    r.expected_answer,
                    len(r.retrieved_contexts),
                    r.error or "",
                ]
            )
    return out_path


__all__ = [
    "DEFAULT_EVAL_PATH",
    "EvalQuestion",
    "EvalResult",
    "EvalRow",
    "RagasMissingError",
    "load_eval_set",
    "run_eval",
    "save_results",
]
