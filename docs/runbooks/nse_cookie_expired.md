# Runbook — NSE session / cookie expired (jugaad-data or nsepython)

## Symptoms

- Prefect task `ingest.equity.nse_daily` or `ingest.derivatives.nse_options` fails with
  HTTP 401/403, or responses are HTML instead of JSON.
- Error trace mentions `ValueError: Invalid JSON`, `requests.exceptions.HTTPError: 401`,
  or `nsepython.core.fetcher... Max retries exceeded`.
- Intra-day data is missing after a previously good morning run.

## Diagnosis

1. Confirm NSE is reachable at all:
   ```powershell
   docker exec -it pfip-backend curl -s -I https://www.nseindia.com/api/marketStatus
   ```
   A 200 with `Set-Cookie` header means NSE is up; a 403 means the bot-detection kicked in.
2. Inspect how many requests the flow has fired in the last minute — NSE throttles heavier
   than yfinance.
3. If using `nsepython`, check whether the user-agent string is still on NSE's allow
   list (changes silently every few months).

## Fix

### Primary

- Refresh the cookie jar. With `jugaad-data`:
  ```python
  from jugaad_data.nse import NSELive
  NSELive().stock_quote("INFY")  # triggers fresh handshake
  ```
- With `nsepython`: set `NSEPYTHON_USER_AGENT` in `.env` to a current Chrome UA string,
  restart backend.
- Sleep 30 seconds between symbol fetches; single-threaded only.

### Fallback

- Swap to BSE for the overlapping tickers (`BSE:500209` vs `NSE:INFY`) via `bsedata`.
- Use `yfinance` with the `.NS` suffix as a slower-moving substitute
  (`INFY.NS`) — lag of a few minutes but no cookie drama.

### Nuclear

- Route egress through an Indian VPN endpoint — NSE flat-blocks some overseas IPs.
- Disable the NSE adapter for the rest of the day; re-enable tomorrow after
  market open handshake.

## Prevention

- One-threaded NSE ingest only. Guard with a Redis lock key `pfip:nse:ingest:lock`.
- Daily cookie warm-up flow at 08:50 IST before market open.
- Pin `jugaad-data` and `nsepython` versions in `pyproject.toml`; quarterly review
  upstream CHANGELOG for user-agent string changes.

## Last occurred

None yet (Stage 0 fresh install).
