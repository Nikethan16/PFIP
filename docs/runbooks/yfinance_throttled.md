# Runbook — yfinance throttled / empty responses

## Symptoms

- Prefect task `ingest.equity.yfinance_daily` fails with HTTP 429 or returns an empty
  DataFrame for symbols that previously worked.
- Backend logs show `YFRateLimitError` or `json.decoder.JSONDecodeError: Expecting value`.
- `/api/v1/assets/{SYMBOL}/candles` returns stale data for Indian / US equities.

## Diagnosis

1. Check whether the issue is per-symbol or global:
   ```powershell
   docker exec -it pfip-backend uv run python -c "import yfinance as yf; print(yf.Ticker('AAPL').history(period='5d'))"
   ```
2. Inspect Prefect task logs for status codes. A burst of 429s means Yahoo has throttled
   the host IP; sporadic empty frames usually mean a single ticker was delisted or
   renamed (e.g. `FB` → `META`).
3. `curl -s -o /dev/null -w "%{http_code}\n" "https://query1.finance.yahoo.com/v7/finance/download/AAPL"` —
   a 429 at the raw endpoint confirms IP-level throttling.

## Fix

### Primary

- Space requests: set `YFINANCE_MIN_INTERVAL_SEC=1.5` in `.env`, restart backend. The
  adapter honours it via a token-bucket rate limiter.
- Chunk symbol list: ingest in batches of 10 with `asyncio.sleep(2)` between batches.
- Retry with exponential backoff (already wired; 3 attempts, base 5s).

### Fallback

- Flip the equity adapter to Stooq or Finnhub for the affected timeframe:
  ```powershell
  docker exec -it pfip-backend uv run python -m pfip.ingest.equity.stooq_daily --symbols AAPL,MSFT
  ```
- For Indian equities, switch to `jugaad-data` or `nsepython` (different upstream).

### Nuclear

- Rotate your egress IP (restart router, or route through a VPN) — yfinance throttling
  is IP-based and has no auth lever.
- Skip the day's ingest for that market; re-run tomorrow. Stored data stays valid.

## Prevention

- Keep `YFINANCE_MIN_INTERVAL_SEC` >= 1.0.
- Never run two yfinance ingests in parallel from the same host.
- Alert rule in Uptime Kuma on `ingest.equity.yfinance_daily` failing twice in a row.
- Long-term: subscribe to Tiingo or Finnhub premium once Stage 5 revenue justifies it.

## Last occurred

None yet (Stage 0 fresh install).
