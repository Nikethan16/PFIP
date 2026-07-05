"""Rich fundamentals: statement normalization + trend + peer ranking
(pfip.research.statements, pfip.diligence.peers). Pure-logic coverage; the
network/DB paths are best-effort and integration-covered.
"""

from __future__ import annotations

import pytest

from pfip.diligence import peers as PEERS
from pfip.research import statements as ST


# --- statement normalization -------------------------------------------------


def test_normalize_reports_maps_and_limits():
    reports = [
        {
            "fiscalDateEnding": "2025-12-31",
            "totalRevenue": "1000",
            "netIncome": "120",
            "grossProfit": "400",
        },
        {
            "fiscalDateEnding": "2024-12-31",
            "totalRevenue": "900",
            "netIncome": "None",
            "grossProfit": "350",
        },
        {
            "fiscalDateEnding": "2023-12-31",
            "totalRevenue": "800",
            "netIncome": "60",
            "grossProfit": "300",
        },
    ]
    out = ST._normalize_reports(reports, ST._INCOME_MAP, years=2)
    assert [r["period"] for r in out] == ["2025-12-31", "2024-12-31"]  # newest first, capped
    assert out[0]["revenue"] == 1000.0 and out[0]["net_income"] == 120.0
    assert out[1]["net_income"] is None  # "None" sentinel dropped to null


def test_derive_trend_computes_margin_and_fcf():
    income = [
        {"period": "2025-12-31", "revenue": 1000.0, "net_income": 200.0},
        {"period": "2024-12-31", "revenue": 800.0, "net_income": 120.0},
    ]
    cash_flow = [
        {"period": "2025-12-31", "operating_cash_flow": 300.0, "capex": -50.0},
        {"period": "2024-12-31", "operating_cash_flow": 250.0, "capex": -40.0},
    ]
    trend = ST._derive_trend(income, cash_flow)
    # Oldest-first for a left→right chart.
    assert [t["period"] for t in trend] == ["2024-12-31", "2025-12-31"]
    last = trend[-1]
    assert last["net_margin_pct"] == 20.0  # 200/1000
    assert last["free_cash_flow"] == 250.0  # 300 - |−50|


# --- peer comparison ---------------------------------------------------------


def test_peers_for_resolves_group():
    assert set(PEERS.peers_for("TCS.NS")) == {"INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"}
    assert PEERS.peers_for("NVDA")  # in two groups; returns the first match
    assert PEERS.peers_for("ZZZZ") == []


def test_compare_ranks_target_vs_peers():
    metrics = {
        "TCS.NS": {"pe_ratio": 22.0, "roe": 40.0, "net_margin": 20.0},
        "INFY.NS": {"pe_ratio": 25.0, "roe": 30.0, "net_margin": 18.0},
        "WIPRO.NS": {"pe_ratio": 18.0, "roe": 20.0, "net_margin": 15.0},
    }
    out = PEERS.compare("TCS.NS", metrics)
    assert out["n_peers"] == 2
    # ROE 40 beats both peers (30, 20) → better_than_pct 100, rank 1 (best).
    roe = out["fields"]["roe"]
    assert roe["better"] == "higher" and roe["better_than_pct"] == 100.0 and roe["rank"] == 1
    assert roe["peer_median"] == 25.0  # median(30, 20)
    # P/E 22 is cheaper than INFY (25) but pricier than WIPRO (18) → beats 1 of 2.
    pe = out["fields"]["pe_ratio"]
    assert pe["better"] == "lower" and pe["better_than_pct"] == 50.0


def test_compare_skips_fields_target_lacks():
    metrics = {"TCS.NS": {"roe": 40.0}, "INFY.NS": {"roe": 30.0, "pe_ratio": 25.0}}
    out = PEERS.compare("TCS.NS", metrics)
    assert "roe" in out["fields"]
    assert "pe_ratio" not in out["fields"]  # target has no P/E → skipped
