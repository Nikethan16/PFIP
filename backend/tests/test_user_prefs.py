"""Tests for the persisted-preferences loop.

``pfip.core.user_prefs`` overlays the operator's persisted ``user_settings``
``prefs`` blob (frontend units: percents, ``"HH:MM"``, lowercase severity)
onto the immutable ``core.config.Settings`` defaults and exposes an
engine-native :class:`UserPrefs` (fractions, ``time``, uppercase severity).
The ``RiskManager`` and the alert dispatcher consume that view, so a value
edited on the settings page actually changes engine behaviour.

Coverage:
- ``UserPrefs.from_config`` — all-defaults snapshot mirrors Settings.
- ``UserPrefs.from_stored`` — override, partial fallback, unit conversion,
  bad-value tolerance, empty/None blob.
- ``load_user_prefs(session)`` — reads the single DB row's ``prefs`` blob.
- ``RiskManager`` — honours pref caps (position / drawdown / daily) over config,
  and ``from_prefs(session)`` reads the DB row.
- dispatcher — custom quiet window, severity threshold, and the
  ``telegram_alerts_enabled`` gate all flow from prefs into ``send_alert``.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pfip.alerts import dispatcher as disp
from pfip.alerts.dispatcher import AlertKind, AlertSeverity
from pfip.core.config import get_settings
from pfip.core.user_prefs import UserPrefs, load_user_prefs
from pfip.portfolio.risk_manager import RiskManager

# ---------------------------------------------------------------------------
# Fake async session mirroring the conftest pattern, but returning a chosen row
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, row) -> None:  # noqa: ANN001
        self._row = row

    def first(self):
        return self._row


class _Result:
    def __init__(self, row) -> None:  # noqa: ANN001
        self._row = row

    def scalars(self):
        return _Scalars(self._row)


class _RowSession:
    """Async-session stand-in whose ``execute`` returns a single prefs row."""

    def __init__(self, prefs: dict | None) -> None:
        # ``None`` ⇒ no row exists yet; a dict ⇒ a row carrying that blob.
        self._row = None if prefs is None else type("Row", (), {"prefs": prefs})()

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _Result(self._row)


# ---------------------------------------------------------------------------
# UserPrefs.from_config — defaults
# ---------------------------------------------------------------------------


def test_from_config_mirrors_settings_defaults():
    s = get_settings()
    prefs = UserPrefs.from_config(s)
    assert prefs.max_position_pct == pytest.approx(float(s.max_position_pct))
    assert prefs.drawdown_halt_pct == pytest.approx(float(s.drawdown_halt_pct))
    assert prefs.daily_new_positions_cap == int(s.daily_new_positions_cap)
    # Alert fallbacks: WARN threshold, 23:00–07:00 quiet window.
    assert prefs.alert_severity_threshold == "WARN"
    assert prefs.quiet_hours_start == time(23, 0)
    assert prefs.quiet_hours_end == time(7, 0)
    assert isinstance(prefs.telegram_alerts_enabled, bool)


# ---------------------------------------------------------------------------
# from_stored — override / fallback / conversion
# ---------------------------------------------------------------------------


def test_from_stored_overrides_all_keys():
    """A full blob (frontend units) overlays every default in engine units."""
    stored = {
        "max_position_pct": 5,  # 5% ⇒ 0.05
        "drawdown_halt_pct": 15,  # 15% ⇒ 0.15
        "daily_new_positions_cap": 4,
        "alert_severity_threshold": "critical",  # ⇒ CRITICAL
        "quiet_hours_start": "21:30",
        "quiet_hours_end": "06:15",
        "telegram_alerts_enabled": True,
    }
    prefs = UserPrefs.from_stored(stored)
    assert prefs.max_position_pct == pytest.approx(0.05)
    assert prefs.drawdown_halt_pct == pytest.approx(0.15)
    assert prefs.daily_new_positions_cap == 4
    assert prefs.alert_severity_threshold == "CRITICAL"
    assert prefs.quiet_hours_start == time(21, 30)
    assert prefs.quiet_hours_end == time(6, 15)
    assert prefs.telegram_alerts_enabled is True


def test_from_stored_partial_blob_falls_back_per_key():
    """Keys absent from the blob keep their config defaults."""
    base = UserPrefs.from_config()
    prefs = UserPrefs.from_stored({"max_position_pct": 7})
    assert prefs.max_position_pct == pytest.approx(0.07)  # overridden
    # everything else == defaults
    assert prefs.drawdown_halt_pct == base.drawdown_halt_pct
    assert prefs.daily_new_positions_cap == base.daily_new_positions_cap
    assert prefs.alert_severity_threshold == base.alert_severity_threshold
    assert prefs.quiet_hours_start == base.quiet_hours_start
    assert prefs.telegram_alerts_enabled == base.telegram_alerts_enabled


@pytest.mark.parametrize("blob", [None, {}])
def test_from_stored_empty_is_all_defaults(blob):
    assert UserPrefs.from_stored(blob) == UserPrefs.from_config()


def test_from_stored_tolerates_bad_values():
    """Unparseable values fall back rather than crashing an engine."""
    base = UserPrefs.from_config()
    stored = {
        "max_position_pct": "not-a-number",
        "drawdown_halt_pct": None,
        "daily_new_positions_cap": "x",
        "alert_severity_threshold": "bogus",
        "quiet_hours_start": "99:99",
        "quiet_hours_end": "??",
        "telegram_alerts_enabled": "yes",  # truthy string ⇒ True
    }
    prefs = UserPrefs.from_stored(stored)
    assert prefs.max_position_pct == base.max_position_pct
    assert prefs.drawdown_halt_pct == base.drawdown_halt_pct
    assert prefs.daily_new_positions_cap == base.daily_new_positions_cap
    assert prefs.alert_severity_threshold == base.alert_severity_threshold
    assert prefs.quiet_hours_start == base.quiet_hours_start
    assert prefs.quiet_hours_end == base.quiet_hours_end
    assert prefs.telegram_alerts_enabled is True  # "yes" parsed


def test_from_stored_fraction_passthrough():
    """A value already <= 1 is treated as a fraction (defensive)."""
    prefs = UserPrefs.from_stored({"max_position_pct": 0.25})
    assert prefs.max_position_pct == pytest.approx(0.25)


def test_severity_alias_warning_maps_to_warn():
    assert (
        UserPrefs.from_stored({"alert_severity_threshold": "warning"}).alert_severity_threshold
        == "WARN"
    )
    assert (
        UserPrefs.from_stored({"alert_severity_threshold": "INFO"}).alert_severity_threshold
        == "INFO"
    )


# ---------------------------------------------------------------------------
# DB-backed loader reads the single row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_user_prefs_reads_db_row():
    session = _RowSession(
        {"max_position_pct": 3, "telegram_alerts_enabled": True, "quiet_hours_start": "20:00"}
    )
    prefs = await load_user_prefs(session)
    assert prefs.max_position_pct == pytest.approx(0.03)
    assert prefs.telegram_alerts_enabled is True
    assert prefs.quiet_hours_start == time(20, 0)


@pytest.mark.asyncio
async def test_load_user_prefs_no_row_is_defaults():
    prefs = await load_user_prefs(_RowSession(None))
    assert prefs == UserPrefs.from_config()


# ---------------------------------------------------------------------------
# RiskManager consumes prefs
# ---------------------------------------------------------------------------


def test_risk_manager_position_cap_from_prefs():
    """A tighter pref cap rejects a position the config cap would pass.

    Config default cap is 10%. We set a 5% pref cap and propose an 8% position:
    fails under prefs, would pass under config.
    """
    prefs = UserPrefs.from_stored({"max_position_pct": 5})
    rm = RiskManager(prefs=prefs)
    verdict = rm.check_pre_trade(
        symbol="ACME",
        qty=Decimal("8"),
        price=Decimal("1000"),  # 8,000 notional
        existing_holdings=[],
        portfolio_value_inr=Decimal("100000"),  # 8% of portfolio
        stop_distance_pct=0.05,
        regime="bull",
        signal_confidence=70,
        news_count_24h=1,
    )
    assert verdict.per_item["position_size_within_cap"] is False
    # Same trade under config defaults (10% cap) passes the position check.
    rm_default = RiskManager()
    v2 = rm_default.check_pre_trade(
        symbol="ACME",
        qty=Decimal("8"),
        price=Decimal("1000"),
        existing_holdings=[],
        portfolio_value_inr=Decimal("100000"),
        stop_distance_pct=0.05,
        regime="bull",
        signal_confidence=70,
        news_count_24h=1,
    )
    assert v2.per_item["position_size_within_cap"] is True


def test_risk_manager_daily_cap_and_drawdown_from_prefs():
    prefs = UserPrefs.from_stored({"daily_new_positions_cap": 1, "drawdown_halt_pct": 10})
    rm = RiskManager(prefs=prefs)
    # Daily cap of 1: zero remaining once one position has been added today.
    assert rm.daily_new_positions_remaining(1) == 0
    # Drawdown halt at 10%: a 12% drawdown trips HALT.
    status, dd = rm.check_drawdown([Decimal("100"), Decimal("88")])
    assert status == "HALT"
    assert dd == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_risk_manager_from_prefs_reads_db_row():
    session = _RowSession({"daily_new_positions_cap": 5})
    rm = await RiskManager.from_prefs(session)
    assert rm.daily_new_positions_remaining(0) == 5


# ---------------------------------------------------------------------------
# Dispatcher: quiet hours from prefs
# ---------------------------------------------------------------------------


def test_is_quiet_hour_honours_custom_same_day_window():
    """A same-day (non-wrapping) window 09:00–17:00 IST."""
    # 12:00 IST = 06:30 UTC ⇒ inside.
    inside = datetime(2025, 5, 30, 6, 30, tzinfo=timezone.utc)
    # 20:00 IST = 14:30 UTC ⇒ outside.
    outside = datetime(2025, 5, 30, 14, 30, tzinfo=timezone.utc)
    assert disp._is_quiet_hour(inside, time(9, 0), time(17, 0)) is True
    assert disp._is_quiet_hour(outside, time(9, 0), time(17, 0)) is False


def test_is_quiet_hour_default_window_unchanged():
    """No start/end ⇒ legacy 23:00–07:00 IST behaviour (00:00 IST is quiet)."""
    midnight_ist = datetime(2025, 5, 30, 18, 30, tzinfo=timezone.utc)  # 00:00 IST
    assert disp._is_quiet_hour(midnight_ist) is True


# ---------------------------------------------------------------------------
# Dispatcher: send_alert reads prefs (threshold + quiet hours + telegram gate)
# ---------------------------------------------------------------------------


@pytest.fixture
def _no_redis(monkeypatch):
    """Make the dispatcher's redis a no-op so digest paths don't touch a server."""

    async def _none():
        return None

    monkeypatch.setattr(disp, "_get_redis", _none)


def _patch_prefs(monkeypatch, **overrides):
    """Force ``send_alert`` to see a specific UserPrefs without a DB."""
    base = UserPrefs.from_config()
    prefs = UserPrefs(
        max_position_pct=base.max_position_pct,
        drawdown_halt_pct=base.drawdown_halt_pct,
        daily_new_positions_cap=base.daily_new_positions_cap,
        alert_severity_threshold=overrides.get(
            "alert_severity_threshold", base.alert_severity_threshold
        ),
        quiet_hours_start=overrides.get("quiet_hours_start", base.quiet_hours_start),
        quiet_hours_end=overrides.get("quiet_hours_end", base.quiet_hours_end),
        telegram_alerts_enabled=overrides.get(
            "telegram_alerts_enabled", base.telegram_alerts_enabled
        ),
    )

    async def _fake_load():
        return prefs

    monkeypatch.setattr(disp, "_load_prefs_safe", _fake_load)
    return prefs


@pytest.mark.asyncio
async def test_send_alert_below_threshold_is_deferred(monkeypatch, _no_redis):
    """A WARN alert under a CRITICAL threshold is suppressed (digested)."""
    _patch_prefs(monkeypatch, alert_severity_threshold="CRITICAL")
    sent = []
    monkeypatch.setattr(disp, "_send_telegram", lambda *a, **k: sent.append((a, k)))
    res = await disp.send_alert(
        AlertKind.SIGNAL_FIRED, AlertSeverity.WARN, title_override="x", body_override="y"
    )
    assert res.get("deferred") == "below_threshold"
    assert sent == []  # never reached the transport


@pytest.mark.asyncio
async def test_send_alert_quiet_hours_from_prefs(monkeypatch, _no_redis):
    """A WARN at 12:00 IST is normally loud, but a 09:00–17:00 pref window defers it."""
    _patch_prefs(
        monkeypatch,
        alert_severity_threshold="INFO",  # don't let threshold short-circuit first
        quiet_hours_start=time(9, 0),
        quiet_hours_end=time(17, 0),
    )
    # Freeze "now" to 12:00 IST (06:30 UTC).
    fixed = datetime(2025, 5, 30, 6, 30, tzinfo=timezone.utc)

    class _FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(disp, "datetime", _FrozenDT)
    res = await disp.send_alert(
        AlertKind.SIGNAL_FIRED, AlertSeverity.WARN, title_override="x", body_override="y"
    )
    assert res.get("deferred") == "quiet_hours"


@pytest.mark.asyncio
async def test_send_alert_telegram_gate_flows_from_prefs(monkeypatch, _no_redis):
    """``telegram_alerts_enabled`` from prefs is passed to the transport as ``enabled``."""
    _patch_prefs(
        monkeypatch,
        alert_severity_threshold="INFO",
        telegram_alerts_enabled=True,
        # Wide-open quiet window that never fires (start == end ⇒ never quiet).
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
    )

    # Make rate cap pass and capture the transport call kwargs.
    async def _ok_rate(_r):
        return True

    captured = {}

    async def _fake_send(alert, *, force=False, enabled=None):  # noqa: ANN001
        captured["enabled"] = enabled
        captured["force"] = force
        return {"ok": True}

    monkeypatch.setattr(disp, "_check_rate_cap", _ok_rate)
    monkeypatch.setattr(disp, "_send_telegram", _fake_send)
    res = await disp.send_alert(
        AlertKind.SIGNAL_FIRED, AlertSeverity.WARN, title_override="x", body_override="y"
    )
    assert res == {"ok": True}
    assert captured["enabled"] is True  # the pref reached the transport
    assert captured["force"] is False


@pytest.mark.asyncio
async def test_send_telegram_enabled_override_gates_send(monkeypatch):
    """``enabled=False`` blocks a send even when the env flag would allow it;
    ``enabled=True`` lets it through to the HTTP layer."""
    # ``Settings`` is a frozen pydantic model with extra="ignore", so we can't
    # attach telegram_bot_token to it. The dispatcher only reads these via
    # getattr, so a lightweight namespace standing in for ``get_settings()``
    # gets us past the 'unconfigured' guard while ``feature_telegram_alerts``
    # stays falsey (proving ``enabled`` is the authoritative gate).
    fake_settings = SimpleNamespace(
        telegram_bot_token="tok",
        telegram_bot_chat_id="chat",
        feature_telegram_alerts=False,
    )
    monkeypatch.setattr(disp, "get_settings", lambda: fake_settings)

    alert = disp.Alert(
        kind=AlertKind.CUSTOM,
        severity=AlertSeverity.WARN,
        title="t",
        body="b",
        context={},
        timestamp=datetime.now(tz=timezone.utc),
    )
    # enabled=False ⇒ short-circuit, no HTTP.
    res_off = await disp._send_telegram(alert, enabled=False)
    assert res_off == {"ok": False, "reason": "feature_disabled"}

    # enabled=True ⇒ proceeds to HTTP (which we stub).
    posted = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):  # noqa: ANN001
            posted["url"] = url
            return _Resp()

    monkeypatch.setattr(disp.httpx, "AsyncClient", _Client)
    res_on = await disp._send_telegram(alert, enabled=True)
    assert res_on == {"ok": True, "code": 200}
    assert "sendMessage" in posted["url"]
