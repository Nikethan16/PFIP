"""Alias of :mod:`pfip.ingest.crypto.glassnode` — free-tier metrics.

The free Glassnode tier exposes ~10 metrics. The implementation is in the
``glassnode`` module; this alias matches the naming used in FEATURES.md.
"""

from __future__ import annotations

from pfip.ingest.crypto.glassnode import fetch_glassnode_metrics, ingest_glassnode

__all__ = ["fetch_glassnode_metrics", "ingest_glassnode"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_glassnode())
