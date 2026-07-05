"""Due-diligence aggregation router — ``/api/v1/diligence``.

``GET /diligence/{symbol}`` returns a single structured aggregate of everything
PFIP knows about an asset: last price + change, pivoted fundamentals (+ a curated
``key_metrics`` subset), recent regulatory filings, insider/PIT disclosures,
market-level FII/DII flows, on-chain metrics (crypto), the model's
regime/signal read, recent news, and an *honest* derived summary.

The heavy lifting lives in :func:`pfip.diligence.service.build_diligence` so the
chat agent's ``get_diligence`` tool and this endpoint share one implementation.

The endpoint **degrades gracefully**: any symbol with at least one OHLCV bar
returns 200 with empty/null sections where data is missing, never a 500. A
symbol that is entirely unknown (no OHLCV at all) returns 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from pfip.api.deps import CurrentUser, DbSession
from pfip.diligence.service import build_diligence

router = APIRouter(prefix="/diligence", tags=["diligence"])


# NOTE: registered BEFORE the ``/{symbol:path}`` catch-all so it isn't swallowed.
@router.get("/{symbol:path}/peers")
async def get_peers(symbol: str, db: DbSession, _user: CurrentUser) -> dict[str, Any]:
    """Compare ``symbol`` to its curated sector peers on valuation + quality
    ratios. Returns an empty comparison (never 404) when the symbol is ungrouped
    or peers lack stored metrics."""
    from pfip.diligence.peers import compare, load_key_metrics, peers_for

    peer_syms = peers_for(symbol)
    if not peer_syms:
        return {
            "target": symbol,
            "peers": [],
            "n_peers": 0,
            "fields": {},
            "note": "no curated peer group for this symbol",
        }
    metrics_by = await load_key_metrics(db, [symbol, *peer_syms])
    # Ensure the target has metrics even if only finnhub-prefixed ones exist.
    if symbol not in metrics_by and symbol.upper() not in {k.upper() for k in metrics_by}:
        agg = await build_diligence(db, symbol)
        km = ((agg.get("fundamentals") or {}).get("key_metrics")) or {}
        if km:
            metrics_by[symbol] = {k: float(v) for k, v in km.items() if isinstance(v, (int, float))}
    if len(metrics_by) < 2:
        return {
            "target": symbol,
            "peers": peer_syms,
            "n_peers": len(peer_syms),
            "fields": {},
            "note": "insufficient stored metrics for a comparison",
        }
    return compare(symbol, metrics_by)


@router.get("/{symbol:path}")
async def get_diligence(symbol: str, db: DbSession, _user: CurrentUser) -> dict:
    """Aggregate all known data for ``symbol``.

    ``symbol:path`` so dotted Indian tickers (``RELIANCE.NS``) and dashed crypto
    pairs (``BTC-USD``) pass through cleanly. Returns 404 only when the symbol is
    completely unknown to the platform (no OHLCV history); otherwise 200 with a
    gracefully-degraded aggregate.
    """
    result = await build_diligence(db, symbol)
    if not result.get("found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data for symbol {symbol!r} — unknown to the platform.",
        )
    return result


__all__ = ["router"]
