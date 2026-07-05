"""AMFI NAV parsing + tracked-scheme filtering (pfip.ingest.indian_mf.amfi_nav).

The filter is what keeps the nightly pipeline from upserting ~50,000 scheme
NAVs into free-tier Neon (the old behaviour timed out > 420s).
"""

from __future__ import annotations

import pytest

from pfip.ingest.indian_mf import amfi_nav as A

_SAMPLE = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
119551;INF209K01157;INF209K01165;ABSL Banking Growth;100.5;05-Jul-2026
120503;INF090I01239;-;Franklin India Bluechip;50.25;05-Jul-2026
118989;INF179K01BE2;INF179K01BF9;HDFC Flexi Cap;1234.5;05-Jul-2026
"""


@pytest.fixture(autouse=True)
def _stub_download(monkeypatch):
    async def fake_download() -> str:
        return _SAMPLE

    monkeypatch.setattr(A, "_download", fake_download)


@pytest.mark.asyncio
async def test_no_filter_keeps_all():
    rows = await A.fetch_amfi_nav(None)
    assert {r["symbol"] for r in rows} == {"MF_119551", "MF_120503", "MF_118989"}
    # NAV is fanned out into OHLC and volume is 0.
    r0 = next(r for r in rows if r["symbol"] == "MF_119551")
    assert r0["close"] == 100.5 and r0["open"] == r0["high"] == r0["low"] == 100.5
    assert r0["market"] == "MF_INDIA"


@pytest.mark.asyncio
async def test_empty_allowed_keeps_none():
    assert await A.fetch_amfi_nav(set()) == []


@pytest.mark.asyncio
async def test_filter_by_scheme_code_and_mf_prefix():
    # Both the bare code and the MF_<code> form must match.
    assert {r["symbol"] for r in await A.fetch_amfi_nav({"119551"})} == {"MF_119551"}
    assert {r["symbol"] for r in await A.fetch_amfi_nav({"MF_120503"})} == {"MF_120503"}


@pytest.mark.asyncio
async def test_filter_by_isin():
    # A holding stored by ISIN (either growth or reinvestment column) resolves.
    assert {r["symbol"] for r in await A.fetch_amfi_nav({"INF179K01BE2"})} == {"MF_118989"}
    assert {r["symbol"] for r in await A.fetch_amfi_nav({"INF179K01BF9"})} == {"MF_118989"}
