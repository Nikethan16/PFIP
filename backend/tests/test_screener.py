"""Screener — pure filter engine + router smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pfip.research.screener import Criterion, apply_screen, validate_criteria


def _universe():
    return {
        "TCS.NS": {"roce": 40.0, "pe_ratio": 30.0, "debt_to_equity": 0.1},
        "INFY.NS": {"roce": 32.0, "pe_ratio": 24.0, "debt_to_equity": 0.05},
        "WIPRO.NS": {"roce": 18.0, "pe_ratio": 20.0, "debt_to_equity": 0.2},
        "NOFUND.NS": {"pe_ratio": 15.0},  # missing roce → excluded when roce filtered
    }


def test_apply_screen_and_filters() -> None:
    criteria = [
        Criterion(field="roce", op="gt", value=20),
        Criterion(field="pe_ratio", op="lt", value=25),
    ]
    res = apply_screen(_universe(), criteria)
    syms = [m.symbol for m in res.matches]
    assert syms == ["INFY.NS"]  # only one passes both
    assert res.n_universe == 4
    # NOFUND lacks roce → not evaluable against the roce criterion
    assert res.n_evaluated == 3


def test_apply_screen_sorts_by_first_criterion_direction() -> None:
    # roce is "higher is better" → descending
    res = apply_screen(_universe(), [Criterion(field="roce", op="gte", value=0)])
    assert [m.symbol for m in res.matches] == ["TCS.NS", "INFY.NS", "WIPRO.NS"]


def test_validate_rejects_unknown_field() -> None:
    errs = validate_criteria([Criterion(field="made_up", op="gt", value=1)])
    assert errs and "made_up" in errs[0]


def test_fields_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/screener/fields").status_code == 401


def test_fields_lists_metrics(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/screener/fields", headers=auth_headers)
    assert resp.status_code == 200
    keys = {f["key"] for f in resp.json()["fields"]}
    assert {"roce", "pe_ratio", "debt_to_equity"} <= keys


def test_run_rejects_unknown_field(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/screener/run",
        headers=auth_headers,
        json={"criteria": [{"field": "nope", "op": "gt", "value": 1}]},
    )
    assert resp.status_code == 422


def test_run_returns_result_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Fake DB yields no rows → empty universe, but the shape must be valid.
    resp = client.post(
        "/api/v1/screener/run",
        headers=auth_headers,
        json={"criteria": [{"field": "roce", "op": "gt", "value": 20}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matches"] == []
    assert "n_universe" in body and "disclaimer" in body
