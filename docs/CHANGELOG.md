# PFIP Changelog

The single source of truth for "what changed". Newest first. Dates are the day the
change landed. Grouped by Security / Correctness / Features / Docs / Known-state.

---

## 2026-06-04 — Security & correctness audit + two new portfolio features

A security/correctness audit pass plus two shipped features. Backend test suite is now
**477 tests: 471 passing, 1 skipped** (LightGBM not installed in the test env), 5 failing
**only** because `litellm` isn't installed in the local venv — it is pinned in
`backend/requirements.txt` and present in the Docker image, so the suite is green there.

### Security / config / deployment

- **Loopback-only ports.** Every host port in `infra/docker-compose.yml` is now bound to
  `127.0.0.1:PORT:PORT` (was implicitly `0.0.0.0`). Postgres (5432), Redis (6379), Qdrant
  (6333/6334), Prefect (4200), MLflow (5000), Ollama (11434), backend (8000), frontend
  (3000), and Uptime Kuma (3001) are no longer reachable from the LAN.
- **Fail-loud auth secrets.** Compose now uses `${NEXTAUTH_SECRET:?...}` and
  `${POSTGRES_PASSWORD:?...}`. The old fail-**open** defaults (`:-dev-change-me`,
  `:-pfip_dev`) were removed — a missing secret makes `docker compose` abort at startup
  instead of silently substituting a dev default.
- **Startup config validator.** `backend/pfip/core/config.py` now **raises** when
  `APP_ENV != "dev"` and any auth secret is still a default (empty/`dev-change-me`
  `NEXTAUTH_SECRET`, empty `PFIP_USER_PASSWORD_HASH`, or `DATABASE_URL` still containing
  `pfip:pfip_dev`). In dev it logs a loud warning instead.
- **Sentry actually wired.** `backend/pfip/api/main.py` initializes Sentry only when
  `SENTRY_DSN` is set (no-op otherwise). `sentry-sdk[fastapi]==2.7.1` pinned in
  `requirements.txt`. (Previously documented but not implemented.)
- **Global exception handler.** RFC-7807 `problem+json` responses; logs the full trace
  server-side and leaks nothing in the body.
- **Non-root containers + build targets.** `backend/Dockerfile` runs as `appuser` and adds
  multi-stage `prod`/`dev` targets (`dev` default with `--reload`; `prod` runs uvicorn
  without `--reload` and no bind-mount). `frontend/Dockerfile` adds `prod`/`dev` targets
  and drops the `|| pnpm install` fallback that defeated the lockfile.
- **Healthchecks** added to qdrant, prefect, mlflow, ollama, backend, frontend (previously
  only timescaledb/redis had them).
- **Pinned Ollama image** `ollama/ollama:0.30.4` (was `:latest`).
- **Frontend hardening.** Next.js bumped 14.2.5 → 14.2.35 (critical advisories — run
  `pnpm install` to apply). New `frontend/middleware.ts` enforces auth on all routes except
  `/login`, `/api/auth`, and static assets; `apiFetch` redirects to `/login` on 401.
  Security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP) added in
  `frontend/next.config.mjs`.
- **Auth on assets endpoints.** All 4 `/api/v1/assets/*` endpoints now require an
  authenticated user (were unauthenticated). `/tax/import` enforces a 10 MB upload cap and
  validates the broker against the known adapter registry.

### Privacy

- **Holdings never reach a cloud LLM.** The chat agent (`backend/pfip/agent/graph.py`) now
  feeds the user's open-holding symbols into the privacy classifier **and** structurally
  forces `SENSITIVE` whenever any holding row was retrieved into the prompt — so holdings
  stay local even on a classifier miss. The streaming call was switched to the
  sensitivity-routing `MultiProviderClient.stream`.

### Correctness fixes

- **`OHLCVRow.ts` AttributeError.** The model column is `time`; 11 sites referenced a
  non-existent `.ts`. Fixed with a SQLAlchemy synonym `ts = synonym("time")`. This unbroke
  `/tax/harvest`, `/changes-today`, the agent price tool, `market_close`, and 3 Prefect
  flows.
- **FX cost-basis** (`backend/pfip/tax/fx_cost_basis.py`) was silently broken under
  `AsyncSession`, used a blocking httpx call and a wrong static USD/INR table. Now
  async-correct, reads the dedicated `fx_rates` table via `prefetch_fx_rates`, and warns
  loudly on any fallback.
- **Tax FY filter pushed into SQL.** `/tax/summary` (and friends) no longer load full
  holdings + portfolio_tx history into Python.
- **Capital-gains FIFO** now sorts by full timestamp (was date-only → non-deterministic
  intraday lot assignment).
- **Calibration** in `signals/runner.py`: fixed a NaN-mask mismatch that silently disabled
  isotonic calibration.
