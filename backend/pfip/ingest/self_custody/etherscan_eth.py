"""Alias of :mod:`pfip.ingest.self_custody.etherscan`.

Etherscan-based ETH + ERC-20 address tracking. Naming alias matches the spec
in FEATURES.md M1.
"""

from __future__ import annotations

from pfip.ingest.self_custody.etherscan import (  # noqa: F401
    fetch_addresses,
    ingest_etherscan,
)

ingest_etherscan_eth = ingest_etherscan

__all__ = ["fetch_addresses", "ingest_etherscan", "ingest_etherscan_eth"]


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest_etherscan_eth())
