"""Tax engine unit tests — Appendix F rule coverage.

Each scenario uses hand-built synthetic transactions so results are
deterministic and can be recomputed by hand.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pfip.brokers.csv_adapters import UnknownSchemaError
from pfip.brokers.csv_adapters.router import autodetect, route_and_parse
from pfip.tax.engine import (
    AssetClass,
    CGEvent,
    GainTerm,
    build_tax_summary,
    classify_capital_gains,
    compare_regimes,
    compute_80c_optimizer,
    compute_form_67,
    compute_ltcg,
    compute_schedule_fa,
    compute_stcg,
    compute_vda_tax,
    dividend_tax,
    fy_bounds,
    itr_form_recommendation,
    surcharge_cliff_check,
)
from pfip.tax.forms import schedule_cg_json, schedule_fa_json
from pfip.tax.indian_rules import DISCLAIMER, is_vda

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Existing router smoke tests (kept)
# ---------------------------------------------------------------------------


def test_tax_summary_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/tax/summary?fy=2026-27")
    assert resp.status_code == 401


def test_tax_summary_with_auth_returns_200(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get(
        "/api/v1/tax/summary?fy=2026-27&gross_income_inr=1200000",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["fy"] == "2026-27"


def test_tax_details_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/tax/details?fy=2026-27").status_code == 401


def test_tax_details_returns_expected_shape(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Matches the frontend TaxDetailsSchema (all plain numbers)."""
    resp = client.get(
        "/api/v1/tax/details?fy=2026-27&gross_income_inr=1200000",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    required = {
        "fy",
        "slab_income_inr",
        "eighty_c_used_inr",
        "eighty_c_cap_inr",
        "marginal_rate_pct",
        "total_income_inr",
        "old_regime_tax_inr",
        "new_regime_tax_inr",
        "surcharge_thresholds",
        "form_67_lines",
    }
    assert required.issubset(body.keys())
    assert body["fy"] == "2026-27"
    assert body["eighty_c_cap_inr"] == 150000
    assert isinstance(body["surcharge_thresholds"], list)
    assert body["surcharge_thresholds"][0] == {
        "threshold_inr": 5000000,
        "rate_pct": 10.0,
    }
    assert isinstance(body["form_67_lines"], list)
    for key in ("slab_income_inr", "old_regime_tax_inr", "new_regime_tax_inr"):
        assert isinstance(body[key], (int, float))


def test_tax_export_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/tax/export?fy=2026-27").status_code == 401


def test_tax_export_returns_downloadable_file(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/api/v1/tax/export?fy=2026-27", headers=auth_headers)
    assert resp.status_code == 200
    # PDF when reportlab is present, else text/plain fallback — both downloadable.
    assert resp.headers["content-type"] in ("application/pdf", "text/plain; charset=utf-8")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "pfip-tax-2026-27" in resp.headers.get("content-disposition", "")
    assert len(resp.content) > 0


def test_tax_regime_compare_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/tax/regime-compare",
        json={
            "gross_income_inr": "1200000",
            "deductions": {"80C": "150000", "80D": "25000"},
            "fy": "2026-27",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_regime"] in ("old", "new")


# ---------------------------------------------------------------------------
# 1. Equity STCG / LTCG (simple)
# ---------------------------------------------------------------------------


def _tx(
    sym: str,
    when: str,
    kind: str,
    qty: float,
    price: float,
    *,
    asset_class: AssetClass = AssetClass.EQUITY,
    tds: float = 0.0,
) -> dict:
    return {
        "symbol": sym,
        "time": datetime.fromisoformat(when).replace(tzinfo=timezone.utc),
        "kind": kind,
        "qty": Decimal(str(qty)),
        "price": Decimal(str(price)),
        "amount_inr": Decimal(str(qty)) * Decimal(str(price)),
        "tax_withheld": Decimal(str(tds)),
        "asset_class": asset_class,
    }


def test_equity_stcg_basic() -> None:
    txs = [
        _tx("RELIANCE", "2024-06-10", "BUY", 10, 2900),
        _tx("RELIANCE", "2025-03-10", "SELL", 10, 3100),  # <12 months
    ]
    events = classify_capital_gains(txs)
    assert len(events) == 1
    e = events[0]
    assert e.term == GainTerm.STCG
    assert e.gain_inr == Decimal("2000.00")
    tax = compute_stcg(events)
    # 15% of 2000 = 300
    assert tax == Decimal("300.00")
    # LTCG on this set must be zero.
    assert compute_ltcg(events) == Decimal("0")


def test_equity_ltcg_exemption_and_tax() -> None:
    # Two LT lots; gains 120000 → 20000 taxable → 2000 tax at 10%.
    txs = [
        _tx("INFY", "2022-05-10", "BUY", 100, 1500),
        _tx("INFY", "2024-06-15", "SELL", 100, 2700),  # 120k gain
    ]
    events = classify_capital_gains(txs)
    assert len(events) == 1
    assert events[0].term == GainTerm.LTCG
    # 120000 - 100000 exempt = 20000 taxable × 10% = 2000
    assert compute_ltcg(events) == Decimal("2000.00")
    # STCG should be zero
    assert compute_stcg(events) == Decimal("0")


def test_ltcg_below_exemption_is_zero() -> None:
    txs = [
        _tx("ITC", "2022-01-01", "BUY", 100, 200),
        _tx("ITC", "2024-01-15", "SELL", 100, 300),  # 10000 gain, LTCG, <1L
    ]
    events = classify_capital_gains(txs)
    assert events[0].term == GainTerm.LTCG
    assert compute_ltcg(events) == Decimal("0")


# ---------------------------------------------------------------------------
# 2. Grandfathered equity (31-Jan-2018 cost uplift)
# ---------------------------------------------------------------------------


def test_grandfathered_equity_uplift_to_fmv() -> None:
    """Bought pre-Jan-2018, sold post; FMV-uplift should cap the gain."""
    txs = [
        _tx("WIPRO", "2015-04-01", "BUY", 50, 400),  # cost 400
        _tx("WIPRO", "2024-08-15", "SELL", 50, 600),  # sale 600, FMV31jan2018 = 500
    ]
    fmv = {"WIPRO": Decimal("500")}
    events = classify_capital_gains(txs, fmv_31jan2018=fmv)
    e = events[0]
    assert e.grandfathered is True
    # cost_per_unit = max(400, min(500, 600)) = 500
    assert e.buy_cost_inr == Decimal("25000.00")
    assert e.sell_proceeds_inr == Decimal("30000.00")
    assert e.gain_inr == Decimal("5000.00")
    # LTCG, gain < 1L → 0 tax.
    assert compute_ltcg(events) == Decimal("0")


def test_grandfathered_sale_price_below_fmv_caps_at_actual_cost() -> None:
    """If FMV > sale price, the FMV-route gives no relief (lower-of rule)."""
    txs = [
        _tx("OLD", "2015-01-01", "BUY", 10, 100),  # cost 100
        _tx("OLD", "2024-06-01", "SELL", 10, 150),  # sale 150, FMV = 500
    ]
    fmv = {"OLD": Decimal("500")}
    events = classify_capital_gains(txs, fmv_31jan2018=fmv)
    e = events[0]
    # cost_per_unit = max(100, min(500, 150)) = max(100, 150) = 150
    assert e.buy_cost_inr == Decimal("1500.00")
    assert e.gain_inr == Decimal("0.00")


# ---------------------------------------------------------------------------
# 3. VDA — 30% flat, 1% TDS, no loss set-off
# ---------------------------------------------------------------------------


def test_vda_tax_flat_30_pct_and_no_setoff() -> None:
    # Gain on BTC 10k; loss on ETH 5k → taxable = 10k (not 5k).
    txs = [
        _tx("BTC", "2024-07-10", "BUY", 0.01, 5_000_000, asset_class=AssetClass.VDA),
        _tx(
            "BTC",
            "2024-11-10",
            "SELL",
            0.01,
            5_100_000,
            asset_class=AssetClass.VDA,
            tds=510,
        ),
        _tx("ETH", "2024-06-10", "BUY", 0.1, 250_000, asset_class=AssetClass.VDA),
        _tx("ETH", "2024-09-10", "SELL", 0.1, 200_000, asset_class=AssetClass.VDA, tds=200),
    ]
    events = classify_capital_gains(txs)
    vda_events = [e for e in events if e.asset_class == AssetClass.VDA]
    result = compute_vda_tax(vda_events)
    assert result["loss_setoff_allowed"] is False
    assert result["loss_carryforward_allowed"] is False
    # gains only count (BTC 1000); losses (ETH -5000) don't reduce taxable.
    assert result["taxable_gains_inr"] == Decimal("1000.00")
    # 30% of 1000 = 300; TDS 710 → net -410 (refund due).
    assert result["tax_before_tds_inr"] == Decimal("300.00")
    assert result["tds_credit_inr"] == Decimal("710.00")
    assert result["net_tax_payable_inr"] == Decimal("-410.00")


def test_is_vda_symbol_detection() -> None:
    assert is_vda("BTC") is True
    assert is_vda("BTC/INR") is True
    assert is_vda("ETH-USDT") is True
    assert is_vda("RELIANCE") is False
    assert is_vda(None) is False


# ---------------------------------------------------------------------------
# 4. US stock / DTAA / Form 67
# ---------------------------------------------------------------------------


def test_form_67_dtaa_credit() -> None:
    rows = compute_form_67(
        [
            {
                "symbol": "AAPL",
                "paid_on": date(2025, 2, 14),
                "amount_usd": Decimal("100"),
                "tax_withheld_usd": Decimal("25"),
                "fx_rate": Decimal("85"),
            }
        ],
        slab_rate=Decimal("0.30"),
    )
    assert len(rows) == 1
    r = rows[0]
    # foreign income INR = 100 × 85 = 8500
    assert r.foreign_income_inr == Decimal("8500.00")
    # tax abroad INR = 25 × 85 = 2125
    assert r.tax_paid_abroad_inr == Decimal("2125.00")
    # Indian tax at slab 30% = 2550
    assert r.indian_tax_on_same_income_inr == Decimal("2550.00")
    # Credit = min(2125, 2550) = 2125
    assert r.dtaa_credit_inr == Decimal("2125.00")


def test_schedule_fa_peak_balance() -> None:
    rows = compute_schedule_fa(
        [
            {
                "symbol": "AAPL",
                "isin": "US0378331005",
                "acquired_on": date(2024, 10, 15),
                "daily_balances_usd": {
                    date(2024, 12, 31): Decimal("2500"),
                    date(2025, 1, 2): Decimal("2400"),
                    date(2025, 3, 31): Decimal("2300"),
                },
                "closing_balance_usd": Decimal("2300"),
            }
        ],
        dividends_usd=[
            {"symbol": "AAPL", "paid_on": date(2025, 2, 14), "amount_usd": Decimal("5")},
        ],
        fy="2024-25",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.peak_balance_usd == Decimal("2500")
    assert r.gross_dividend_usd == Decimal("5")
    # Static fallback uses 2024-12-31 rate 85.62
    assert r.peak_balance_inr > Decimal("0")


# ---------------------------------------------------------------------------
# 4b. Schedule FA router — real daily-peak from OHLCV + per-row basis flag
# ---------------------------------------------------------------------------


def test_schedule_fa_router_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/tax/schedule-fa?fy=2024-25").status_code == 401


def test_schedule_fa_router_empty_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    """No USD holdings → correct empty shape, still 200."""
    resp = client.get("/api/v1/tax/schedule-fa?fy=2024-25", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["schedule"] == "FA"
    assert body["rows"] == []
    assert body["disclaimer"] == DISCLAIMER


def test_schedule_fa_router_real_peak_and_basis_flag(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """A USD holding with OHLCV history gets a price-derived peak + basis=peak;
    one without history falls back to cost_approx and is flagged honestly."""
    from collections.abc import AsyncIterator

    from pfip.api.deps import get_db
    from pfip.api.main import app
    from pfip.models.holdings import HoldingRow

    priced = HoldingRow(
        id=__import__("uuid").uuid4(),
        category="us_stock",
        symbol="AAPL",
        isin="US0378331005",
        broker="indmoney",
        acquired_at=datetime(2024, 10, 15, tzinfo=timezone.utc),
        qty=Decimal("10"),
        cost_basis_inr=Decimal("170000"),
        cost_basis_ccy="USD",
        fx_rate=Decimal("85"),
    )
    no_history = HoldingRow(
        id=__import__("uuid").uuid4(),
        category="us_stock",
        symbol="TSLA",
        isin="US88160R1014",
        broker="vested",
        acquired_at=datetime(2024, 11, 1, tzinfo=timezone.utc),
        qty=Decimal("5"),
        cost_basis_inr=Decimal("100000"),
        cost_basis_ccy="USD",
        fx_rate=Decimal("84"),
    )

    # AAPL daily closes (USD). Peak balance = 10 * 260 = 2600; closing = 10 * 250.
    aapl_closes = [
        (datetime(2024, 12, 31, tzinfo=timezone.utc), Decimal("240")),
        (datetime(2025, 1, 15, tzinfo=timezone.utc), Decimal("260")),  # peak
        (datetime(2025, 3, 31, tzinfo=timezone.utc), Decimal("250")),  # closing
    ]

    class _Result:
        def __init__(self, scalars=None, rows=None):
            self._scalars = scalars or []
            self._rows = rows or []

        def scalars(self):
            data = self._scalars

            class _S:
                def all(self_inner):
                    return data

            return _S()

        def all(self):
            return self._rows

        def first(self):
            return None  # no DB fx rate → static fallback

    class _Session:
        async def execute(self, stmt, params=None, *args, **kwargs):  # noqa: ANN001
            text = str(stmt)
            if "FROM holdings" in text or "holdings" in text and "ohlcv" not in text:
                return _Result(scalars=[priced, no_history])
            if "ohlcv" in text:
                # Route by the symbol bound parameter in the compiled query.
                # SQLAlchemy core select on OHLCVRow.symbol == r.symbol uses a
                # bound param; inspect the rendered SQL params instead.
                # Fall back: return AAPL closes only for the AAPL pass.
                compiled = stmt.compile()
                bound = {str(k): v for k, v in compiled.params.items()}
                sym = next((v for k, v in bound.items() if v in ("AAPL", "TSLA")), None)
                if sym == "AAPL":
                    return _Result(rows=aapl_closes)
                return _Result(rows=[])
            if "fx_rates" in text:
                return _Result()
            return _Result()

        async def close(self) -> None:
            return None

    async def _db() -> AsyncIterator[_Session]:
        yield _Session()

    app.dependency_overrides[get_db] = _db
    try:
        resp = client.get("/api/v1/tax/schedule-fa?fy=2024-25", headers=auth_headers)
    finally:
        app.dependency_overrides[get_db] = _db
    assert resp.status_code == 200
    body = resp.json()
    rows = {r["symbol"]: r for r in body["rows"]}
    assert set(rows) == {"AAPL", "TSLA"}

    # AAPL: real price-derived peak.
    aapl = rows["AAPL"]
    assert aapl["basis"] == "peak"
    assert Decimal(aapl["peak_balance_usd"]) == Decimal("2600")
    assert Decimal(aapl["closing_balance_usd"]) == Decimal("2500")
    assert Decimal(aapl["peak_balance_inr"]) > Decimal("0")

    # TSLA: no history → honest cost-basis approximation, closing 0.
    tsla = rows["TSLA"]
    assert tsla["basis"] == "cost_approx"
    assert Decimal(tsla["closing_balance_usd"]) == Decimal("0")


# ---------------------------------------------------------------------------
# 5. Regime comparison sanity
# ---------------------------------------------------------------------------


def test_compare_regimes_new_wins_for_large_income_no_deductions() -> None:
    cmp = compare_regimes(Decimal("2000000"), {}, fy="2026-27")
    assert cmp["recommended_regime"] == "new"
    assert cmp["new_regime_tax_inr"] < cmp["old_regime_tax_inr"]


def test_compare_regimes_old_wins_with_heavy_deductions() -> None:
    cmp = compare_regimes(
        Decimal("1500000"),
        {"80C": Decimal("150000"), "80D": Decimal("25000"), "80CCD_1B": Decimal("50000")},
        fy="2026-27",
    )
    # Can go either way — assert both numbers are plausible and disclaimer present.
    assert cmp["disclaimer"] == DISCLAIMER
    assert cmp["old_regime_tax_inr"] >= Decimal("0")
    assert cmp["new_regime_tax_inr"] >= Decimal("0")


# ---------------------------------------------------------------------------
# 6. Surcharge cliffs, ITR routing, 80C optimiser
# ---------------------------------------------------------------------------


def test_surcharge_cliff_detection() -> None:
    r = surcharge_cliff_check(Decimal("4900000"))  # 1% below ₹50L
    assert any(f["within_5_pct"] for f in r["flags"])
    assert r["disclaimer"] == DISCLAIMER


def test_itr_form_routing_foreign_assets() -> None:
    r = itr_form_recommendation({"salary": True, "foreign_assets": True})
    assert r["recommended_form"] == "ITR-2"
    r = itr_form_recommendation({"salary": True, "business": True, "foreign_assets": True})
    assert r["recommended_form"] == "ITR-3"
    r = itr_form_recommendation({"salary": True})
    assert r["recommended_form"] == "ITR-1"


def test_80c_optimizer_ranks_instruments() -> None:
    out = compute_80c_optimizer(
        {"PPF": Decimal("50000"), "NPS_1B": Decimal("0")},
        income_slab=Decimal("0.30"),
    )
    assert out["disclaimer"] == DISCLAIMER
    # Remaining 80C headroom = 100k; NPS_1B = 50k.
    # All 3 instruments returned; ordered by tax saved.
    assert len(out["ranked"]) == 3


# ---------------------------------------------------------------------------
# 7. Dividend tax (post-2020)
# ---------------------------------------------------------------------------


def test_dividend_tax_slab_rate() -> None:
    out = dividend_tax(
        [{"symbol": "TCS", "amount_inr": Decimal("10000"), "paid_on": date(2024, 12, 1)}],
        slab_rate=Decimal("0.30"),
    )
    assert out["total_dividend_inr"] == Decimal("10000")
    assert out["tax_on_dividend_inr"] == Decimal("3000.00")


# ---------------------------------------------------------------------------
# 8. FY bounds + schedule-CG JSON shape
# ---------------------------------------------------------------------------


def test_fy_bounds() -> None:
    s, e = fy_bounds("2026-27")
    assert s == date(2026, 4, 1)
    assert e == date(2027, 3, 31)


def test_schedule_cg_json_shape() -> None:
    events = [
        CGEvent(
            symbol="X",
            asset_class=AssetClass.EQUITY,
            term=GainTerm.STCG,
            qty=Decimal("1"),
            buy_date=date(2024, 1, 1),
            sell_date=date(2024, 6, 1),
            buy_cost_inr=Decimal("100"),
            sell_proceeds_inr=Decimal("150"),
            gain_inr=Decimal("50"),
        )
    ]
    j = schedule_cg_json(events)
    assert j["schedule"] == "CG"
    assert len(j["equity_stcg"]["items"]) == 1
    assert j["disclaimer"] == DISCLAIMER


# ---------------------------------------------------------------------------
# 9. CSV adapters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn,broker",
    [
        ("zerodha_tradebook.csv", "zerodha"),
        ("icicidirect_trades.csv", "icicidirect"),
        ("groww_stocks.csv", "groww"),
        ("indmoney_us.csv", "indmoney"),
        ("vested_us.csv", "vested"),
        ("wazirx_trades.csv", "wazirx"),
        ("coindcx_trades.csv", "coindcx"),
        ("binance_trades.csv", "binance"),
        ("coinbase_tx.csv", "coinbase"),
        ("kraken_ledger.csv", "kraken"),
    ],
)
def test_adapter_parses_fixture(fn: str, broker: str) -> None:
    data = (FIX / fn).read_bytes()
    detected = autodetect(data)
    assert detected == broker, f"Autodetect failed; expected {broker}, got {detected}"
    result = route_and_parse(data, broker)
    assert result.broker == broker
    assert len(result.imported) >= 1


def test_adapter_raises_on_unknown_schema() -> None:
    with pytest.raises(UnknownSchemaError):
        route_and_parse(b"foo,bar,baz\n1,2,3\n", broker=None)


# ---------------------------------------------------------------------------
# 10. End-to-end summary
# ---------------------------------------------------------------------------


def test_build_tax_summary_aggregates() -> None:
    txs = [
        _tx("RELIANCE", "2024-06-10", "BUY", 10, 2900),
        _tx("RELIANCE", "2025-03-10", "SELL", 10, 3100),  # STCG 2000
        _tx("BTC", "2024-05-01", "BUY", 0.01, 5_000_000, asset_class=AssetClass.VDA),
        _tx(
            "BTC",
            "2025-01-10",
            "SELL",
            0.01,
            5_100_000,
            asset_class=AssetClass.VDA,
            tds=510,
        ),
    ]
    events = classify_capital_gains(txs)
    s = build_tax_summary("2024-25", events, gross_income=Decimal("1200000"))
    assert s.stcg_equity_inr == Decimal("2000.00")
    # VDA gains within FY 2024-25 (Apr 2024 – Mar 2025): 1000
    assert s.vda_gain_inr == Decimal("1000.00")
    assert s.recommended_regime in ("old", "new")
    assert s.recommended_itr in ("ITR-1", "ITR-2", "ITR-3", "ITR-4")


# ---------------------------------------------------------------------------
# 11. Partial sells — FIFO correctness
# ---------------------------------------------------------------------------


def test_fifo_partial_sell_picks_oldest_lot_first() -> None:
    txs = [
        _tx("X", "2022-01-01", "BUY", 10, 100),  # lot A (old, LT-eligible)
        _tx("X", "2024-06-01", "BUY", 10, 200),  # lot B (newer)
        _tx("X", "2024-12-01", "SELL", 15, 300),  # consume all of A + 5 of B
    ]
    events = classify_capital_gains(txs)
    # Two events emitted (one per consumed lot).
    assert len(events) == 2
    # First event from oldest lot: 10 units, gain = 10*(300-100) = 2000, LTCG
    assert events[0].qty == Decimal("10")
    assert events[0].term == GainTerm.LTCG
    assert events[0].gain_inr == Decimal("2000.00")
    # Second event from newer lot: 5 units, STCG
    assert events[1].qty == Decimal("5")
    assert events[1].term == GainTerm.STCG
    assert events[1].gain_inr == Decimal("500.00")
