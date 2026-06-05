"""Ad-hoc CLI wrapper around :mod:`pfip.kb.ragas_eval`.

Usage (inside the backend container):

    python -m pfip.scripts.run_ragas_eval                 # full run, MLflow log
    python -m pfip.scripts.run_ragas_eval --sample 5      # smoke test on 5 Q
    python -m pfip.scripts.run_ragas_eval --no-mlflow     # CSV only
    python -m pfip.scripts.run_ragas_eval --k 8           # bigger retrieval

Exits non-zero on RagasMissingError so CI can skip the eval cleanly when
the optional dependency isn't installed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pfip.kb.ragas_eval import RagasMissingError, run_eval, save_results


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run RAGAS eval on the KB RAG layer.")
    p.add_argument("--k", type=int, default=5, help="Top-k chunks per question")
    p.add_argument("--sample", type=int, default=None, help="Run only first N Qs")
    p.add_argument(
        "--no-mlflow",
        dest="mlflow",
        action="store_false",
        help="Skip MLflow logging (CSV only)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/.telemetry/ragas/adhoc.csv"),
        help="CSV path for per-question rows",
    )
    p.set_defaults(mlflow=True)
    return p.parse_args()


async def _main() -> int:
    args = _parse_args()
    try:
        result = await run_eval(
            k=args.k,
            log_to_mlflow=args.mlflow,
            sample=args.sample,
        )
    except RagasMissingError as exc:
        print(f"[ragas] skipped: {exc}", file=sys.stderr)
        return 2

    save_results(result, args.out)

    summary = {
        "run_id": result.run_id,
        "n_questions": result.n_questions,
        "n_errors": result.n_errors,
        "metrics": result.metrics,
        "csv": str(args.out),
    }
    print(json.dumps(summary, indent=2))
    return 0 if result.n_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
