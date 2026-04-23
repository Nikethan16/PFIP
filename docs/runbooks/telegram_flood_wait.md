# Runbook — Telegram FloodWait (Telethon)

## Symptoms

- `ingest.news.telegram` flow fails with `telethon.errors.FloodWaitError: A wait of N
  seconds is required`.
- News sidebar stops updating Telegram-sourced headlines.
- Outbound alerts via `TELEGRAM_BOT_TOKEN` may also 429 if the bot is in the same
  rate-limit bucket.

## Diagnosis

1. Capture the wait duration from the error — Telegram is specific about it.
2. Identify the offending channel / action:
   - Joining channels too fast triggers the harshest FloodWaits.
   - `get_messages` on a firehose channel can exceed read limits.
3. Confirm the session file is still valid (not revoked):
   ```powershell
   docker exec -it pfip-backend uv run python -m pfip.ingest.telegram.diag
   ```

## Fix

### Primary

- Sleep the full requested duration; Telethon retries automatically if
  `flood_sleep_threshold` is raised. Set `TELEGRAM_FLOOD_SLEEP_THRESHOLD=300` in `.env`.
- Reduce concurrency: single worker on the Telegram flow, `TELEGRAM_READ_CHUNK_SIZE=50`.
- Spread channel polls across the hour: stagger schedules in `/schedules/`.

### Fallback

- Pause the Telegram ingest flow; other news sources (Reddit, RSS, GDELT, Bluesky)
  continue unaffected.
- For outbound alerts, switch transport to email/SMTP via SendGrid free tier while the
  bot cools down.

### Nuclear

- If the FloodWait is >24h, the account is at risk of a permanent limit. Stop all
  Telethon traffic for 48h. Do **not** log in again during that window or the timer
  resets.
- If the account was banned, you'll need a new dedicated Telegram account; see
  `docs/SECURITY.md` section 6.

## Prevention

- Never share the session with another process or host — spawning a second logged-in
  client triggers FloodWait immediately.
- Join no more than 3 channels per day; join slowly after account creation.
- Prefer channel public API (MTProto `ChannelParticipantsRecent` etc.) over scraping full
  history; cache and diff.
- Uptime Kuma: mark the Telegram flow non-critical so it doesn't page you on flood-wait.

## Last occurred

None yet (Stage 0 fresh install; ingest not wired to a real account).
