# PFIP Contracts

Canonical contracts that both backend and frontend must implement identically. Any change here propagates to both sides. Backend owns Pydantic definitions (`/backend/pfip/core/contracts.py`); frontend mirrors them as TypeScript (`/frontend/lib/contracts.ts`).

---

## 1. Core Enums

### Market
```
BTC_USD | ETH_USD | SOL_USD | BNB_USD        # crypto
SPY | QQQ | DIA | VTI                         # US ETFs + any ticker
NIFTY50 | NIFTY500 | SENSEX | any .NS/.BO     # Indian
USDINR | EURUSD | GBPUSD                      # FX
```

### Source
`coinbase | kraken | bybit | okx | yfinance | stooq | jugaad | amfi | frankfurter | rbi | fred | sec_edgar`

### Regime
`bull_trend | bear_trend | sideways | high_volatility | accumulation | distribution`

### HoldingCategory
`equity | etf | mutual_fund | ppf | epf | nps | fd | sgb | gsec | bond | crypto_exchange | crypto_self_custody | cash`

### SignalDirection
`BUY | HOLD | SELL`

---

## 2. Typed Signal Contract (the seam between M4 and M7)

```python
class Signal(BaseModel):
    direction: SignalDirection
    confidence: int  # 0–100
    horizon_hours: int
    drivers: list[Driver]           # top 5 supporting
    counter_arguments: list[Driver]  # top 3 against
    regime: Regime
    model_name: str
    model_version: str
    asset: str  # e.g. "BTC-USD"
    generated_at: datetime  # UTC
```

```python
class Driver(BaseModel):
    feature: str
    contribution: float  # SHAP value or equivalent
```

The agent (M7) reads signals but cannot mutate them. Validation is strict; unknown fields rejected.

---

## 3. OHLCV Row (stored in TimescaleDB hypertable)

```sql
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT         NOT NULL,
    market      TEXT         NOT NULL,
    source      TEXT         NOT NULL,
    timeframe   TEXT         NOT NULL,   -- '1m' | '5m' | '1h' | '1d'
    open        NUMERIC(20, 8) NOT NULL,
    high        NUMERIC(20, 8) NOT NULL,
    low         NUMERIC(20, 8) NOT NULL,
    close       NUMERIC(20, 8) NOT NULL,
    volume      NUMERIC(30, 8) NOT NULL,
    PRIMARY KEY (time, symbol, source, timeframe)
);
SELECT create_hypertable('ohlcv', 'time');
```

---

## 4. Fundamentals Row (PIT-aware, per Section 4.6)

```sql
CREATE TABLE fundamentals (
    as_of_date  DATE NOT NULL,     -- date data was first available
    report_date DATE NOT NULL,     -- period the data covers
    symbol      TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       NUMERIC,
    source      TEXT NOT NULL,
    PRIMARY KEY (as_of_date, symbol, field, source)
);
```

Queries MUST filter `as_of_date <= point_in_time_t`. Restatements stored as new rows, not overwrites.

---

## 5. Portfolio Ledger

```sql
CREATE TABLE holdings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        TEXT NOT NULL,          -- HoldingCategory enum
    symbol          TEXT,
    isin            TEXT,
    broker          TEXT,
    account_id      TEXT,
    acquired_at     TIMESTAMPTZ NOT NULL,
    qty             NUMERIC NOT NULL,
    cost_basis_inr  NUMERIC NOT NULL,
    cost_basis_ccy  TEXT DEFAULT 'INR',
    fx_rate         NUMERIC,                 -- for US stocks etc
    is_self_custody BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    closed_at       TIMESTAMPTZ,
    exit_price_inr  NUMERIC
);

CREATE TABLE portfolio_tx (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    holding_id   UUID REFERENCES holdings(id),
    time         TIMESTAMPTZ NOT NULL,
    kind         TEXT NOT NULL,   -- BUY | SELL | DIVIDEND | INTEREST | TRANSFER | FEE | TDS
    qty          NUMERIC,
    price        NUMERIC,
    amount_inr   NUMERIC NOT NULL,
    fx_rate      NUMERIC,
    tax_withheld NUMERIC DEFAULT 0,
    note         TEXT
);
```

The `shadow_portfolio_ledger` is a mirror of the above schema; identical columns, separate table name.

---

## 6. REST API Routes (FastAPI)

All routes are prefixed `/api/v1`.

### Health
- `GET /health` → `{ "status": "ok", "time": "..." }`
- `GET /health/deep` → checks CORE deps (TimescaleDB, Redis) + OPTIONAL deps (Qdrant,
  Ollama, cloud LLM). Returns `{ status, ready, ... }` where `status` is `"ok"` (all up) /
  `"degraded"` (core up, an optional dep down — e.g. Ollama offline on a local run) /
  `"down"` (a core dep down), and `ready` is a boolean.