- **`/health/deep`** now distinguishes CORE deps (TimescaleDB, Redis) from OPTIONAL
  (Qdrant, Ollama, cloud LLM). Status is `ok` / `degraded` (core ok, optional down) /
  `down` (core down), plus a `ready` boolean. A local run with Ollama down is now
  `degraded`, not `down`.
- **LLM timeout.** Calls use an explicit timeout (`llm_request_timeout_s`, default 120s) so
  a hung Ollama can't block the SSE stream forever.
- **Windows cp1252 crash.** 4 file-IO sites (`precommitment.py` read/write,
  `alerts/dispatcher.py`, `prefect/flows/annual_itr_drill.py`) now use `encoding="utf-8"` —
  the ₹ symbol previously crashed writes on Windows.
- **Dead idempotency code** (imported a non-existent model) removed from
  `ingest/_common/idempotency.py`.

### Features (shipped 2026-06-04)

- **`/portfolio/summary` is now real mark-to-market** (was cost-basis only): holdings are
  valued at the latest OHLCV close per symbol, USD assets converted to INR via the
  `fx_rates` table. Uses **correctness-by-abstention**: holdings whose price currency can't
  be unambiguously resolved, or USD holdings with no FX rate, fall back to cost basis (never
  a wrong rupee figure).
- **`/portfolio/exposure` and `/portfolio/concentration`** use the same live prices.
- **`/portfolio/correlations` is a real matrix** — Pearson correlation of daily log-returns
  from each symbol's own OHLCV history over the window (currency-agnostic). Response shape:
  `{ window_days, symbols: string[], matrix: number[][], note, disclaimer }`.
- **New endpoint `GET /portfolio/marking`** — mark-to-market coverage:
  `{ as_of, usdinr, marked, unmarked: [{symbol, reason}], mark_prices_inr, coverage: {marked, total}, disclaimer }`.
  Reasons: `no_price` / `unknown_currency` / `no_fx_rate`.
- **New module** `backend/pfip/portfolio/marking.py` (currency resolution + valuation +
  return series), with unit tests in `backend/tests/test_marking.py`.
- **Frontend.** 6 hooks that used `z.any()` now have real Zod schemas; drawdown risk-bar
  color aligned to the KPI severity scale; notification poll is now auth-gated and sends a
  bearer token; dead `/reset` link removed; dropdown menus got keyboard a11y
  (Escape/focus/roles); light-theme muted contrast raised.

### Docs

- New `docs/CHANGELOG.md` (this file).
- `docs/SECURITY.md` — loopback ports now compose-enforced, fail-loud secrets, assets auth,
  upload cap, security headers, non-root containers, Sentry wired.
- `docs/runbooks/compose_env_file_flag.md` and `docs/runbooks/postgres_password_mismatch.md`
  — updated for the new fail-loud `${VAR:?}` behavior (symptom is now "variable not set"
  abort, not "silently used the default").
- `docs/ARCHITECTURE.md` — MTM summary, real correlations, `/portfolio/marking`, Sentry
  wired, loopback ports, ML-layer status note.
- `docs/CONTRACTS.md` — `/portfolio/summary` (MTM), new `/portfolio/marking`, real
  `/portfolio/correlations` shape, `/health/deep` status model.
- `docs/LLM_ROUTING.md` — privacy hardening (holdings-symbol feed + structural SENSITIVE
  forcing); reranker still not wired into the live path.
- `BUILD_STATUS.md`, `README.md`, `docs/FEATURES.md`, `docs/PROJECT_HANDOFF.md` — audit
  fixes, new portfolio features, accurate ML status.

### Known state — ML / models layer (documented honestly)

- **Real & scheduled:** regime detection (HMM, BTC daily), backtesting (walk-forward +
  CPCV + Monte Carlo + shuffle test, BTC weekly), calibration (Brier/ECE + suspension
  rules, monthly), technical features (BTC via the legacy `compute_features_flow`).
  LightGBM model code (walk-forward, isotonic calibration, SHAP drivers) is implemented and
  correct.
- **Scaffolded but NOT deployed/wired:** the `signals_generate_daily` Prefect flow is not in
  the deployment, so the `signals` table stays empty and the daily shadow-reconcile reads
  nothing. The multi-asset `compute_features_daily` flow is also not deployed (only the
  legacy BTC-only features run).
- **`FEATURE_ML_SIGNALS`** config flag is defined but checked nowhere (dead; no
  stage-gating implemented).
- **Live signal generation is intentionally NOT enabled.** The walk-forward trainer needs
  ~3 years / 756+ bars of OHLCV history per asset, which a fresh install lacks. Enabling it
  prematurely would produce untrustworthy signals. It will be wired when sufficient data
  history exists.
