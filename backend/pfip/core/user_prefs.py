"""Shared loader for the operator's persisted preferences.

The settings page (``pfip.api.settings``) upserts a single ``user_settings``
row whose ``prefs`` JSONB blob holds the editable risk / alert / UI knobs in
*frontend* units (risk caps as whole-number percents, quiet hours as
``"HH:MM"`` strings, severity as a lowercase label). Historically the engines
(``RiskManager``, the alert dispatcher) ignored that blob and read only the
immutable ``core.config.Settings`` constants, so editing a limit in the UI was
a no-op.

This module closes that loop. :class:`UserPrefs` is a typed, *engine-native*
view of those knobs (risk caps as fractions, quiet hours as
``datetime.time``, severity as an :class:`~enum.Enum`-compatible uppercase
string) built by overlaying the persisted blob onto the config defaults — any
key that is unset (or unparseable) falls back to its ``Settings`` default, so
partial blobs and the "no row yet" case both behave correctly.

Callers:

    # async (FastAPI request / Prefect flow already in an event loop)
    prefs = await load_user_prefs(session)

    # async, opening its own session
    prefs = await load_user_prefs()

    # sync (rare — a non-async call site)
    prefs = load_user_prefs_sync()

Single-user app ⇒ at most one row; the first row wins.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.config import Settings, get_settings

# Engine-native fallbacks for the alert knobs. These mirror the dispatcher's
# module constants but are duplicated here to keep the dependency direction
# one-way (dispatcher -> user_prefs, never the reverse). Severity is carried
# as the uppercase string the ``AlertSeverity`` enum is keyed by, so the
# dispatcher can do ``AlertSeverity(prefs.alert_severity_threshold)`` without
# this module importing the enum.
_DEFAULT_QUIET_START = time(23, 0)
_DEFAULT_QUIET_END = time(7, 0)
_DEFAULT_SEVERITY = "WARN"

# Maps the frontend's lowercase severity labels (and a few synonyms) onto the
# canonical ``AlertSeverity`` enum values.
_SEVERITY_ALIASES = {
    "info": "INFO",
    "warning": "WARN",
    "warn": "WARN",
    "critical": "CRITICAL",
    "crit": "CRITICAL",
}
_VALID_SEVERITIES = {"INFO", "WARN", "CRITICAL"}


@dataclass(frozen=True, slots=True)
class UserPrefs:
    """Engine-native snapshot of the operator's editable preferences.

    Units differ from the persisted blob on purpose: the JSONB stores what the
    settings *form* shows (percents, ``"HH:MM"``, lowercase labels); this view
    stores what the *engines* consume (fractions, ``time``, enum-keyed
    uppercase severity).
    """

    # --- Risk (fractions, matching Settings.*_pct semantics) ---
    max_position_pct: float
    drawdown_halt_pct: float
    daily_new_positions_cap: int

    # --- Alerts ---
    # Minimum severity that may reach a live channel; anything below is
    # suppressed/digested by the dispatcher. One of INFO / WARN / CRITICAL.
    alert_severity_threshold: str
    quiet_hours_start: time
    quiet_hours_end: time
    telegram_alerts_enabled: bool

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, settings: Settings | None = None) -> "UserPrefs":
        """All-defaults instance (the "no row yet" case)."""
        s = settings or get_settings()
        return cls(
            max_position_pct=float(s.max_position_pct),
            drawdown_halt_pct=float(s.drawdown_halt_pct),
            daily_new_positions_cap=int(s.daily_new_positions_cap),
            alert_severity_threshold=_DEFAULT_SEVERITY,
            quiet_hours_start=_DEFAULT_QUIET_START,
            quiet_hours_end=_DEFAULT_QUIET_END,
            # No real ``feature_telegram_alerts`` field exists on Settings; this
            # preserves whatever env/getattr default the dispatcher used before.
            telegram_alerts_enabled=bool(getattr(s, "feature_telegram_alerts", False)),
        )

    @classmethod
    def from_stored(cls, stored: dict | None, settings: Settings | None = None) -> "UserPrefs":
        """Overlay a persisted ``prefs`` blob onto the config defaults.

        ``stored`` is the raw JSONB dict (frontend units). Every field falls
        back to its :meth:`from_config` value when the key is absent, ``None``,
        or fails to parse — so a partial blob never breaks an engine.
        """
        base = cls.from_config(settings)
        if not stored:
            return base

        return cls(
            max_position_pct=_pct_to_fraction(
                stored.get("max_position_pct"), base.max_position_pct
            ),
            drawdown_halt_pct=_pct_to_fraction(
                stored.get("drawdown_halt_pct"), base.drawdown_halt_pct
            ),
            daily_new_positions_cap=_as_int(
                stored.get("daily_new_positions_cap"), base.daily_new_positions_cap
            ),
            alert_severity_threshold=_normalize_severity(
                stored.get("alert_severity_threshold"), base.alert_severity_threshold
            ),
            quiet_hours_start=_parse_hhmm(stored.get("quiet_hours_start"), base.quiet_hours_start),
            quiet_hours_end=_parse_hhmm(stored.get("quiet_hours_end"), base.quiet_hours_end),
            telegram_alerts_enabled=_as_bool(
                stored.get("telegram_alerts_enabled"), base.telegram_alerts_enabled
            ),
        )


# ---------------------------------------------------------------------------
# Coercion helpers — each is total: bad input returns the fallback, never raises
# ---------------------------------------------------------------------------


def _pct_to_fraction(value: object, fallback: float) -> float:
    """Convert a stored whole-number percent (``10``) to a fraction (``0.10``).

    The settings form stores ``max_position_pct: 10`` meaning 10%. Engines
    compare against fractions, so divide by 100. Values already <= 1 are
    assumed to be fractions already (defensive — the form never sends those).
    """
    if value is None:
        return fallback
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    if f < 0:
        return fallback
    return f / 100.0 if f > 1.0 else f


def _as_int(value: object, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_bool(value: object, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_severity(value: object, fallback: str) -> str:
    """Map a stored severity label onto a canonical ``AlertSeverity`` value."""
    if value is None:
        return fallback
    key = str(value).strip().lower()
    mapped = _SEVERITY_ALIASES.get(key)
    if mapped is not None:
        return mapped
    upper = str(value).strip().upper()
    return upper if upper in _VALID_SEVERITIES else fallback


def _parse_hhmm(value: object, fallback: time) -> time:
    """Parse a ``"HH:MM"`` (or ``"HH:MM:SS"``) string into a ``time``."""
    if value is None:
        return fallback
    if isinstance(value, time):
        return value
    try:
        parts = str(value).strip().split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        if 0 <= hh < 24 and 0 <= mm < 60:
            return time(hh, mm)
    except (TypeError, ValueError, IndexError):
        pass
    return fallback


# ---------------------------------------------------------------------------
# DB-backed loaders
# ---------------------------------------------------------------------------


async def _load_row_prefs(session: AsyncSession) -> dict | None:
    """Return the single user_settings row's ``prefs`` blob, or ``None``."""
    # Imported lazily to avoid importing the ORM/model graph at module import
    # time (keeps this module cheap for the pure ``from_stored`` unit tests).
    from pfip.models.user_settings import UserSettingsRow

    res = await session.execute(select(UserSettingsRow).limit(1))
    row = res.scalars().first()
    return row.prefs if row is not None else None


