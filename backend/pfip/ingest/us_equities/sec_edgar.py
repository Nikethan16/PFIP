"""SEC EDGAR — 10-K/10-Q/8-K filings + company facts.

No API key required; SEC mandates a descriptive User-Agent with contact info.
We set ``SEC_EDGAR_USER_AGENT`` (falls back to the common PFIP UA).

We use two endpoints:
- ``data.sec.gov/submissions/CIK{10-digit}.json``      -> recent filings list
- ``data.sec.gov/api/xbrl/companyfacts/CIK{10-digit}.json`` -> structured facts

Filings are stored as news rows with category=``sec_filing``; companyfacts
numeric series go to fundamentals using filing date as ``as_of_date`` (PIT).
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from pfip.core.logging import get_logger
from pfip.db.session import get_sessionmaker
from pfip.ingest._common.http import USER_AGENT, get_async_client, retry_http
from pfip.ingest._common.upsert import upsert_fundamentals, upsert_news

log = get_logger("pfip.ingest.us_equities.sec_edgar")

BASE = "https://data.sec.gov"


_ua_warned = False


def _ua_headers() -> dict[str, str]:
    # SEC hard-403s any request whose User-Agent doesn't identify you with a
    # contact email. When SEC_EDGAR_USER_AGENT is unset we fall back to the
    # generic UA (which SEC rejects) — warn ONCE so the fix is discoverable
    # instead of a wall of silent 403s.
    global _ua_warned
    configured = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    if not configured and not _ua_warned:
        _ua_warned = True
        log.warning(
            "SEC_EDGAR_USER_AGENT not set — SEC will 403 every request. Set it to "
            "'Your Name your@email' in the env (and the GitHub secret) to enable "
            "US filings ingestion."
        )
    ua = configured or USER_AGENT
    return {"User-Agent": ua, "Accept": "application/json"}


@retry_http(max_attempts=3)
async def _get_json(path: str) -> Any:
    async with get_async_client(headers=_ua_headers()) as client:
        r = await client.get(f"{BASE}{path}")
        r.raise_for_status()
        return r.json()


def _cik10(cik: int | str) -> str:
    return str(int(str(cik))).zfill(10)


async def fetch_submissions(cik: int | str) -> list[dict[str, Any]]:
    """Return a list of news-shaped rows for the company's recent filings."""
    try:
        sub = await _get_json(f"/submissions/CIK{_cik10(cik)}.json")
    except Exception as e:  # noqa: BLE001
        log.warning(f"sec_edgar: submissions {cik} failed: {type(e).__name__}: {e}")
        return []
    ticker = (sub.get("tickers") or [None])[0]
    name = sub.get("name") or ""
    recent = (sub.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []
    items: list[dict[str, Any]] = []
    for form, d, acc, doc in zip(forms, dates, accessions, primary_docs):
        if form not in ("10-K", "10-Q", "8-K"):
            continue
        try:
            t = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        acc_clean = acc.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{doc}"
        items.append(
            {
                "time": t,
                "title": f"{ticker or name} {form} filed {d}",
                "url": url,
                "source": "sec_edgar",
                "symbol": ticker,
                "summary": f"{name} — {form}",
                "category": "sec_filing",
            }
        )
    return items


async def fetch_company_facts(cik: int | str, max_facts: int = 20) -> list[dict[str, Any]]:
    """Return fundamentals rows from companyfacts (numeric, latest-per-field)."""
    try:
        facts = await _get_json(f"/api/xbrl/companyfacts/CIK{_cik10(cik)}.json")
    except Exception as e:  # noqa: BLE001
        log.warning(f"sec_edgar: companyfacts {cik} failed: {type(e).__name__}: {e}")
        return []
    entity = facts.get("entityName") or ""
    ticker = None  # companyfacts has no ticker; caller often passes via submissions
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    out: list[dict[str, Any]] = []
    # Iterate at most max_facts fact keys to keep runtime bounded.
    for field_key, blob in list(gaap.items())[:max_facts]:
        units = blob.get("units") or {}
        # Use the first available unit (USD, USD/shares, shares, etc.).
        for _unit_key, observations in units.items():
            if not isinstance(observations, list):
                continue
            # Keep only items with a "filed" date and numeric val.
            for obs in observations[-25:]:  # last 25 per field to bound volume
                val = obs.get("val")
                filed = obs.get("filed")
                end = obs.get("end")
                if val is None or not filed or not end:
                    continue
                try:
                    as_of = date.fromisoformat(filed)
                    rep = date.fromisoformat(end)
                except Exception:
                    continue
                out.append(
                    {
                        "as_of_date": as_of,
                        "report_date": rep,
                        "symbol": ticker or entity[:20].upper(),
                        "field": f"gaap_{field_key}",
                        "value": val,
                        "source": "sec_edgar",
                    }
                )
            break  # take only first unit family per field
    return out


async def ingest_sec_edgar(
    ciks: Iterable[int | str] = (320193, 789019, 1652044),  # Apple, Microsoft, Alphabet
    session: AsyncSession | None = None,
) -> int:
    """Ingest SEC filings + companyfacts for CIKs."""
    log.info("ingest.sec_edgar starting")
    all_news: list[dict[str, Any]] = []
    all_facts: list[dict[str, Any]] = []
    for cik in ciks:
        all_news.extend(await fetch_submissions(cik))
        all_facts.extend(await fetch_company_facts(cik))
    if session is None:
        factory = get_sessionmaker()
        async with factory() as s:
            n1 = await upsert_news(s, all_news)
            n2 = await upsert_fundamentals(s, all_facts)
    else:
        n1 = await upsert_news(session, all_news)
        n2 = await upsert_fundamentals(session, all_facts)
    total = n1 + n2
    log.info(f"ingest.sec_edgar done: {total} rows")
    return total
