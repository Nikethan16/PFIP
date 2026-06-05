"""Idempotency keys for ingest batches.

Every batch an adapter writes carries a deterministic key:

    sha256(source || symbol || timeframe || start_iso || end_iso || extra_json)

Stored in ``source_health.last_batch_key``. Before inserting a batch
the adapter calls :func:`batch_already_ingested` — if the key matches
the last recorded one for this source we skip the write entirely.

This eliminates a class of double-writes that arises when:

- Prefect retries a flow that already committed its inserts.
- Two manual triggers race during a backfill.
- A flow crashes after insert-commit but before source_health update.

The key intentionally includes ``timeframe`` so 1d and 1h batches don't
collide for the same date range.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any


def make_batch_key(
    *,
    source: str,
    symbol: str,
    timeframe: str | None = None,
    start: date | datetime | None = None,
    end: date | datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Compute the deterministic SHA-256 key for a batch.

    All parts are coerced to strings via the canonical ISO format for
    date/datetime; ``None`` becomes the empty string. ``extra`` is
    serialized as JSON with sorted keys so dict ordering doesn't matter.
    """
    parts = [
        source,
        symbol,
        timeframe or "",
        _to_iso(start),
        _to_iso(end),
        json.dumps(extra or {}, sort_keys=True, default=str),
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _to_iso(v: date | datetime | None) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    return v.isoformat()


__all__ = ["make_batch_key"]
