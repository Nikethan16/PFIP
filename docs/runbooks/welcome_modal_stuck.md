# Runbook — Welcome modal won't dismiss / keeps coming back

## Symptom

The first-run welcome modal (`frontend/components/shared/welcome-modal.tsx`)
reappears on every dashboard load even after the user clicked **Dismiss** or
finished **Seed demo data**.

## Root cause

The modal's visibility is the AND of two conditions:

1. `localStorage["pfip:welcome-dismissed"] !== "1"`
2. `GET /api/v1/setup/status` returned `needs_setup === true`

`needs_setup` is `true` whenever **all** of the following are empty:

- `watchlist` table
- `holdings` table
- `signals` table from the last 7 days
- `ohlcv` table from the last 24 hours

If any of those is still empty *after* clicking "Seed demo" the modal will
keep showing — typically because the demo seed failed silently or the
backend container was restarted before the rows committed.

## Fix

```powershell
# 1. Check what setup status actually says
curl -sS http://localhost:8000/api/v1/setup/status | jq

# 2. If `needs_setup: true` but you already ran demo seed, re-run it:
docker exec pfip-backend python -m pfip.scripts.seed_demo

# 3. If you've started ingesting real data and just want to dismiss
#    the modal, open browser DevTools console:
localStorage.setItem('pfip:welcome-dismissed', '1');
location.reload();

# 4. If `setup/status` itself is 500ing, check the backend logs:
docker logs pfip-backend --tail 200 | grep -iE "setup|status"
```

## Prevention

The status endpoint is intentionally permissive — it tolerates partial
seeds. If you want to test that the modal *does* show, clear the dismiss
key in DevTools and clear demo data via `DELETE /api/v1/setup/demo`.

## Related

- `docs/runbooks/source_health_ambiguous_param.md` — if `setup/status`
  itself errors due to a SQL cast issue
- `backend/pfip/api/setup.py` — endpoint impl
- `backend/pfip/scripts/seed_demo.py` — synthetic seed
