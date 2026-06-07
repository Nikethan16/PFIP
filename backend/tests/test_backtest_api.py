"""Tests for the backtest router (/api/v1/backtest).

Mirrors the shadow-router test style: API-smoke tests against the autouse
fake session (empty DB), plus a populated-shape test that swaps in a fake
session returning a synthetic ``BacktestRunRow`` so we exercise the JSON
serialization (headline-metric hoisting + full-blob passthrough) without a
real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.models.backtest import BacktestRunRow


# ---------------------------------------------------------------------------
# Auth + empty-list smoke tests (use the autouse empty fake session).
# ---------------------------------------------------------------------------


def test_list_runs_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/backtest/runs")
    assert resp.status_code == 401


def test_get_run_requires_auth(client: TestClient) -> None:
    resp = client.get(f"/api/v1/backtest/runs/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_list_runs_empty_with_auth(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Graceful empty list when no runs exist."""
    resp = client.get("/api/v1/backtest/runs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"runs": [], "count": 0}


def test_get_run_404_when_missing(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Unknown id → 404 (fake session's .get returns None)."""
    resp = client.get(f"/api/v1/backtest/runs/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_list_runs_rejects_bad_limit(client: TestClient, auth_headers: dict[str, str]) -> None:
    """limit is bounded (1..200)."""
    resp = client.get("/api/v1/backtest/runs?limit=0", headers=auth_headers)
    assert resp.status_code == 422
    resp = client.get("/api/v1/backtest/runs?limit=9999", headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Populated-shape tests with a fake session that returns one synthetic run.
# ---------------------------------------------------------------------------


def _sample_row() -> BacktestRunRow:
    row = BacktestRunRow()
    row.id = uuid.uuid4()
    row.market = "BTC-USD"
    row.strategy = "ma_50_200"
    row.model_name = None
    row.model_version = None
    row.start_date = date(2023, 5, 5)
    row.end_date = date(2026, 6, 7)
    row.lookahead_ok = True
    row.created_at = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    row.metrics = {
        "walkforward": {
            "sharpe": 1.23,
            "sortino": 1.55,
            "max_drawdown": -0.18,
            "calmar": 0.9,
            "hit_rate": 0.52,
            "cagr": 0.21,
            "total_return": 0.65,
            "n_trades": 14,
            "n_folds": 17,
            "cpcv_mean_sharpe": 0.8,
            "mc_sharpe_5th": 0.4,
            "fold_metrics": [
                {
                    "fold": 0,
                    "start_idx": 0,
                    "end_idx": 282,
                    "sharpe": 1.1,
                    "max_drawdown": -0.1,
                    "hit_rate": 0.5,
                    "avg_return": 0.001,
                    "n_trades": 2,
                }
            ],
        },
        "benchmarks": {"buy_hold": {"sharpe": 0.7}},
        "monte_carlo": {"sharpe_5th": 0.4},
        "shuffle_test": {"leakage": False},
    }
    row.params = {"train_window": 252, "step": 21, "embargo": 5, "horizon": 3}
    return row


class _OneRowScalars:
    def __init__(self, rows: list[BacktestRunRow]) -> None:
        self._rows = rows

    def all(self) -> list[BacktestRunRow]:
        return list(self._rows)

    def first(self) -> BacktestRunRow | None:
        return self._rows[0] if self._rows else None


class _OneRowResult:
    def __init__(self, rows: list[BacktestRunRow]) -> None:
        self._rows = rows

    def scalars(self) -> _OneRowScalars:
        return _OneRowScalars(self._rows)


class _OneRowSession:
    """Fake session that always serves the one synthetic backtest run."""

    def __init__(self, row: BacktestRunRow) -> None:
        self._row = row

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _OneRowResult([self._row])

    async def get(self, _cls, pk):  # noqa: ANN001
        return self._row if pk == self._row.id else None

    async def close(self) -> None:
        return None


@pytest.fixture
def populated_client(auth_headers: dict[str, str]):
    row = _sample_row()

    async def _one_row_db():
        yield _OneRowSession(row)

    app.dependency_overrides[get_db] = _one_row_db
    try:
        yield TestClient(app), row
    finally:
        # Restore the autouse empty fake session for subsequent tests.
        app.dependency_overrides.pop(get_db, None)


def test_list_runs_populated_shape(populated_client, auth_headers: dict[str, str]) -> None:
    client, row = populated_client
    resp = client.get("/api/v1/backtest/runs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    run = data["runs"][0]
    assert run["id"] == str(row.id)
    assert run["market"] == "BTC-USD"
    assert run["strategy"] == "ma_50_200"
    assert run["lookahead_ok"] is True
    # Headline metrics hoisted out of the nested walkforward blob.
    assert run["sharpe"] == 1.23
    assert run["max_drawdown"] == -0.18
    assert run["n_folds"] == 17
    assert run["cpcv_mean_sharpe"] == 0.8
    # List view stays flat — no full metrics blob.
    assert "metrics" not in run
    assert run["start_date"] == "2023-05-05"


def test_get_run_detail_shape(populated_client, auth_headers: dict[str, str]) -> None:
    client, row = populated_client
    resp = client.get(f"/api/v1/backtest/runs/{row.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(row.id)
    assert data["sharpe"] == 1.23
    # Detail view carries the full blobs untouched.
    assert "metrics" in data
    assert "params" in data
    fold_metrics = data["metrics"]["walkforward"]["fold_metrics"]
    assert isinstance(fold_metrics, list)
    assert fold_metrics[0]["fold"] == 0
    assert data["params"]["train_window"] == 252
    assert data["metrics"]["shuffle_test"]["leakage"] is False
