"""Learn module — notable-move detection + router smoke."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from pfip.research.learn import (
    PricePoint,
    default_strategies,
    detect_notable_moves,
    is_crypto_symbol,
)


def _series() -> list[PricePoint]:
    # Day 2: +10% (100→110), day 3: -9.09% (110→100), day 4: +1% (100→101)
    return [
        PricePoint(date=date(2026, 1, 1), close=100.0),
        PricePoint(date=date(2026, 1, 2), close=110.0),
        PricePoint(date=date(2026, 1, 3), close=100.0),
        PricePoint(date=date(2026, 1, 4), close=101.0),
    ]


def test_detect_notable_moves_picks_big_swings_only() -> None:
    moves = detect_notable_moves(_series(), min_abs_pct=3.0)
    dates = [m.date for m in moves]
    # +1% day is below threshold → excluded; two big moves remain, date-ordered.
    assert dates == [date(2026, 1, 2), date(2026, 1, 3)]
    assert moves[0].direction == "up"
    assert moves[1].direction == "down"


def test_detect_respects_top_n() -> None:
    moves = detect_notable_moves(_series(), top_n=1, min_abs_pct=3.0)
    assert len(moves) == 1  # keeps the single biggest by magnitude


def test_is_crypto_symbol() -> None:
    assert is_crypto_symbol("BTC-USD") is True
    assert is_crypto_symbol("AAPL") is False


def test_strategies_include_crypto_note_only_for_crypto() -> None:
    assert any("Volatility" in s.name for s in default_strategies(is_crypto=True))
    assert not any("Volatility" in s.name for s in default_strategies(is_crypto=False))


def test_learn_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/learn/BTC-USD").status_code == 401


def test_learn_returns_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Fake DB → empty series/news, but the envelope must be valid.
    resp = client.get("/api/v1/learn/BTC-USD", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTC-USD"
    assert body["is_crypto"] is True
    assert isinstance(body["strategies"], list) and body["strategies"]
    assert "primer_markdown" in body
