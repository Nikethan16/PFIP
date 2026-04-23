# Morning Checklist

When you wake up and want to see what the agent accomplished overnight.

## 60-second scan

1. Open `MORNING_REPORT.md` (the agent writes this before stopping).
2. Open `OVERNIGHT_LOG.md` — scan for red/fail lines.
3. Check what's running: PowerShell → `docker ps`. You should see ~9 containers up.
4. Hit http://localhost:3000 — log in with `suresh.sahoo@cbcinc.ai` / `pfip-local-2026`. You should see BTC chart with real data.

## If something's wrong

- Agent stopped early → read the last section of `OVERNIGHT_LOG.md`, it'll say why.
- Containers not running → `.\scripts\up.ps1` to bring them back.
- Docker ran out of disk → `docker system prune -a` (safe; removes unused images only).
- Laptop restarted mid-way (Windows Update) → everything in `docker volume ls` is preserved; just run `.\scripts\up.ps1`.

## Travel mode

If you're hitting the road:
- Leave the machine plugged in and connected to Wi-Fi — Prefect schedules will keep running daily ingest even without you.
- Or shut it down with `.\scripts\down.ps1` — data is preserved in Docker volumes, just start again when you're back.

## When back at the keyboard

Priorities for your next session:
1. Read `MORNING_REPORT.md` top-to-bottom.
2. Anything marked "needs user decision" — answer those.
3. If you have broker CSVs handy, drop them in via the Tax page (http://localhost:3000/tax).
4. Run the tax engine against last year's actuals to calibrate (Stage 5 gate in the plan).
