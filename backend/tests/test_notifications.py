"""Tests for /api/v1/notifications/recent — the backend bell mirror.

Covers the 401 (no auth), the 200 + shape (empty DB via the conftest fake
session), and a populated case driven by a custom session override that
returns recent signals / regime transitions / model events.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.models.calibration_reports import ModelEventRow, RegimeTransitionRow
from pfip.models.signals import SignalRow


def test_notifications_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/notifications/recent").status_code == 401


def test_notifications_empty_shape_with_auth(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Empty DB → correct non-fake shape: unread 0, no items."""
    resp = client.get("/api/v1/notifications/recent", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"unread", "window_hours", "items"}
    assert body["unread"] == 0
    assert body["items"] == []
    assert body["window_hours"] == 24


def test_notifications_surfaces_recent_events(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Recent signals / regime flips / model events surface as items."""
    now = datetime.now(tz=timezone.utc)

    sig = SignalRow(
        id=uuid.uuid4(),
        asset="AAPL",
        direction="BUY",
        confidence=72,
        horizon_hours=24,
        regime="bull",
        model_name="lgbm",
        model_version="v3",
        drivers=[],
        counter_arguments=[],
        generated_at=now - timedelta(hours=1),
    )
    regime = RegimeTransitionRow(
        id=uuid.uuid4(),
        symbol="BTC-USD",
        from_regime="bull",
        to_regime="bear",
        at=now - timedelta(hours=2),
        confidence=0.8,
    )
    event = ModelEventRow(
        id=uuid.uuid4(),
        model_name="lgbm",
        model_version="v3",
        event_type="suspended",
        at=now - timedelta(hours=3),
        reason="calibration breach",
        payload={},
    )

    class _PopulatedResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            rows = self._rows

            class _S:
                def all(self_inner):
                    return rows

            return _S()

    class _PopulatedSession:
        async def execute(self, stmt, *args, **kwargs):  # noqa: ANN001
            # Route by the model referenced in the SELECT.
            text = str(stmt)
            if "signals" in text:
                return _PopulatedResult([sig])
            if "regime_transitions" in text:
                return _PopulatedResult([regime])
            if "model_events" in text:
                return _PopulatedResult([event])
            return _PopulatedResult([])

        async def close(self) -> None:
            return None

    async def _populated_db() -> AsyncIterator[_PopulatedSession]:
        yield _PopulatedSession()

    app.dependency_overrides[get_db] = _populated_db
    try:
        resp = client.get("/api/v1/notifications/recent", headers=auth_headers)
    finally:
        # The autouse fixture restores the default fake DB after the test.
        app.dependency_overrides[get_db] = _populated_db
    assert resp.status_code == 200
    body = resp.json()
    assert body["unread"] == 3
    kinds = {it["kind"] for it in body["items"]}
    assert kinds == {"signal", "regime_transition", "model_event"}
    # Newest-first ordering.
    ats = [it["at"] for it in body["items"]]
    assert ats == sorted(ats, reverse=True)
    # The suspended model event is CRITICAL; the high-confidence BUY is WARN.
    sev_by_kind = {it["kind"]: it["severity"] for it in body["items"]}
    assert sev_by_kind["model_event"] == "CRITICAL"
    assert sev_by_kind["signal"] == "WARN"
    assert sev_by_kind["regime_transition"] == "WARN"
