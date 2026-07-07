"""Corporate calendar — pure grouping + router smoke."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from pfip.research.calendar import CalendarEvent, group_by_date


def _ev(day: int, hour: int, symbol: str) -> CalendarEvent:
    return CalendarEvent(
        symbol=symbol,
        title=f"{symbol} event",
        category="corp_announcement",
        at=datetime(2026, 7, day, hour, tzinfo=timezone.utc),
    )


def test_group_by_date_buckets_newest_first() -> None:
    days = group_by_date([_ev(1, 9, "A"), _ev(3, 9, "B"), _ev(3, 14, "C")])
    assert [d.date.day for d in days] == [3, 1]  # newest day first
    # within a day, newest event first
    assert [e.symbol for e in days[0].events] == ["C", "B"]


def test_group_by_date_empty() -> None:
    assert group_by_date([]) == []


def test_calendar_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/calendar").status_code == 401


def test_calendar_returns_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/calendar", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == []  # fake DB → no rows
    assert body["n_events"] == 0
    assert "disclaimer" in body