async def load_user_prefs(
    session: AsyncSession | None = None, *, settings: Settings | None = None
) -> UserPrefs:
    """Load the operator's preferences, overlaid on config defaults.

    If ``session`` is given it is used as-is (typical: a FastAPI request or a
    Prefect flow already inside an event loop). Otherwise a short-lived session
    is opened from the process session factory.
    """
    if session is not None:
        stored = await _load_row_prefs(session)
        return UserPrefs.from_stored(stored, settings)

    from pfip.db.session import get_sessionmaker

    factory = get_sessionmaker()
    async with factory() as own_session:
        stored = await _load_row_prefs(own_session)
        return UserPrefs.from_stored(stored, settings)


def load_user_prefs_sync(*, settings: Settings | None = None) -> UserPrefs:
    """Synchronous fallback for the rare non-async call site.

    Opens its own event loop + session. Must NOT be called from inside a
    running event loop (use the async :func:`load_user_prefs` there); it raises
    ``RuntimeError`` in that case rather than dead-locking, and the caller
    should treat that as "fall back to config defaults".
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to drive our own.
        return asyncio.run(load_user_prefs(settings=settings))
    raise RuntimeError(
        "load_user_prefs_sync() called from within a running event loop; "
        "use `await load_user_prefs(session)` instead."
    )


__all__ = ["UserPrefs", "load_user_prefs", "load_user_prefs_sync"]
