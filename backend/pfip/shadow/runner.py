"""Shadow-portfolio orchestration entry point.

Wraps :mod:`pfip.shadow.reconcile` + :mod:`pfip.shadow.metrics` so that a
single call from a Prefect flow (or the CLI) executes the daily pass and
returns a self-describing summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pfip.shadow.metrics import shadow_vs_actual
from pfip.shadow.reconcile import ReconcileSummary, reconcile_daily

log = logging.getLogger(__name__)


@dataclass
class ShadowRunSummary:
    reconcile: ReconcileSummary
    vs_actual: dict[str, object]

    def headline(self) -> dict[str, object]:
        return {
            "accepted": self.reconcile.accepted,
            "rejected": self.reconcile.rejected,
            "equity_inr": self.reconcile.equity_inr,
            **{f"shadow_{k}": v for k, v in self.vs_actual["shadow"].items()},
        }


async def run_daily(session) -> ShadowRunSummary:
    """End-to-end daily shadow pass.

    Reads today's high-confidence signals, applies them under risk rules,
    marks-to-market the book, and computes shadow-vs-actual metrics.
    """
    reconcile = await reconcile_daily(session)
    vs_actual = await shadow_vs_actual(session)
    return ShadowRunSummary(reconcile=reconcile, vs_actual=vs_actual)
