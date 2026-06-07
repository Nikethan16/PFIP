"""Tests for the self-custody wallet router (/api/v1/self-custody/wallets).

Covered:
  * auth gate (401 without a bearer token) on every verb,
  * add → list → delete round-trip against a stateful in-memory fake session,
  * per-chain address validation (a bad address is rejected 400),
  * duplicate add is rejected 409,
  * balances endpoint joins the latest fundamentals row and converts units.

The fake session keeps two lists (wallets + fundamentals) and routes each
SQLAlchemy statement by inspecting its target entity, so a single object answers
the handful of reads/writes the router issues without touching a real DB.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pfip.api.deps import get_db
from pfip.api.main import app
from pfip.models.fundamentals import FundamentalRow
from pfip.models.self_custody import SelfCustodyAddressRow

# Valid-format sample addresses per chain.
BTC_ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # genesis coinbase address
ETH_ADDR = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
SOL_ADDR = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"

USER = "user@example.com"  # matches Settings.pfip_user_email default → JWT sub


# ---------------------------------------------------------------------------
# Stateful fake session
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list, *, tuples: list | None = None) -> None:
        self._rows = rows
        self._tuples = tuples

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def first(self):
        if self._tuples is not None:
            return self._tuples[0] if self._tuples else None
        return self._rows[0] if self._rows else None

    def all(self) -> list:
        return list(self._tuples if self._tuples is not None else self._rows)


class _StatefulSession:
    """In-memory stand-in routing by the statement's target entity."""

    def __init__(self, fundamentals: list[FundamentalRow] | None = None) -> None:
        self.wallets: list[SelfCustodyAddressRow] = []
        self.fundamentals: list[FundamentalRow] = list(fundamentals or [])

    async def execute(self, stmt, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        text = str(stmt).lower()
        params = {}
        try:
            params = stmt.compile().params
        except Exception:  # noqa: BLE001
            params = {}
        pvals = [str(v) for v in params.values()]

        if "self_custody_addresses" in text:
            rows = list(self.wallets)
            # WHERE id = ... (delete/dup-by-id lookups)
            id_vals = [v for v in params.values() if isinstance(v, uuid.UUID)]
            if id_vals:
                rows = [r for r in rows if r.id in id_vals]
            # WHERE chain = ... AND address = ... (duplicate guard)
            if any(":" not in p and p in {"btc", "eth", "sol"} for p in pvals):
                chains = {p for p in pvals if p in {"btc", "eth", "sol"}}
                rows = [r for r in rows if r.chain in chains]
            addr_vals = {p for p in pvals if p in (BTC_ADDR, ETH_ADDR, SOL_ADDR)}
            if addr_vals:
                rows = [r for r in rows if r.address in addr_vals]
            # newest-first to match the router's order_by
            rows = sorted(rows, key=lambda r: r.added_at, reverse=True)
            return _Result(rows)

        if "fundamentals" in text:
            addr = next((p for p in pvals if p in (BTC_ADDR, ETH_ADDR, SOL_ADDR)), None)
            field = next((p for p in pvals if p.endswith(("_sat", "_balance", "lamports"))), None)
            matches = [
                f
                for f in self.fundamentals
                if (addr is None or f.symbol == addr) and (field is None or f.field == field)
            ]
            matches.sort(key=lambda f: f.as_of_date, reverse=True)
            tuples = [(f.value, f.as_of_date) for f in matches]
            return _Result(matches, tuples=tuples)

        return _Result([])

    def add(self, obj) -> None:  # noqa: ANN001
        if isinstance(obj, SelfCustodyAddressRow):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.added_at is None:
                obj.added_at = datetime.now(tz=timezone.utc)
            self.wallets.append(obj)

    async def delete(self, obj) -> None:  # noqa: ANN001
        self.wallets = [w for w in self.wallets if w.id != getattr(obj, "id", None)]

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def refresh(self, obj) -> None:  # noqa: ANN001
        if isinstance(obj, SelfCustodyAddressRow) and obj.added_at is None:
            obj.added_at = datetime.now(tz=timezone.utc)

    async def close(self) -> None:
        return None


@pytest.fixture
def stateful_client():
    session = _StatefulSession()

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_wallets_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/self-custody/wallets").status_code == 401
    assert (
        client.post(
            "/api/v1/self-custody/wallets", json={"chain": "btc", "address": BTC_ADDR}
        ).status_code
        == 401
    )
    assert client.delete(f"/api/v1/self-custody/wallets/{uuid.uuid4()}").status_code == 401
    assert client.get("/api/v1/self-custody/wallets/balances").status_code == 401


# ---------------------------------------------------------------------------
# Round-trip + shape
# ---------------------------------------------------------------------------


def test_add_list_delete_roundtrip(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _session = stateful_client

    # Empty to start.
    r = client.get("/api/v1/self-custody/wallets", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []

    # Add one.
    r = client.post(
        "/api/v1/self-custody/wallets",
        json={"chain": "btc", "address": BTC_ADDR, "label": "cold wallet"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["chain"] == "btc"
    assert body["address"] == BTC_ADDR
    assert body["label"] == "cold wallet"
    assert set(body.keys()) >= {"id", "chain", "address", "label", "added_at"}
    wallet_id = body["id"]

    # List shows it.
    r = client.get("/api/v1/self-custody/wallets", headers=auth_headers)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["id"] == wallet_id

    # Delete it.
    r = client.delete(f"/api/v1/self-custody/wallets/{wallet_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == wallet_id

    # Gone.
    r = client.get("/api/v1/self-custody/wallets", headers=auth_headers)
    assert r.json() == []


def test_eth_and_sol_addresses_accepted(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    for chain, addr in (("eth", ETH_ADDR), ("sol", SOL_ADDR)):
        r = client.post(
            "/api/v1/self-custody/wallets",
            json={"chain": chain, "address": addr},
            headers=auth_headers,
        )
        assert r.status_code == 201, (chain, r.json())
        assert r.json()["chain"] == chain


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_bad_address_rejected(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    r = client.post(
        "/api/v1/self-custody/wallets",
        json={"chain": "btc", "address": "not-a-real-btc-address"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_address"


def test_eth_address_on_btc_chain_rejected(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    r = client.post(
        "/api/v1/self-custody/wallets",
        json={"chain": "btc", "address": ETH_ADDR},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_unsupported_chain_rejected(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    r = client.post(
        "/api/v1/self-custody/wallets",
        json={"chain": "doge", "address": BTC_ADDR},
        headers=auth_headers,
    )
    # Pydantic field_validator → 422 unprocessable entity.
    assert r.status_code == 422


def test_duplicate_rejected(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    payload = {"chain": "eth", "address": ETH_ADDR}
    assert (
        client.post("/api/v1/self-custody/wallets", json=payload, headers=auth_headers).status_code
        == 201
    )
    dup = client.post("/api/v1/self-custody/wallets", json=payload, headers=auth_headers)
    assert dup.status_code == 409


def test_delete_unknown_404(stateful_client, auth_headers: dict[str, str]) -> None:
    client, _ = stateful_client
    r = client.delete(f"/api/v1/self-custody/wallets/{uuid.uuid4()}", headers=auth_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def test_balances_join_latest_fundamentals(auth_headers: dict[str, str]) -> None:
    """A synced BTC wallet reports its sat balance + the whole-coin conversion."""
    # Seed a fundamentals snapshot for the BTC address.
    f = FundamentalRow()
    f.as_of_date = date(2026, 6, 6)
    f.report_date = date(2026, 6, 6)
    f.symbol = BTC_ADDR
    f.field = "btc_balance_sat"
    f.value = 150_000_000  # 1.5 BTC
    f.source = "mempool"

    session = _StatefulSession(fundamentals=[f])
    # Pre-load a wallet for the user.
    w = SelfCustodyAddressRow(user_id=USER, chain="btc", address=BTC_ADDR, label="cold")
    w.id = uuid.uuid4()
    w.added_at = datetime.now(tz=timezone.utc)
    session.wallets.append(w)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        client = TestClient(app)
        r = client.get("/api/v1/self-custody/wallets/balances", headers=auth_headers)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["chain"] == "btc"
        assert row["synced"] is True
        assert row["balance_raw"] == 150_000_000
        assert row["balance"] == pytest.approx(1.5)
        assert row["unit"] == "sat"
        assert row["as_of"] == "2026-06-06"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_balances_unsynced_wallet_reports_nulls(auth_headers: dict[str, str]) -> None:
    """A wallet with no fundamentals snapshot comes back synced=False."""
    session = _StatefulSession(fundamentals=[])
    w = SelfCustodyAddressRow(user_id=USER, chain="sol", address=SOL_ADDR)
    w.id = uuid.uuid4()
    w.added_at = datetime.now(tz=timezone.utc)
    session.wallets.append(w)

    async def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    try:
        client = TestClient(app)
        r = client.get("/api/v1/self-custody/wallets/balances", headers=auth_headers)
        assert r.status_code == 200
        row = r.json()[0]
        assert row["synced"] is False
        assert row["balance"] is None
        assert row["balance_raw"] is None
        assert row["unit"] == "lamports"
    finally:
        app.dependency_overrides.pop(get_db, None)
