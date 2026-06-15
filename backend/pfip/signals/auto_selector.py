"""Regime → model auto-selector.

Per plan §7.2: at Stage 4, the auto-selector is a **hand-coded mapping**
from regime label to which signal model to use per asset. The trained
auto-selector (Stage 6+) requires 12+ months of live regime labels and
per-model performance data we don't yet have.

This module provides:

- ``select_model_for(regime, asset)`` — returns the (model_name, version)
  tuple for the regime's preferred specialist.
- ``record_selection(...)`` — logs the selection to MLflow + ``model_events``
  table so we can later evaluate which mappings worked.
- ``recommended_overrides`` — config-driven asset-specific overrides
  (e.g. "for SOL-USD in high_vol, override to xgb_volatility_v2").

The mapping below is the one published in WHY_AND_WHAT.md §7.2:

    bull_trend / bear_trend   → lgbm_trend_specialist
    sideways                  → xgb_meanrev_specialist + ttm_short
    high_volatility           → catboost_riskoff (halved position sizing)
    accumulation/distribution → ensemble (lgbm + xgb + catboost) + on-chain

If a regime label isn't recognised, we fall back to the trend specialist
under the principle "when in doubt, trend > mean-reversion > nothing".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ModelSelection:
    primary_model: str
    primary_version: str
    ensemble: tuple[str, ...]
    position_size_multiplier: float
    reason: str


# ---------------------------------------------------------------------------
# The mapping
# ---------------------------------------------------------------------------


_DEFAULT_MAPPING: dict[str, ModelSelection] = {
    "bull_trend": ModelSelection(
        primary_model="lgbm_trend_specialist",
        primary_version="v1",
        ensemble=("lgbm_trend_specialist",),
        position_size_multiplier=1.0,
        reason="Trend regime: boosted trees excel at momentum continuation.",
    ),
    "bear_trend": ModelSelection(
        primary_model="lgbm_trend_specialist",
        primary_version="v1",
        ensemble=("lgbm_trend_specialist",),
        position_size_multiplier=0.75,
        reason="Bear trend: same specialist, position size reduced (asymmetric tail risk).",
    ),
    "sideways": ModelSelection(
        primary_model="xgb_meanrev_specialist",
        primary_version="v1",
        ensemble=("xgb_meanrev_specialist", "ttm_short_horizon"),
        position_size_multiplier=0.8,
        reason="Range-bound: mean-reversion + short-horizon foundation model.",
    ),
    "high_volatility": ModelSelection(
        primary_model="catboost_riskoff",
        primary_version="v1",
        ensemble=("catboost_riskoff",),
        position_size_multiplier=0.5,
        reason="High volatility: risk-off model, position size halved.",
    ),
    "accumulation": ModelSelection(
        primary_model="lgbm_trend_specialist",
        primary_version="v1",
        ensemble=("lgbm_trend_specialist", "xgb_meanrev_specialist", "catboost_riskoff"),
        position_size_multiplier=1.0,
        reason="Accumulation: needs more corroboration; full ensemble + on-chain.",
    ),
    "distribution": ModelSelection(
        primary_model="catboost_riskoff",
        primary_version="v1",
        ensemble=("lgbm_trend_specialist", "xgb_meanrev_specialist", "catboost_riskoff"),
        position_size_multiplier=0.5,
        reason="Distribution: smart-money distributing — defensive ensemble.",
    ),
}


# Per-asset overrides — populated via env or DB later. Empty by default;
# we trust the regime-based default until proven otherwise.
_OVERRIDES: dict[tuple[str, str], ModelSelection] = {}


def add_override(asset: str, regime: str, selection: ModelSelection) -> None:
    """Register a per-asset override at runtime. Used by Settings → Models page."""
    _OVERRIDES[(asset.upper(), regime)] = selection


def clear_override(asset: str, regime: str) -> bool:
    """Remove a previously-registered override. Returns True if one existed."""
    return _OVERRIDES.pop((asset.upper(), regime), None) is not None


def select_model_for(regime: str, asset: str) -> ModelSelection:
    """Return the model selection for an (asset, regime) pair.

    Lookup order:
        1. Asset+regime override (set via ``add_override``).
        2. Regime-based default from the published mapping.
        3. Fallback to ``bull_trend`` model (trend > nothing).
    """
    override = _OVERRIDES.get((asset.upper(), regime))
    if override is not None:
        return override
    return _DEFAULT_MAPPING.get(regime, _DEFAULT_MAPPING["bull_trend"])


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


async def record_selection(
    db: AsyncSession,
    *,
    asset: str,
    regime: str,
    selection: ModelSelection,
    notes: str | None = None,
) -> None:
    """Log the (asset, regime, selection) triple to model_events so we can
    later audit which mappings produced which signals. No-op if the table
    isn't present yet (graceful degradation on older deployments)."""
    try:
        await db.execute(
            sql_text("""
                INSERT INTO model_events
                    (kind, asset, regime, model_name, model_version,
                     position_size_multiplier, reason, notes, created_at)
                VALUES
                    ('auto_select', :asset, :regime, :model_name, :model_version,
                     :psize, :reason, :notes, :created_at)
                """),
            {
                "asset": asset.upper(),
                "regime": regime,
                "model_name": selection.primary_model,
                "model_version": selection.primary_version,
                "psize": selection.position_size_multiplier,
                "reason": selection.reason,
                "notes": notes,
                "created_at": datetime.now(tz=timezone.utc),
            },
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"record_selection failed (probably model_events table missing): {exc}")
        await db.rollback()


# ---------------------------------------------------------------------------
# Bulk: pick models for the whole watchlist + current regime per asset
# ---------------------------------------------------------------------------


async def select_for_watchlist(db: AsyncSession) -> list[dict[str, Any]]:
    """Return current model selection for every watchlist asset, joined
    with its latest regime label. Useful for the Settings → Models page
    and the model-router dashboard.
    """
    try:
        rows = (await db.execute(sql_text("""
                    SELECT w.symbol AS asset,
                           COALESCE(r.regime, 'bull_trend') AS regime,
                           r.since AS regime_since,
                           r.confidence AS regime_confidence
                    FROM watchlist w
                    LEFT JOIN LATERAL (
                        SELECT regime, since, confidence
                        FROM regime
                        WHERE symbol = w.symbol
                        ORDER BY since DESC
                        LIMIT 1
                    ) r ON true
                    ORDER BY w.added_at DESC
                    """))).mappings().all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"select_for_watchlist failed: {exc}")
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        sel = select_model_for(r["regime"], r["asset"])
        out.append(
            {
                "asset": r["asset"],
                "regime": r["regime"],
                "regime_since": r["regime_since"].isoformat() if r["regime_since"] else None,
                "regime_confidence": float(r["regime_confidence"] or 0.0),
                "primary_model": sel.primary_model,
                "primary_version": sel.primary_version,
                "ensemble": list(sel.ensemble),
                "position_size_multiplier": sel.position_size_multiplier,
                "reason": sel.reason,
            }
        )
    return out


__all__ = [
    "ModelSelection",
    "select_model_for",
    "add_override",
    "clear_override",
    "record_selection",
    "select_for_watchlist",
]
