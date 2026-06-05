# Runbook — Telegram alerts not firing

## Symptom

`pfip.alerts.dispatcher.send_alert()` is called by morning brief / risk breach /
drawdown halt / ingest failure code paths but no message arrives on the
chat. Logs may show `Telegram disabled (missing TELEGRAM_BOT_TOKEN)` or
`alerts:silenced=1` in Redis.

## Diagnostic checklist

```powershell
# 1. Is the bot token + chat ID set?
docker exec pfip-backend python -c "from pfip.config import settings; print('token=',bool(settings.TELEGRAM_BOT_TOKEN),'chat=',settings.TELEGRAM_BOT_CHAT_ID)"

# 2. Is the silence flag set?
docker exec pfip-redis redis-cli GET alerts:silenced

# 3. Are we in quiet hours? (23:00–07:00 IST blocks INFO/WARN; CRITICAL still fires)
docker exec pfip-backend python -c "from datetime import datetime; from zoneinfo import ZoneInfo; print(datetime.now(ZoneInfo('Asia/Kolkata')).hour)"

# 4. Have we hit the rate cap? Default is 10/hour.
docker exec pfip-redis redis-cli ZRANGE alerts:ratecap 0 -1 WITHSCORES

# 5. Manual test send (bypasses dispatcher):
docker exec pfip-backend python -c "
import asyncio, os, httpx
async def main():
    tok=os.environ['TELEGRAM_BOT_TOKEN']; chat=os.environ['TELEGRAM_BOT_CHAT_ID']
    r=await httpx.AsyncClient().post(f'https://api.telegram.org/bot{tok}/sendMessage', json={'chat_id': chat, 'text': 'PFIP ping'})
    print(r.status_code, r.text)
asyncio.run(main())
"
```

## Common fixes

| Cause | Fix |
|---|---|
| Empty `TELEGRAM_BOT_TOKEN` in `.env` | Talk to @BotFather, paste token, `docker compose --env-file .env restart backend` |
| `TELEGRAM_BOT_CHAT_ID` wrong (negative for group) | Send `/start` to bot from target chat, hit `https://api.telegram.org/bot<TOKEN>/getUpdates`, copy `message.chat.id` |
| Rate cap hit (10/hour) | Wait, or `redis-cli DEL alerts:ratecap` to clear |
| Kill switch on | `docker exec pfip-redis redis-cli DEL alerts:silenced` |
| Quiet hours suppressing INFO | Expected; only `CRITICAL` ignores quiet hours |
| Bot blocked / not added to chat | Re-add bot, or send a message *to* the bot first to open the conversation |

## Prevention

- Use the dedicated PFIP Telegram account, not your personal one
  (avoids account-level flood-waits affecting all your messages).
- INFO alerts are intentionally rate-capped + digested — if you need
  every event, route through WARN severity.

## Related

- `backend/pfip/alerts/dispatcher.py` — dispatcher impl
- `backend/pfip/alerts/templates/*.md` — message bodies
- `docs/runbooks/telegram_flood_wait.md` — 429 / FloodWait handling
