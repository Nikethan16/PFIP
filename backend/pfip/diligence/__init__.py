"""Due-diligence aggregation.

A single :func:`pfip.diligence.service.build_diligence` aggregates everything
PFIP knows about an asset (price, fundamentals, filings, insider activity,
institutional flows, on-chain metrics, the model's regime/signal read, and
recent news) into one structured, JSON-safe dict.

Both the ``/api/v1/diligence/{symbol}`` endpoint and the chat agent's
``get_diligence`` tool call this same function so there is exactly one
implementation of the aggregation logic.
"""

from __future__ import annotations

from pfip.diligence.service import build_diligence

__all__ = ["build_diligence"]
