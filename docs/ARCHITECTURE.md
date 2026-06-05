# PFIP Architecture

Operational view of the system. For product scope and roadmap, see plan Sections 1, 2, and
12. For the exact tech stack & justifications, see plan Section 11. For the canonical
interfaces between modules, see `./CONTRACTS.md`.

---

## 1. Module map (M1–M9)

Each module is a Python package under `/backend/pfip/` and a matching UI surface under
`/frontend/app/`. Boundaries follow the plan.

| Module | Name                       | Purpose                                                                                     | Stage  |
| ------ | -------------------------- | ------------------------------------------------------------------------------------------- | ------ |
| M1     | Ingest & data layer        | Pull OHLCV, fundamentals, news, on-chain, macro. Write to TimescaleDB / Qdrant / Redis.     | 0 → 1  |
| M2     | Feature engineering        | PIT-safe features: RSI, MACD, ATR, vol, returns, on-chain, sentiment.                       | 1      |
| M3     | Regime detection           | HMM / rules classifier → `bull_trend | bear_trend | sideways | ...` from CONTRACTS.md.      | 2      |
| M4     | ML signal layer            | Per-asset models; outputs `Signal` contract with confidence, drivers, counter-arguments.    | 4      |
| M5     | Backtesting engine         | vectorbt-based; CPCV + walk-forward; calibration (Brier, ECE) tracked in MLflow.            | 4      |
| M6     | Knowledge base             | 20 reference books chunked + embedded (nomic-embed-text) in Qdrant; hybrid retrieval.       | 3      |
| M7     | Chat agent                 | LangGraph agent; reads M3/M4/M6 but cannot mutate signals. SSE streaming to frontend.       | 3      |
| M8     | Portfolio + shadow ledger  | Real holdings (6 categories) + mirror paper-traded shadow; XIRR, drawdown, exposure maps.   | 5      |
| M9     | Tax + compliance           | India-first: STCG/LTCG, VDA, Schedule FA, Form 67 (DTAA), XIRR statement.                   | 5      |

Cross-cutting concerns:

- **Auth:** NextAuth single-user with bcrypt (frontend); JWT verified by FastAPI.
  `frontend/middleware.ts` gates every route except `/login`, `/api/auth`, and static
  assets; the `/api/v1/assets/*` endpoints now require an authenticated user.
- **Observability:** Uptime Kuma (service liveness) + Sentry (errors, now wired in
  `backend/pfip/api/main.py` when `SENTRY_DSN` is set; no-op otherwise) + LangSmith (LLM
  traces, optional). A global RFC-7807 exception handler logs server-side and returns a
  generic `problem+json` body. `/health/deep` separates CORE deps (TimescaleDB, Redis) from
  OPTIONAL (Qdrant, Ollama, cloud LLM) and reports `ok` / `degraded` / `down` + a `ready`
  boolean.
- **Scheduling:** Prefect 2 for all recurring flows (see `docs/SCHEDULED_TASKS.md`).
- **Safety:** Advisory-only. `FEATURE_LIVE_TRADING=false` hard-wired. Risk caps in
  `/backend/pfip/portfolio/risk_manager.py`. The chat agent structurally forces local-only
  LLM routing whenever any holding row is in the prompt, so holdings never reach a cloud LLM
  (see `docs/LLM_ROUTING.md` §5).

---

### ML layer status (be precise about what's live)

The M3–M5 stack is implemented and partly scheduled, but **live per-asset signal generation
is intentionally NOT enabled** — be careful not to overclaim it:

- **Real & scheduled:** regime detection (HMM, BTC daily), backtesting (walk-forward + CPCV
  + Monte Carlo + shuffle test, BTC weekly), calibration (Brier/ECE + suspension rules,
  monthly), technical features (BTC via the legacy `compute_features_flow`). The LightGBM
  model code (walk-forward training, isotonic calibration, SHAP drivers) is implemented and
  correct.
- **Scaffolded but NOT deployed/wired:** the `signals_generate_daily` Prefect flow is not in
  the deployment, so the `signals` table stays empty and the daily shadow-reconcile reads
  nothing. The multi-asset `compute_features_daily` flow is also not deployed (only the
  legacy BTC-only features run).
- **`FEATURE_ML_SIGNALS`** config flag is defined but checked nowhere (dead; no
  stage-gating implemented yet).
- **Why off:** the walk-forward trainer needs ~3 years / 756+ bars of OHLCV history per
  asset, which a fresh install lacks. It will be wired when enough history exists; enabling
  it prematurely would produce untrustworthy signals.

### Portfolio valuation (M8)

`/portfolio/summary`, `/exposure`, and `/concentration` are **marked to market** — holdings
are valued at the latest OHLCV close per symbol, USD assets converted to INR via the
`fx_rates` table. The valuation is **correctness-by-abstention**: any holding whose price
currency can't be resolved, or USD holding with no FX rate, falls back to cost basis (never
a wrong rupee figure). `/portfolio/marking` exposes the coverage (which symbols are
live-priced vs cost-basis, and why). `/portfolio/correlations` returns a real Pearson matrix
of daily log-returns from each symbol's own OHLCV history (currency-agnostic). See
`./CONTRACTS.md` for response shapes. Logic lives in `backend/pfip/portfolio/marking.py`.

---

## 2. Service topology (docker-compose)

Source of truth: `/infra/docker-compose.yml`. All services join the `pfip-net` bridge.

