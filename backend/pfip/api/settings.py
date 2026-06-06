"""User settings router — single-row preferences for the single-user app.

Backs the frontend ``useUserSettings`` / ``useUpdateUserSettings`` hooks and
the settings page. ``GET /settings`` returns the current settings (seeded from
``core.config.Settings`` defaults the first time, before any row exists);
``PATCH /settings`` (and ``PUT`` as an alias) upserts a partial patch onto the
stored row. Both require auth.

The persisted shape mirrors the frontend ``UserSettings`` Zod schema exactly so
the response validates client-side. Risk percentages are surfaced as
*whole-number percents* (``max_position_pct: 10`` ⇒ 10%), matching the form
inputs on the settings page — the config-layer defaults are stored as fractions
(0.10) and converted on seed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from pfip.api.deps import CurrentUser, DbSession, SettingsDep
from pfip.models.user_settings import UserSettingsRow

router = APIRouter(prefix="/settings", tags=["settings"])


# The canonical set of keys the frontend UserSettings schema expects. Anything
# stored under a key not in here is ignored on read so the response always
# validates against the Zod schema; a patch may only set these keys.
_ALLOWED_KEYS = {
    "max_position_pct",
    "drawdown_halt_pct",
    "daily_new_positions_cap",
    "tax_year",
    "alert_severity_threshold",
    "quiet_hours_start",
    "quiet_hours_end",
    "morning_brief_enabled",
    "telegram_alerts_enabled",
    "default_models_by_regime",
    "scheduled_tasks",
}


def _defaults(settings: Any) -> dict[str, Any]:
    """Seed the settings payload from ``core.config.Settings``.

    Risk fractions (0.10) are converted to whole-number percents (10) to match
    the frontend form. ``tax_year`` is derived from the configured FY start
    year (``2026-04-01`` ⇒ ``"2026-27"``).
    """
    start_year = int(settings.tax_year_start.split("-")[0])
    tax_year = f"{start_year}-{str((start_year + 1) % 100).zfill(2)}"
    return {
        "max_position_pct": round(float(settings.max_position_pct) * 100, 4),
        "drawdown_halt_pct": round(float(settings.drawdown_halt_pct) * 100, 4),
        "daily_new_positions_cap": int(settings.daily_new_positions_cap),
        "tax_year": tax_year,
        "alert_severity_threshold": "warning",
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "morning_brief_enabled": bool(settings.feature_morning_brief),
        "telegram_alerts_enabled": False,
        "default_models_by_regime": {},
        "scheduled_tasks": [],
    }


def _merge(settings: Any, stored: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults overlaid with whatever is persisted (only allowed keys)."""
    out = _defaults(settings)
    if stored:
        for k, v in stored.items():
            if k in _ALLOWED_KEYS:
                out[k] = v
    return out


async def _load_row(db: Any) -> UserSettingsRow | None:
    res = await db.execute(select(UserSettingsRow).limit(1))
    return res.scalars().first()


@router.get("")
async def get_settings_endpoint(
    db: DbSession, _user: CurrentUser, settings: SettingsDep
) -> dict[str, Any]:
    """Return the current settings, seeded from config defaults if no row yet."""
    row = await _load_row(db)
    return _merge(settings, row.prefs if row else None)


@router.patch("")
async def patch_settings(
    patch: dict[str, Any], db: DbSession, _user: CurrentUser, settings: SettingsDep
) -> dict[str, Any]:
    """Upsert a partial settings patch and return the merged result."""
    row = await _load_row(db)
    current = dict(row.prefs) if (row and row.prefs) else {}
    for k, v in patch.items():
        if k in _ALLOWED_KEYS:
            current[k] = v

    if row is None:
        row = UserSettingsRow(prefs=current)
        db.add(row)
    else:
        row.prefs = current
    await db.commit()
    return _merge(settings, current)


# PUT as an alias for clients that send a full settings object via PUT.
@router.put("")
async def put_settings(
    patch: dict[str, Any], db: DbSession, _user: CurrentUser, settings: SettingsDep
) -> dict[str, Any]:
    return await patch_settings(patch, db, _user, settings)
