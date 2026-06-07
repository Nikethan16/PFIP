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

from fastapi import APIRouter, HTTPException, status

from pfip.api.deps import CurrentUser, DbSession
from pfip.diligence.service import build_diligence

router = APIRouter(prefix="/diligence", tags=["diligence"])


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