| Service         | Image                               | Host port | Purpose                                              |
| --------------- | ----------------------------------- | --------- | ---------------------------------------------------- |
| `timescaledb`   | `timescale/timescaledb:2.15.2-pg16` | 5432      | OHLCV hypertable, fundamentals PIT, portfolio ledger |
| `redis`         | `redis:7.2-alpine`                  | 6379      | Cache, rate-limiter tokens, Prefect queue transport  |
| `qdrant`        | `qdrant/qdrant:v1.9.3`              | 6333/6334 | KB + news embeddings                                 |
| `prefect`       | `prefecthq/prefect:2.19-python3.12` | 4200      | Scheduler + UI                                       |
| `mlflow`        | `ghcr.io/mlflow/mlflow:v2.14.0`     | 5000      | Model registry, metrics, artifacts                   |
| `ollama`        | `ollama/ollama:0.30.4`              | 11434     | Local LLMs: mistral-7b-instruct + nomic-embed-text   |
| `uptime-kuma`   | `louislam/uptime-kuma:1`            | 3001      | Per-service liveness dashboard                       |
| `backend`       | built from `../backend`             | 8000      | FastAPI + Prefect flows + LangGraph agent            |
| `frontend`      | built from `../frontend`            | 3000      | Next.js 14 dashboard (mobile-first)                  |

All host ports bind to `127.0.0.1` (loopback) — the compose file now enforces this
explicitly with `127.0.0.1:PORT:PORT` mappings, so nothing is published on `0.0.0.0`/the
LAN. Auth-critical secrets (`NEXTAUTH_SECRET`, `POSTGRES_PASSWORD`) are required via
`${VAR:?}` and compose aborts if they're unset. See `docs/SECURITY.md` for the full posture.

---

## 3. Data flow (ascii)

End-to-end: external source → ingest → features → signal → agent answer / UI.

```
[External sources]                [Ingest (M1)]                [Storage]
  Coinbase WS/REST     \                                        +----------------+
  yfinance / jugaad    --> Prefect flows  --normalize-->        | TimescaleDB    |
  FRED / RBI           /   (backend/pfip/ingest/*)              |  ohlcv         |
  NewsAPI / RSS        /                                        |  fundamentals  |
  Reddit / Bluesky    /                                         |  news_items    |
  Telegram channels  /                                          |  portfolio_tx  |
                                                                +-------+--------+
                                                                        |
                                                  [Features (M2)]      v
                                                  +----------------------------+
                                                  | feature builders (PIT)     |
                                                  | RSI, MACD, ATR, on-chain   |
                                                  +--------------+-------------+
                                                                 |
                  [Regime (M3)]        [Signals (M4)]            |
                  +--------------+     +------------------+      |
                  | HMM / rules  |<----| LightGBM / etc.  |<-----+
                  +------+-------+     +--------+---------+
                         |                      |
                         v                      v
                   +-----------+        +-----------------+
                   | Signal    |------->|  FastAPI        |
                   | contract  |        |  /api/v1/...    |
                   +-----------+        +--------+--------+
                                                 |
            [KB (M6)] ---Qdrant---+               |
                                   \              v
            [Agent (M7)] --LangGraph-+-->    +----------+
                                             | Next.js  |
                                             | frontend |
                                             +----+-----+
                                                  |
                                                  v
                                             Browser (mobile/desktop)

[Portfolio (M8)] and [Tax (M9)] read from ledger + Signal + market data, write back to
TimescaleDB; surface through FastAPI, consumed by frontend.
```

---

## 4. Tech stack reference

Detailed reasoning lives in plan **Section 11**. Quick summary:

- **Backend language:** Python 3.12 via `uv`.
- **API:** FastAPI + Pydantic v2.
- **ORM / migrations:** SQLAlchemy 2 + Alembic.
- **Scheduler:** Prefect 2.
- **ML:** scikit-learn, LightGBM, vectorbt, MLflow.
- **Agent:** LangGraph + LangChain tool calling over Ollama; Groq cloud fallback.
- **Vector DB:** Qdrant.
- **Cache/queue transport:** Redis 7.
- **Time-series DB:** TimescaleDB (Postgres 16 + hypertables).
- **Frontend:** Next.js 14 (app router), TypeScript, Tailwind, TanStack Query, NextAuth.
- **Charts:** Recharts + lightweight-charts.
- **Error tracking:** Sentry.
- **LLM tracing:** LangSmith.
- **Uptime:** Uptime Kuma.

---

## 5. Network diagram

```
                    +----------------------------------+
                    |         Windows host             |
                    |  (localhost bindings only)       |
                    |                                  |
                    |   Browser  ->  http://localhost  |
                    |              3000 / 8000 / 4200  |
                    |              5000 / 6333 / 3001  |
                    +--------+----------+--------------+
                             |          |
                             v          v
              +----- pfip-net (bridge) ----------------+
              |                                        |
              |  frontend:3000 <--> backend:8000       |
              |        \                /              |
              |         \              /               |
              |   timescaledb:5432  redis:6379         |
              |   qdrant:6333       ollama:11434       |
              |   prefect:4200      mlflow:5000        |
              |   uptime-kuma:3001                     |
              +----------------------------------------+

Outbound (to the public internet) comes ONLY from the backend and Prefect flows
hitting whitelisted data-source APIs. No inbound from the public internet.
If a VPS is added later, Tailscale creates a point-to-point tunnel; see SECURITY.md.
```
