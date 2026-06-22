"""Shadow-portfolio tests — API smoke + engine unit tests.

The engine tests use an in-memory fake session so we don't need Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from pfip.core.contracts import Driver, Regime, Signal, SignalDirection
from pfip.models.shadow import ShadowHoldingRow, ShadowPortfolioTxRow
from pfip.shadow.engine import RiskRules, ShadowPortfolio

# ---------------------------------------------------------------------------
# API smoke tests
# ---------------------------------------------------------------------------


def test_shadow_holdings_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/shadow/holdings")
    assert resp.status_code == 401


def test_shadow_holdings_empty_with_auth(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/shadow/holdings", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_shadow_vs_actual_returns_dict(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/shadow/vs-actual", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "n_shadow_positions" in data
    assert "n_actual_positions" in data
    assert "diff_inr" in data


# ---------------------------------------------------------------------------
# Engine unit tests with in-memory fake session.
# ---------------------------------------------------------------------------


@dataclass
class _InMemSession:
    """Stand-in for an async SQLAlchemy session covering the ops the engine uses."""

    holdings: dict[UUID, ShadowHoldingRow] = field(default_factory=dict)
    txs: list[ShadowPortfolioTxRow] = field(default_factory=list)
    pending: list[Any] = field(default_factory=list)
    ohlcv: dict[str, list[tuple[datetime, Decimal]]] = field(default_factory=dict)
    actual_holdings: list[Any] = field(default_factory=list)

    def add(self, obj: Any) -> None:
        self.pending.append(obj)

    async def flush(self) -> None:
        self._materialize()

    async def commit(self) -> None:
        self._materialize()

    async def get(self, cls: Any, pk: Any) -> Any:
        if cls is ShadowHoldingRow:
            return self.holdings.get(pk)
        return None

    async def execute(self, stmt: Any) -> Any:
        # We cheat: we don't actually parse the stmt. Callers will only invoke
        # execute on the select() helpers the engine builds; we serve them all
        # by introspecting the table/columns.
        desc = str(stmt).lower()
        if "shadow_portfolio_tx" in desc and "kind" in desc:
            # count today buys — engine filters by kind + time
            matches = [t for t in self.txs if t.kind == "BUY"]
            return _Res(matches)
        if "shadow_holdings" in desc:
            rows = [h for h in self.holdings.values() if h.closed_at is None]
            return _Res(rows)
        if "ohlcv" in desc and "close" in desc:
            # Sort-by-desc latest close
            flat: list[tuple[datetime, Decimal]] = []
            for _sym, seq in self.ohlcv.items():
                flat.extend(seq)
            flat.sort(key=lambda kv: kv[0], reverse=True)
            return _Res([kv[1] for kv in flat])
        if "holdings" in desc and "closed_at" in desc:
            return _Res(list(self.actual_holdings))
        return _Res([])

    def _materialize(self) -> None:
        for obj in list(self.pending):
            if isinstance(obj, ShadowHoldingRow):
                if obj.id is None:
                    obj.id = uuid4()
                self.holdings[obj.id] = obj
            elif isinstance(obj, ShadowPortfolioTxRow):
                if obj.id is None:
                    obj.id = uuid4()
                self.txs.append(obj)
            else:
                pass
        self.pending.clear()


@dataclass
class _Res:
    items: list[Any]

    def scalars(self) -> Any:
        parent = self

        class _S:
            def all(self_inner) -> list[Any]:  # noqa: ANN001
                return list(parent.items)

            def first(self_inner) -> Any:  # noqa: ANN001
                return parent.items[0] if parent.items else None

        return _S()

    def all(self) -> list[Any]:
        return list(self.items)


def _signal(asset: str, direction: SignalDirection, confidence: int = 80) -> Signal:
    return Signal(
        direction=direction,
        confidence=confidence,
        horizon_hours=72,
        drivers=[Driver(feature="rsi_14", contribution=0.3)],
        counter_arguments=[],
        regime=Regime.BULL_TREND,
        model_name="lgbm_test",
        model_version="0.0.1",
        asset=asset,
        generated_at=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_apply_signal_rejects_low_confidence() -> None:
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session, rules=RiskRules(confidence_floor=65))
    sig = _signal("BTC/USD", SignalDirection.BUY, confidence=40)
    decision = await portfolio.apply_signal(sig, Decimal("1000"))
    assert decision.accepted is False
    assert "confidence" in decision.reason


@pytest.mark.asyncio
async def test_apply_signal_opens_buy() -> None:
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session)
    sig = _signal("BTC/USD", SignalDirection.BUY, confidence=80)
    decision = await portfolio.apply_signal(sig, Decimal("1000"))
    assert decision.accepted is True
    assert len(session.holdings) == 1
    assert session.txs[0].kind == "BUY"


@pytest.mark.asyncio
async def test_apply_signal_respects_daily_cap() -> None:
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session, rules=RiskRules(daily_new_position_cap=1))
    sig1 = _signal("BTC/USD", SignalDirection.BUY, confidence=80)
    sig2 = _signal("ETH/USD", SignalDirection.BUY, confidence=80)
    d1 = await portfolio.apply_signal(sig1, Decimal("1000"))
    d2 = await portfolio.apply_signal(sig2, Decimal("1000"))
    assert d1.accepted is True
    assert d2.accepted is False
    assert "daily cap" in d2.reason


@pytest.mark.asyncio
async def test_mark_to_market_returns_shape() -> None:
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session)
    sig = _signal("BTC/USD", SignalDirection.BUY, confidence=80)
    await portfolio.apply_signal(sig, Decimal("1000"))
    # Seed latest close for BTC/USD
    session.ohlcv["BTC/USD"] = [(datetime.now(tz=timezone.utc), Decimal("1100"))]
    mtm = await portfolio.mark_to_market()
    assert "equity_inr" in mtm
    assert mtm["equity_inr"] >= 0


@pytest.mark.asyncio
async def test_vs_actual_diff_shape() -> None:
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session)
    diff = await portfolio.vs_actual()
    for key in ("actual_value_inr", "shadow_value_inr", "diff_inr", "only_in_shadow"):
        assert key in diff


@pytest.mark.asyncio
async def test_vs_actual_includes_performance_comparison() -> None:
    """vs_actual now carries marked value + return/Sharpe comparison metrics."""
    session = _InMemSession()
    portfolio = ShadowPortfolio(session=session)
    diff = await portfolio.vs_actual()
    for key in (
        "actual_marked_inr",
        "shadow_marked_inr",
        "actual_return_pct",
        "shadow_return_pct",
        "return_pct_diff",
        "actual_sharpe",
        "shadow_sharpe",
        "sharpe_diff",
    ):
        assert key in diff
    # Empty books ⇒ all-zero performance, no fabricated moves.
    assert diff["shadow_return_pct"] == 0.0
    assert diff["sharpe_diff"] == 0.0


def test_weighted_sharpe_empty_is_zero() -> None:
    assert ShadowPortfolio._weighted_sharpe([]) == 0.0
