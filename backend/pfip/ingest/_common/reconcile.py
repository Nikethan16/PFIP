"""Cross-source price reconciliation.

For every symbol that has more than one source emitting OHLCV (e.g. BTC
from Coinbase + Kraken + Bybit, RELIANCE.NS from yfinance + jugaad-data),
compare the latest close across sources. If any pair diverges by more
than the configured threshold (default 0.5%), flag it.

The check catches:

- One vendor going stale while still returning the last cached value.
- A parser bug emitting prices in the wrong unit (e.g. INR vs paise).
- A corporate-action adjustment applied by one vendor and not another.

Output is a list of :class:`Divergence` records that the caller can
persist to disk + alert on. The module is pure-Python — the database
adapter is its caller, not its responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(slots=True)
class PriceObservation:
    """Latest close for a (symbol, source) pair."""

    symbol: str
    source: str
    ts: datetime
    close: float


@dataclass(slots=True)
class Divergence:
    """A reconciliation finding between two sources for one symbol."""

    symbol: str
    source_a: str
    source_b: str
    close_a: float
    close_b: float
    diff_pct: float  # signed; (close_a - close_b) / midpoint


def _pairwise_diff(a: PriceObservation, b: PriceObservation) -> float:
    """Signed percentage diff vs the midpoint (avoids 0-base singularity)."""
    mid = (a.close + b.close) / 2.0
    if mid == 0:
        return 0.0
    return (a.close - b.close) / mid


def reconcile_latest_closes(
    observations: Iterable[PriceObservation],
    *,
    threshold_pct: float = 0.005,
) -> list[Divergence]:
    """For each symbol with ≥2 sources, return all pairs exceeding the threshold.

    Args:
        observations: latest-close rows. One per (symbol, source) typically.
        threshold_pct: minimum |diff_pct| to flag (e.g. 0.005 = 0.5%).

    Returns:
        list sorted by absolute diff_pct descending.
    """
    by_symbol: dict[str, list[PriceObservation]] = {}
    for o in observations:
        by_symbol.setdefault(o.symbol, []).append(o)

    findings: list[Divergence] = []
    for symbol, obs in by_symbol.items():
        if len(obs) < 2:
            continue
        for i in range(len(obs)):
            for j in range(i + 1, len(obs)):
                a, b = obs[i], obs[j]
                diff = _pairwise_diff(a, b)
                if abs(diff) >= threshold_pct:
                    # Order: higher close first for stability.
                    if a.close >= b.close:
                        findings.append(
                            Divergence(
                                symbol=symbol,
                                source_a=a.source,
                                source_b=b.source,
                                close_a=a.close,
                                close_b=b.close,
                                diff_pct=diff,
                            )
                        )
                    else:
                        findings.append(
                            Divergence(
                                symbol=symbol,
                                source_a=b.source,
                                source_b=a.source,
                                close_a=b.close,
                                close_b=a.close,
                                diff_pct=-diff,
                            )
                        )
    findings.sort(key=lambda d: abs(d.diff_pct), reverse=True)
    return findings


__all__ = ["Divergence", "PriceObservation", "reconcile_latest_closes"]
