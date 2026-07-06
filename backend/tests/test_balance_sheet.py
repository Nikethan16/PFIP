"""Balance-sheet engine — deterministic ratio + Altman-Z math + router smoke."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pfip.research.balance_sheet import (
    BalanceSheetInput,
    compute_metrics,
    parse_csv_bytes,
    parse_text,
)


def _ratio(metrics, key):  # noqa: ANN001
    return next(r for r in metrics.ratios if r.key == key)


def test_ratios_compute_correctly() -> None:
    inp = BalanceSheetInput(
        total_current_assets=200.0,
        total_current_liabilities=100.0,
        inventory=50.0,
        total_assets=500.0,
        total_liabilities=250.0,
        total_equity=250.0,
        total_debt=150.0,
        ebit=80.0,
        interest_expense=20.0,
    )
    m = compute_metrics(inp)
    assert _ratio(m, "current_ratio").value == 2.0
    assert _ratio(m, "current_ratio").health == "strong"
    assert _ratio(m, "quick_ratio").value == 1.5  # (200-50)/100
    assert _ratio(m, "debt_to_equity").value == 0.6  # 150/250
    assert _ratio(m, "interest_coverage").value == 4.0  # 80/20
    # ROCE = EBIT / (assets - current liabs) = 80 / (500-100) = 0.2
    assert abs(_ratio(m, "roce").value - 0.2) < 1e-9
    assert _ratio(m, "roce").health == "strong"


def test_missing_inputs_report_unknown_not_guess() -> None:
    m = compute_metrics(BalanceSheetInput(total_current_assets=100.0))
    cr = _ratio(m, "current_ratio")
    assert cr.value is None
    assert cr.health == "unknown"
    assert "total_current_liabilities" in m.missing_fields


def test_altman_z_safe_zone() -> None:
    # Numbers chosen to land clearly in the safe zone (Z >= 2.99).
    inp = BalanceSheetInput(
        total_current_assets=300.0,
        total_current_liabilities=100.0,
        total_assets=500.0,
        total_liabilities=150.0,
        total_equity=350.0,
        retained_earnings=200.0,
        ebit=120.0,
        revenue=600.0,
    )
    m = compute_metrics(inp)
    z = m.altman_z
    assert z.score is not None
    assert z.zone == "safe"
    assert z.used_market_value is False


def test_altman_z_incomplete_is_unknown() -> None:
    m = compute_metrics(BalanceSheetInput(total_assets=500.0))
    assert m.altman_z.score is None
    assert m.altman_z.zone == "unknown"


def test_parse_csv_matches_labels() -> None:
    # Thousands separators must be quoted in real CSVs (else they split cells).
    data = (
        b'Total current assets,"1,200"\n'
        b"Total Current Liabilities,600\n"
        b'Total assets,"3,000"\n'
        b"Shareholders' equity,1500\n"
        b"Operating profit,450\n"
    )
    fields = parse_csv_bytes(data)
    assert fields["total_current_assets"] == 1200.0
    assert fields["total_current_liabilities"] == 600.0
    assert fields["total_assets"] == 3000.0
    assert fields["total_equity"] == 1500.0
    assert fields["ebit"] == 450.0


def test_parse_text_takes_last_number_and_negatives() -> None:
    text = "Total current liabilities   (1,500)\nRevenue from operations 2024 8,000"
    fields = parse_text(text)
    assert fields["total_current_liabilities"] == -1500.0
    assert fields["revenue"] == 8000.0


# --- router smoke -----------------------------------------------------------


def test_analyze_requires_auth(client: TestClient) -> None:
    resp = client.post("/api/v1/balance-sheet/analyze", json={})
    assert resp.status_code == 401


def test_analyze_returns_metrics(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/balance-sheet/analyze",
        headers=auth_headers,
        json={
            "total_current_assets": 200,
            "total_current_liabilities": 100,
            "total_assets": 500,
            "total_equity": 250,
            "ebit": 80,
            "interest_expense": 20,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    keys = {r["key"] for r in body["metrics"]["ratios"]}
    assert {"current_ratio", "debt_to_equity", "roce"} <= keys
    assert "insight_markdown" in body


def test_upload_csv_extracts_and_analyzes(client: TestClient, auth_headers: dict[str, str]) -> None:
    csv_bytes = (
        b"Total current assets,200\n"
        b"Total current liabilities,100\n"
        b"Total assets,500\n"
        b"Shareholders' equity,250\n"
        b"Operating profit,80\n"
    )
    resp = client.post(
        "/api/v1/balance-sheet/upload",
        headers=auth_headers,
        files={"file": ("bs.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_current_assets" in body["parsed_fields"]
    cr = next(r for r in body["metrics"]["ratios"] if r["key"] == "current_ratio")
    assert cr["value"] == 2.0


def test_upload_rejects_unknown_type(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/balance-sheet/upload",
        headers=auth_headers,
        files={"file": ("x.docx", b"nope", "application/octet-stream")},
    )
    assert resp.status_code == 415
