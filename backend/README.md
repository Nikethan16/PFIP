# PFIP Backend

FastAPI + Prefect + SQLAlchemy 2 + Alembic + Pydantic v2.
Python 3.12, managed by `uv`.

## Dev commands

Everything is expected to run inside the `pfip-backend` container from the
`infra/docker-compose.yml` in the repo root. Commands below assume you are in
the repo root (`PFIP_app/`).

### Bring the stack up

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d backend
```

### Hit the API

- http://localhost:8000/docs — OpenAPI UI
- http://localhost:8000/api/v1/health — liveness
- http://localhost:8000/api/v1/health/deep — DB/Redis/Qdrant/Ollama pings

### Run Alembic migrations

```bash
docker exec -it pfip-backend alembic upgrade head
```

### Run the BTC ingest flow once (manual trigger)

```bash
docker exec -it pfip-backend python -m pfip.prefect.flows.ingest_btc_daily
```

### Register Prefect deployments

```bash
docker exec -it pfip-backend python -m pfip.prefect.deploy
```

### Tests

```bash
docker exec -it pfip-backend pytest -q
```

### Create the password hash

```bash
docker exec -it pfip-backend python scripts/make_password_hash.py
```

## Layout

```
pfip/
  api/          FastAPI routers + app
  core/         config, contracts (Pydantic), logging
  db/           SQLAlchemy async engine, base
  models/       ORM tables (mirrors CONTRACTS.md)
  ingest/       Data source adapters (ccxt for now)
  features/     Feature engineering (pandas-ta)
  prefect/      Prefect flows + deployment script
  agent/        LangGraph agent + prompts + morning brief
  portfolio/    Risk manager
  signals/      (Stage 4 — empty)
  backtest/     (Stage 4 — empty)
  kb/           (Stage 3 — empty)
  tax/          (Stage 5 — empty)
  brokers/      (Stage 7+ — empty)
alembic/        Migrations
scripts/        One-off dev tools
tests/          pytest suite
```

## Stubbed vs. working

- **Working end-to-end**: health checks, auth (JWT), watchlist CRUD,
  journal CRUD, OHLCV/feature/regime/news/FX ingest, feature computation,
  portfolio holdings + CSV import + mark-to-market, tax (harvest, Schedule FA,
  Form 67), shadow portfolio, calibration, signals, agent chat SSE, and the
  `/assets/search` ticker lookup. (The earlier "Stubbed (501)" list was stale —
  all of these are implemented.)
- **Known gaps** (not 501 — see `../PLACEHOLDERS.md`): broker *live-trading*
  adapters (`pfip/brokers/` is CSV-import only), the paper→live Sharpe-floor
  gate in `pfip/portfolio/precommitment.py` (no-op pending the Stage 4
  calibration module), and `FEATURE_ML_SIGNALS` (kept off until calibrated).
