# PFIP — Everything Needed From You (inputs, keys, data)

> **Status:** You've already set the **18 keys that matter most** — the app runs with real
> US/India/crypto/FX data, fundamentals, macro, news, on-chain (ETH), and the GROQ LLM.
> Almost everything below is **optional**. The **one** thing that unlocks the next big
> capability (always-on ingestion) is **Neon + GitHub Secrets** (Section 1).

Two places secrets live:
- **Local** → `.env` at the project root (gitignored, never committed). After editing, apply with:
  `docker compose --env-file .env -f infra/docker-compose.yml up -d backend prefect-worker`
- **Cloud (GitHub Actions)** → repo **Settings → Secrets and variables → Actions → New repository secret**. Used only by the daily-ingest / backfill workflows.

A key set **only locally** affects the local app. A key set **only in GitHub Secrets** affects the cloud cron. For always-on, the data keys go in **both**.

---

## ✅ Already set (no action) — 18
`NEXTAUTH_SECRET`, `PFIP_USER_PASSWORD_HASH`, `FINNHUB_API_KEY`, `TIINGO_API_KEY`,
`POLYGON_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `SEC_EDGAR_USER_AGENT`, `FRED_API_KEY`,
`EIA_API_KEY`, `EXCHANGERATE_API_KEY`, `NASDAQ_DATA_LINK_API_KEY`, `NEWSAPI_API_KEY`,
`MARKETAUX_API_KEY`, `ETHERSCAN_API_KEY`, `COINGECKO_API_KEY`, `REDDIT_USER_AGENT`,
`GROQ_API_KEY`, `SENTRY_DSN`.

---

## 1. 🟢 HIGH — Always-on ingestion (Neon + GitHub Actions)
This is the main pending item. Full runbook in `docs/CLOUD_MIGRATION.md`; the short version:

| What | How to get it | Where it goes |
|---|---|---|
| **Neon database** | Sign up free at **https://neon.tech** → create a project → copy the connection string. Convert `postgresql://USER:PASS@HOST/db` → **`postgresql+psycopg://USER:PASS@HOST/db?sslmode=require`** | GitHub Secret **`DATABASE_URL`** (and optionally your local `.env` `DATABASE_URL` so the local app reads cloud data) |
| **GitHub Secrets for the cron** | Copy each data key you already have in `.env` into repo Secrets | GitHub → Settings → Secrets → Actions |

**GitHub Secrets to add** (so the cloud cron has the same powers as local): `DATABASE_URL` (required) + `TIINGO_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `NEWSAPI_API_KEY`, `MARKETAUX_API_KEY`, `ETHERSCAN_API_KEY`, `SEC_EDGAR_USER_AGENT`, `GROQ_API_KEY`, `NASDAQ_DATA_LINK_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `EIA_API_KEY` (and any optional ones below you add). Keyless sources (ccxt crypto, jugaad India, Frankfurter FX, Screener, RSS) need nothing.

**Then:** run the **Backfill** workflow once (Actions tab) → then **daily-ingest** runs on schedule. Free tier is ~0.5 GB (your data ~150–400 MB; retention keeps it bounded).

---

## 2. 🟡 MEDIUM — High-value optional keys (≈5 min each, all free)

| Key | What it unlocks | How to get | Put in |
|---|---|---|---|
| **`SOLSCAN_API_KEY`** | Solana wallet tracking (you have ETH via Etherscan; this adds SOL) | https://solscan.io → API (free tier) | `.env` (+ GH Secret) |
| **`GEMINI_API_KEY`** | A 2nd cloud LLM (long-context fallback behind GROQ) | https://aistudio.google.com → Get API key (free) | `.env` |
| **`DEEPSEEK_API_KEY`** | LLM fallback (strong reasoning), cheap | https://platform.deepseek.com | `.env` |
| **`CRYPTOPANIC_API_KEY`** | Crypto-specific news feed | https://cryptopanic.com/developers/api (free) | `.env` (+ GH Secret) |
| **`FMP_API_KEY`** | Deeper financial statements for diligence | https://financialmodelingprep.com (free 250/day) | `.env` (+ GH Secret) |

