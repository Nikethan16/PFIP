"""Alias of :mod:`pfip.ingest.commodities.lbma_gold` (LBMA gold/silver fix)."""

from __future__ import annotations

from pfip.ingest.commodities.lbma_gold import fetch_lbma, ingest_lbma_gold

ingest_lbma_fix = ingest_lbma_gold
fetch_lbma_fix = fetch_lbma

__all__ = ["fetch_lbma", "fetch_lbma_fix", "ingest_lbma_fix", "ingest_lbma_gold"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_lbma_fix())