### Auth
- `POST /auth/login` → `{ token, expiresAt }`
- `POST /auth/refresh`
- `GET /auth/me` → current user

### Assets & market data

All `/assets/*` endpoints require an authenticated user. The three below were stubs (`501`)
until 2026-06-04 and are now **real**.

- `GET /assets/{symbol}/candles?timeframe=1d&since=ISO&until=ISO` → `OHLCV[]`
- `GET /assets/{symbol}/features?as_of=ISO` → the **latest** feature row for the symbol (a
  feature dict). Empty when none exists.
- `GET /assets/{symbol}/news?since=ISO&limit=50` → recent `NewsItem[]`, **newest first**,
  capped by `limit`. Items use `time` and `symbol` (the frontend mirrors these field names —
  not `published_at` / `tickers`).
- `GET /assets/{symbol}/regime` → `{ regime, since, confidence }` with the **latest** regime
  label. Returns `{ "regime": "unknown" }` when no regime has been computed for the symbol
  (the frontend tolerates `"unknown"`).

### Watchlist
- `GET /watchlist` → `WatchlistItem[]`
- `POST /watchlist` → add
- `DELETE /watchlist/{id}`

### Signals
- `GET /signals?asset=BTC-USD&since=ISO` → `Signal[]`
- `GET /signals/latest` → most recent per asset

### Portfolio
- `GET /portfolio/holdings` → `Holding[]`
- `POST /portfolio/holdings` → add manual
- `POST /portfolio/import` (multipart CSV) → { imported, rejected, errors }
- `GET /portfolio/summary` → { total_inr, p&l, exposure_by_category, drawdown, ... }
  **Marked to market:** holdings valued at the latest OHLCV close per symbol, USD assets
  converted to INR via the `fx_rates` table. Correctness-by-abstention — any holding whose
  price currency can't be resolved, or USD holding with no FX rate, falls back to cost basis
  (never a wrong rupee figure). `/portfolio/exposure` and `/portfolio/concentration` use the
  same live prices. **`drawdown` is now real** (2026-06-04): peak-to-current drawdown computed
  from a NAV-history proxy — cumulative net-flow from the `portfolio_tx` ledger (no dedicated
  NAV table exists). Was previously hardcoded `0`.
- `GET /portfolio/marking` → mark-to-market coverage:
  ```
  {
    "as_of": "2026-06-04T00:00:00Z" | null,
    "usdinr": "83.21" | null,                 // string-encoded Decimal
    "marked": string[],                        // symbols priced live
    "unmarked": [{ "symbol": "...", "reason": "no_price" | "unknown_currency" | "no_fx_rate" }],
    "mark_prices_inr": { "<symbol>": "<inr price, string Decimal>" },
    "coverage": { "marked": int, "total": int },
    "disclaimer": "..."
  }
  ```
- `GET /portfolio/correlations?window_days=90` → real Pearson correlation matrix of daily
  log-returns from each symbol's own OHLCV history over the window (currency-agnostic, no FX
  involved). `window_days` is clamped to 10–365. Response shape (matches the frontend
  `CorrelationMatrixSchema`):
  ```
  {
    "window_days": 90,
    "symbols": string[],          // row/column order
    "matrix": number[][],         // aligned to `symbols`; symbols with <2 bars dropped
    "note": "...",                // explains an empty matrix when no holding has history
    "disclaimer": "..."
  }
  ```

### Shadow portfolio
- `GET /shadow/holdings`
- `GET /shadow/vs-actual` → compared metrics

### Calibration
- `GET /calibration/latest` → Brier/ECE/reliability per model

### Tax
- `GET /tax/summary?fy=2026-27`
- `GET /tax/schedule-fa?fy=2026-27`
- `GET /tax/form-67?fy=2026-27`
- `POST /tax/import/{broker}` (CSV)

### Agent / chat
- `POST /agent/chat` (SSE streaming) → token stream
- `GET /agent/morning-brief?date=YYYY-MM-DD` → rendered markdown

### Journal
- `GET /journal/entries`
- `POST /journal/entries` (with pre-trade checklist required)
- `POST /journal/entries/{id}/close` (post-mortem required)

---

## 7. SSE Streaming Format

For `/agent/chat` and `/signals/stream`:

```
event: token
data: {"text": "..."}

event: source
data: {"type": "kb" | "news" | "db", "id": "...", "title": "..."}

event: signal
data: { ...Signal object... }

event: done
data: {}
```

---

## 8. Error Format (RFC 7807 style)

```json
{
  "type": "about:blank",
  "title": "Validation failed",
  "status": 422,
  "detail": "...",
  "instance": "/api/v1/..."
}
```

---

## 9. Time Handling

All timestamps in DB: `TIMESTAMPTZ`, stored as UTC.
All API responses: ISO-8601 with timezone (`2026-04-21T10:30:00Z`).
Frontend renders in IST by default (`Asia/Kolkata`), user-configurable later.