---

## 3. 🔔 Telegram alerts (optional — morning brief / signal / regime notifications)
Use a **dedicated** Telegram account (not your personal one for the API). Steps:
1. **`TELEGRAM_API_ID`** + **`TELEGRAM_API_HASH`** → https://my.telegram.org → API development tools.
2. **`TELEGRAM_BOT_TOKEN`** → message **@BotFather** → `/newbot` → copy the token.
3. **`TELEGRAM_BOT_CHAT_ID`** → message your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy `chat.id`.
4. In `.env` set those + flip **`FEATURE_TELEGRAM_ALERTS=true`**, and in the app **Settings → toggle Telegram alerts** (now actually wired to gate sends).
Put in `.env` (local) — alerts run wherever the backend runs.

---

## 4. ⚪ LOW — Niche / skip unless you want them
- `BINANCE_*`, `COINBASE_*`, `ALPACA_*` — private exchange keys. **Not needed** — public OHLCV already works; advisory-only app never trades.
- `GLASSNODE_API_KEY`, `COINGLASS_API_KEY`, `BSCSCAN_API_KEY` — extra on-chain / derivatives depth.
- `REDDIT_CLIENT_ID/SECRET`, `BLUESKY_HANDLE/APP_PASSWORD`, `NEYNAR_API_KEY` — social-sentiment sources (you already have RSS/NewsAPI/GDELT/Marketaux).
- `LANGSMITH_API_KEY` — LLM trace debugging (dev only).
- `OPENROUTER_API_KEY`, `NVIDIA_NIM_API_KEY`, `COHERE_API_KEY`, `CEREBRAS_API_KEY` — more LLM providers / cloud embeddings / reranking. Local Ollama covers these.
- `POSTGRES_PASSWORD` — currently the dev default; fine locally, but set a strong value if you ever expose the DB.

---

## 5. 📊 YOUR DATA (not keys — your actual inputs)
| Item | How | Status |
|---|---|---|
| **Real holdings** (stocks, MFs, PPF/EPF/FD/SGB, crypto) | App → **Portfolio → Add holding** (new dialog), or **Portfolio → Import CSV** (broker tradebook → auto-builds holdings) | ✅ just built |
| **Self-custody wallets** (BTC/ETH/SOL addresses) | App → **Settings → Self-custody wallets → Add** | ✅ just built |
| **Knowledge-base books** | Drop PDFs in `data/kb_sources/`, then `docker exec pfip-backend python -m pfip.kb.ingest /data/kb_sources/`. (16 legal classics/papers already ingested.) In-copyright books (Market Wizards, etc.): buy + add legally. | ✅ pipeline ready |
| **Tax: prior ITR filing** (optional) | For the annual reconciliation drill, drop `data/itr_filed/<FY>.json` (`{stcg_equity_inr, ltcg_equity_inr, vda_gain_inr, dividend_inr, interest_inr, total_tax_inr}`) | optional |

---

## How to apply any change
- **Local key change:** edit `.env` → `docker compose --env-file .env -f infra/docker-compose.yml up -d backend prefect-worker`. For frontend-affecting env, also rebuild the frontend image.
- **GitHub Secret change:** add/edit in repo Settings → picked up on the next workflow run.
- **Never** paste a key into chat or commit `.env` — both are gitignored and stay on your machine.

---

### Priority recap
1. **Neon + GitHub Secrets** → always-on ingestion (the one real unlock).
2. *(optional)* `SOLSCAN` (SOL wallets), a 2nd LLM key (`GEMINI`/`DEEPSEEK`), Telegram (alerts).
3. **Add your real holdings** + wallets in the app.

Everything else is already working or genuinely optional. Anything time-gated (signals getting
trustworthy, journal failure-pattern clustering) just needs accumulated runtime — no input from you.
