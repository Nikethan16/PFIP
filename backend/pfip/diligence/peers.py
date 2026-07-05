"""Peer comparison for diligence / Deep Research.

Answers "how does this company's valuation + quality stack up against its
peers?" — the context a single P/E number can't give. Peers come from a curated
sector map (the tracked universe is too small to derive peers from data alone),
and the ranking itself is a pure function over already-normalised key metrics,
so it's unit-testable without a DB or network.
"""

from __future__ import annotations

from statistics import median
from typing import Any

# Finnhub stores metrics under ``finnhub_<key>`` names; map the ones we compare
# on to our canonical field names so tracked US names (finnhub-sourced) and
# researched names (canonical) compare on the same axis.
_FINNHUB_ALIAS: dict[str, str] = {
    "finnhub_peTTM": "pe_ratio",
    "finnhub_pbAnnual": "pb_ratio",
    "finnhub_pb": "pb_ratio",
    "finnhub_roeTTM": "roe",
    "finnhub_roaeTTM": "roe",
    "finnhub_roiTTM": "roce",
    "finnhub_netProfitMarginTTM": "net_margin",
    "finnhub_operatingMarginTTM": "operating_margin",
    "finnhub_revenueGrowthTTMYoy": "revenue_growth",
    "finnhub_totalDebt/totalEquityQuarterly": "debt_to_equity",
    "finnhub_currentDividendYieldTTM": "dividend_yield",
}

# Curated sector peer groups. Symbols use the app's canonical form (``.NS`` for
# NSE, bare for US). A company is compared against the others in its group.
PEER_GROUPS: dict[str, list[str]] = {
    "us_megacap_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "us_semis": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "MU"],
    "india_it": ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "india_banks": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS"],
    "india_energy": ["RELIANCE.NS", "ONGC.NS", "IOC.NS", "BPCL.NS", "GAIL.NS"],
}

# Metrics we compare on, with the direction that is "better" (so ranking is
# meaningful): higher ROE/margins/growth is better; lower P/E, P/B, D/E is
# better (cheaper / less levered).
COMPARE_FIELDS: dict[str, str] = {
    "pe_ratio": "lower",
    "pb_ratio": "lower",
    "roe": "higher",
    "roce": "higher",
    "net_margin": "higher",
    "operating_margin": "higher",
    "revenue_growth": "higher",
    "debt_to_equity": "lower",
    "dividend_yield": "higher",
}


def peers_for(symbol: str) -> list[str]:
    """Peer symbols for ``symbol`` (its group minus itself). Empty if ungrouped."""
    up = symbol.upper()
    for group in PEER_GROUPS.values():
        if up in (s.upper() for s in group):
            return [s for s in group if s.upper() != up]
    return []


def _rank(target: float, peer_values: list[float], better: str) -> dict[str, Any]:
    """Where the target sits among peers for one metric."""
    peers = [v for v in peer_values if v is not None]
    if not peers:
        return {"peer_median": None, "rank": None, "n_peers": 0, "better_than_pct": None}
    med = float(median(peers))
    if better == "higher":
        beaten = sum(1 for v in peers if target > v)  # peers the target beats
        ahead = sum(1 for v in peers if v > target)  # peers ahead of the target
    else:  # lower is better
        beaten = sum(1 for v in peers if target < v)
        ahead = sum(1 for v in peers if v < target)
    return {
        "peer_median": round(med, 4),
        "rank": ahead + 1,  # 1 = best in the cohort (nobody ahead)
        "n_peers": len(peers),
        "better_than_pct": round(beaten / len(peers) * 100, 1),
    }


def compare(
    target_symbol: str,
    metrics_by_symbol: dict[str, dict[str, Any]],
    *,
    fields: dict[str, str] = COMPARE_FIELDS,
) -> dict[str, Any]:
    """Compare ``target_symbol``'s metrics to its peers'.

    ``metrics_by_symbol`` maps symbol → its ``key_metrics`` dict (target + peers).
    Returns a per-field comparison (target value, peer median, rank, and the %
    of peers it beats on that metric's "better" direction).
    """
    target = (
        metrics_by_symbol.get(target_symbol) or metrics_by_symbol.get(target_symbol.upper()) or {}
    )
    peer_syms = [s for s in metrics_by_symbol if s.upper() != target_symbol.upper()]
    per_field: dict[str, Any] = {}
    for field, better in fields.items():
        tv = target.get(field)
        if tv is None:
            continue
        peer_vals = [metrics_by_symbol[s].get(field) for s in peer_syms]
        per_field[field] = {"target": tv, "better": better, **_rank(float(tv), peer_vals, better)}
    return {
        "target": target_symbol,
        "peers": sorted(peer_syms),
        "n_peers": len(peer_syms),
        "fields": per_field,
        "disclaimer": (
            "Peer comparison over available metrics only — not all peers may have "
            "every ratio, and sector groupings are curated. Research aid, not advice."
        ),
    }


async def load_key_metrics(session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Latest canonical comparison metrics per symbol from the ``fundamentals``
    table (canonical fields + finnhub aliases). Symbols with no stored metrics
    are omitted. Best-effort; never raises."""
    if not symbols:
        return {}
    from sqlalchemy import bindparam, text

    wanted_canon = set(COMPARE_FIELDS)
    wanted_fields = wanted_canon | set(_FINNHUB_ALIAS)
    out: dict[str, dict[str, Any]] = {}
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (symbol, field) symbol, field, value "
                    "FROM fundamentals WHERE upper(symbol) IN :syms AND field IN :fields "
                    "ORDER BY symbol, field, as_of_date DESC"
                ).bindparams(
                    bindparam("syms", expanding=True), bindparam("fields", expanding=True)
                ),
                {
                    "syms": [s.upper() for s in symbols]
                    + [s.split(".")[0].upper() for s in symbols],
                    "fields": list(wanted_fields),
                },
            )
        ).all()
    except Exception:  # noqa: BLE001
        return {}
    # Index rows back onto the requested symbols (match on symbol or its base).
    base_to_full = {s.split(".")[0].upper(): s for s in symbols}
    full_upper = {s.upper(): s for s in symbols}
    for sym, field, value in rows:
        target = full_upper.get(sym.upper()) or base_to_full.get(sym.upper())
        if not target or value is None:
            continue
        canon = field if field in wanted_canon else _FINNHUB_ALIAS.get(field)
        if not canon:
            continue
        out.setdefault(target, {}).setdefault(canon, float(value))
    return out


__all__ = ["PEER_GROUPS", "COMPARE_FIELDS", "peers_for", "compare", "load_key_metrics"]
