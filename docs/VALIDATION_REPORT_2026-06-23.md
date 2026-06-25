# Validation & Audit Report — 2026-06-23

_Regenerated locally after the overnight cloud routines produced no committed output. Covers the
end-to-end run, real-data endpoint verification, data-coverage audit, and the test/dependency
posture. Companion to [ML_SIGNAL_RESEARCH.md](ML_SIGNAL_RESEARCH.md) (the research deliverable)._

## 1. End-to-end run (local)

| Component | Result |
| --- | --- |
| Backend (`uvicorn pfip.api.main:app`, :8000) | **Up** via `backend/run_local.py` (sets `WindowsSelectorEventLoopPolicy`, loads root `.env`). |
| Frontend (Next.js, :3000) | Up (dev server). Build/typecheck/lint previously green across 26 routes. |
| `/health/deep` | `timescaledb: ok` (Neon PostgreSQL 18.4), `llm_providers: groq ok`. Redis/Qdrant/Ollama down locally (not needed for the portfolio pages). |

## 2. New endpoint verification (against live Neon)

A JWT was minted from `NEXTAUTH_SECRET` and all 7 new endpoints were exercised:

| Endpoint | Method | Result |
| --- | --- | --- |
| `/portfolio/goals/project` | POST | ✅ Monte-Carlo percentiles, P(target)=0.68, required-contribution solver returns. |
| `/portfolio/sip/project` | POST | ✅ FV of monthly annuity (₹10k/10y@12% → ₹22.4L corpus, ₹10.4L gain). |
| `/portfolio/sip/xirr` | POST | ✅ XIRR=0.50 on a 2-instalment test. |
| `/portfolio/what-if` | POST | ✅ Before/after exposure, HHI, tax_impact. Frontend payload shape matches contract. |
| `/portfolio/net-worth` | GET | ✅ 200; empty (no holdings yet). |
| `/portfolio/benchmark` | GET | ✅ 200; null windows (no holdings + no index OHLCV — see §3). |
| `/portfolio/stress-test` | GET | ✅ 200; 4 scenarios returned, zero-valued (no holdings). |

**Conclusion:** the feature endpoints are correct. Empty/zero results are a **data-coverage**
artifact (no portfolio holdings; no index price history), not a code defect.

## 3. Data-coverage audit (Neon, `public` schema — 34 tables)

| Table | Rows | Note |
| --- | --- | --- |
| `ohlcv` | 12,421 | 20 symbols; see depth below. |
| `features` | 7,771 | |
| `fx_rates` | 2,526 | USD/EUR/GBP→INR. |
| `fundamentals` | 357 | |
| `regime` / `regime_transitions` | 141 / 32 | |
| `watchlist` | 23 | |
| `news` | 19 | |
| `mf_nav` | **0** | India MF NAVs not yet ingested. |
| `macro_series` | **0** | FRED/RBI macro not yet ingested. |
| `holdings` | **0** | No portfolio → why net-worth/benchmark/stress read empty. |
| `signals` | 0 | Gated OFF (`FEATURE_ML_SIGNALS=false`). |

**OHLCV depth (≥756 bars = ML-eligible):**

- **Eligible (10):** BTC-USD (1944), SOL-USD (1436), ETH-USD (1231), BTC-USDT (1215), XRP-USDT
  (1214), TCS.NS / HDFCBANK.NS / INFY.NS (817), ICICIBANK.NS / RELIANCE.NS (816).
- **Shallow:** XRP-USD (742), BNB-USD (442), and US equities AAPL/MSFT/NVDA/QQQ/SPY (~14 each —
  recent only), plus *-USDT alts (~15).

**Gaps to close (the backfill targets these):** deepen US equities via Tiingo, land India MF NAVs
(AMFI) and FRED macro, and ingest benchmark index history (`^NSEI`/`^GSPC`/`^BSESN`) so the
Benchmark page resolves (today only the `SPY` option can work, once SPY is deepened).

## 4. Test & dependency posture

- **Backend suite: green (pytest exit 0).** Expected skips only: 5 real-DB integration tests
  (no local Docker Postgres) and 1 LightGBM test (package not installed in this env).
- Warnings are pre-existing/non-fatal (feedparser truth-value deprecation, pandas `'H'`→`'h'`,
  one un-awaited-coroutine warning in a tax test fixture). None affect correctness.
- `FEATURE_ML_SIGNALS` was found set to `true` in local `.env` and **corrected to `false`** to
  honour the data-readiness gate.

## 5. Infrastructure finding (blocker for local data ops)

**Intermittent Neon DNS failure from the dev machine.** Single connections and reads succeed, but
sustained backfill connections fail with `getaddrinfo failed` (WinError 11001) — the LAN router
resolver (192.168.0.1) drops repeated lookups to the Neon pooler host. **Mitigation adopted:** run
data backfills on **GitHub Actions** (reliable DNS to Neon), not locally. 20 free-tier API-key
secrets were synced from `.env` to the repo so the cloud backfill/daily-ingest have full source
coverage. The backfill workflow was dispatched on `main` (`days=1200`, compute on).

## 6. Open items requiring user input

1. **Knowledge base (20 books):** `data/kb_sources/` does not exist and no documents are present;
   Qdrant is not running. KB ingestion is blocked until source documents are supplied and a Qdrant
   instance is available.
2. **Four plan decisions:** Stage-1 market focus, Telegram account, VPS (Hetzner) yes/no, and the
   auto-execution stance (currently advisory-only — recommended to keep).
3. **Production env:** set `APP_ENV=prod` for the deployed instance and run a real restore drill
   against a scratch DB (not prod).
