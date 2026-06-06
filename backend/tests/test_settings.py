"""Smoke tests for GET/PATCH /settings (user settings router)."""

from __future__ import annotations

from fastapi.testclient import TestClient

# Field set the frontend UserSettingsSchema (frontend/lib/api.ts) requires.
_REQUIRED_FIELDS = {
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


def test_settings_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/settings").status_code == 401
    assert client.patch("/api/v1/settings", json={}).status_code == 401


def test_settings_get_returns_seeded_defaults(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert _REQUIRED_FIELDS.issubset(body.keys())

    # Risk percentages surface as whole-number percents (config stores 0.10).
    assert body["max_position_pct"] == 10
    assert body["drawdown_halt_pct"] == 20
    assert body["daily_new_positions_cap"] == 2
    # Derived FY from config tax_year_start (2026-04-01).
    assert body["tax_year"] == "2026-27"
    assert isinstance(body["default_models_by_regime"], dict)
    assert isinstance(body["scheduled_tasks"], list)


def test_settings_patch_merges_and_returns(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.patch(
        "/api/v1/settings",
        json={"max_position_pct": 5, "telegram_alerts_enabled": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_position_pct"] == 5
    assert body["telegram_alerts_enabled"] is True
    # Untouched fields keep their defaults.
    assert body["daily_new_positions_cap"] == 2
    assert _REQUIRED_FIELDS.issubset(body.keys())


def test_settings_patch_ignores_unknown_keys(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.patch(
        "/api/v1/settings",
        json={"not_a_real_setting": 123},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "not_a_real_setting" not in resp.json()
