"""Financial statements + multi-year history for Deep Research / Diligence.

Extends the single-snapshot ``key_metrics`` with the three statements (income,
balance sheet, cash flow) over the last ~5 fiscal years, plus a compact derived
trend (revenue / net income / margins / FCF). US comes from Alpha Vantage's
``INCOME_STATEMENT`` / ``BALANCE_SHEET`` / ``CASH_FLOW`` (proven reachable from
the VM); India statement parsing (screener.in tables) is a follow-up.

Everything is best-effort and never raises: a missing key or a rate-limited
response yields an empty section, and the caller degrades gracefully.
"""

from __future__ import annotations

import os
from typing import Any

from pfip.core.logging import get_logger
from pfip.ingest._common.http import get_async_client, retry_http

log = get_logger("pfip.research.statements")

_AV_BASE = "https://www.alphavantage.co/query"


def _av_key() -> str:
    return (
        os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY") or ""
    ).strip()


def _num(v: Any) -> float | None:
    """AV numbers are strings; 'None'/'-' are missing sentinels."""
    if v in (None, "None", "", "-"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# AV field → our canonical line-item name, per statement.
_INCOME_MAP = {
    "totalRevenue": "revenue",
    "grossProfit": "gross_profit",
    "operatingIncome": "operating_income",
    "netIncome": "net_income",
    "ebitda": "ebitda",
    "researchAndDevelopment": "r_and_d",
    "interestExpense": "interest_expense",
}
_BALANCE_MAP = {
    "totalAssets": "total_assets",
    "totalLiabilities": "total_liabilities",
    "totalShareholderEquity": "total_equity",
    "cashAndCashEquivalentsAtCarryingValue": "cash",
    "shortLongTermDebtTotal": "total_debt",
    "inventory": "inventory",
    "commonStockSharesOutstanding": "shares_outstanding",
}
_CASHFLOW_MAP = {
    "operatingCashflow": "operating_cash_flow",
    "capitalExpenditures": "capex",
    "cashflowFromInvestment": "investing_cash_flow",
    "cashflowFromFinancing": "financing_cash_flow",
    "dividendPayout": "dividends_paid",
}


def _normalize_reports(reports: list[dict], mapping: dict[str, str], years: int) -> list[dict]:
    """Map AV annualReports → [{period, <canonical line items>}], newest first."""
    out: list[dict[str, Any]] = []
    for rep in reports[:years]:
        period = rep.get("fiscalDateEnding")
        if not period:
            continue
        row: dict[str, Any] = {"period": period}
        for av_field, canon in mapping.items():
            row[canon] = _num(rep.get(av_field))
        out.append(row)
    return out


@retry_http(max_attempts=2)
async def _av_statement(function: str, symbol: str, key: str) -> dict[str, Any]:
    async with get_async_client() as client:
        r = await client.get(
            _AV_BASE, params={"function": function, "symbol": symbol, "apikey": key}
        )
        r.raise_for_status()
        return r.json() or {}


def _derive_trend(income: list[dict], cash_flow: list[dict]) -> list[dict]:
    """Per-period revenue / net income / net margin / FCF, oldest→newest, for a
    sparkline-friendly trend."""
    cf_by_period = {c["period"]: c for c in cash_flow}
    trend: list[dict[str, Any]] = []
    for row in reversed(income):  # oldest first for a left→right chart
        rev = row.get("revenue")
        ni = row.get("net_income")
        cf = cf_by_period.get(row["period"], {})
        ocf, capex = cf.get("operating_cash_flow"), cf.get("capex")
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
        trend.append(
            {
                "period": row["period"],
                "revenue": rev,
                "net_income": ni,
                "net_margin_pct": round(ni / rev * 100, 2) if (rev and ni is not None) else None,
                "free_cash_flow": fcf,
            }
        )
    return trend


async def fetch_us_statements(symbol: str, *, years: int = 5) -> dict[str, Any]:
    """Fetch + normalize US income/balance/cash-flow (annual, ~5yr) via AV.

    Returns ``{source, currency, income[], balance_sheet[], cash_flow[], trend[]}``
    or ``{}`` on no-key / rate-limit / miss. Spends up to 3 AV calls, so callers
    should invoke it on-demand (Deep Research), not in a nightly sweep.
    """
    key = _av_key()
    if not key:
        return {}
    sym = symbol.split(".")[0].upper()
    try:
        inc = await _av_statement("INCOME_STATEMENT", sym, key)
        if inc.get("Note") or inc.get("Information"):
            log.warning("statements: AV rate-limited")
            return {}
        bal = await _av_statement("BALANCE_SHEET", sym, key)
        cf = await _av_statement("CASH_FLOW", sym, key)
    except Exception as e:  # noqa: BLE001
        log.warning(f"statements: {sym} failed: {type(e).__name__}: {e}")
        return {}

    income = _normalize_reports(inc.get("annualReports") or [], _INCOME_MAP, years)
    balance = _normalize_reports(bal.get("annualReports") or [], _BALANCE_MAP, years)
    cash_flow = _normalize_reports(cf.get("annualReports") or [], _CASHFLOW_MAP, years)
    if not (income or balance or cash_flow):
        return {}
    currency = None
    for rep_set in (inc, bal, cf):
        reps = rep_set.get("annualReports") or []
        if reps and reps[0].get("reportedCurrency"):
            currency = reps[0]["reportedCurrency"]
            break
    return {
        "source": "alphavantage",
        "currency": currency,
        "income": income,
        "balance_sheet": balance,
        "cash_flow": cash_flow,
        "trend": _derive_trend(income, cash_flow),
    }


__all__ = ["fetch_us_statements"]
