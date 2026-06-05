# How to test the frontend

Three paths, fastest first.

---

## Path 1 — Docker Compose (recommended)

This brings up **everything**: Postgres + Redis + Qdrant + Prefect +
MLflow + Ollama + Uptime Kuma + the FastAPI backend + the Next.js
frontend. ~30 seconds on a warm cache, ~3 minutes cold.

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app

# 1. Make sure your .env file exists (you already have one)
#    If not, copy .env.example to .env and fill in the password hash.
type .env | findstr POSTGRES_PASSWORD

# 2. Bring up the stack. The --env-file flag is required so docker
#    expands $POSTGRES_PASSWORD etc. in the compose file.
docker compose -f infra\docker-compose.yml --env-file .env up -d

# 3. Watch it come up. Wait for "compiled successfully" in the
#    frontend logs (Next.js dev server takes ~20s to warm).
docker compose -f infra\docker-compose.yml logs -f frontend
```

Then open:

- **http://localhost:3000** — the app. Welcome modal pops up on first load.
- **http://localhost:3000/login** — login page (creds from `.env`:
  `PFIP_USER_EMAIL` + the password whose bcrypt hash is in
  `PFIP_USER_PASSWORD_HASH`).
- **http://localhost:8000/api/v1/health** — backend liveness.
- **http://localhost:8000/docs** — FastAPI auto-generated API docs.

If you've never seeded data, the welcome modal will offer:
- **Bootstrap real data** — runs free ingest flows for ~3 minutes.
- **Seed demo data** — fills every page with synthetic data instantly.

---

## Path 2 — Frontend dev server only (fast iteration)

If the backend is already up (Path 1 worked once) and you just want
hot-reload on the frontend without rebuilding the container.

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app\frontend
npm install        # first run only; ~90 seconds
npm run dev
```

Frontend at **http://localhost:3000**. It expects the backend at
`http://localhost:8000`. If you don't have the backend running, log-in
will fail but most pages still render empty states.

You'll see hot-reload on every save.

---

## Path 3 — Pages that work without any backend

For pure visual QA of the redesign, every page renders its empty state
correctly with no API. Useful if you just want to see the new Slate &
Teal palette.

Pages worth checking (in priority order):

| URL | What you're checking |
|---|---|
| `/` | Sidebar branding, KPI strip with freshness dots, layout grid |
| `/watchlist` | Market-scope chip strip (Crypto / US equity / India / FX / Other) |
| `/signals` | Cards ↔ Table toggle in the top-right filter row |
| `/portfolio` | New Macro Shock Sensitivity card next to VaR |
| `/tax/harvest` | New harvesting page — try entering some realized gains and click Run |
| `/ops/sources` | Source health table with status badges + KPI tiles |
| `/ops/schedules` | Prefect deployment table — will show "Prefect not reachable" if backend down |
| `/ops/models` | Model registry browser with task/regime/horizon filters |
| `/journal` | 10-item Appendix B checklist dialog (click "New entry") |
| `/chat` | SSE-streaming chat agent (requires LLM key or local Ollama) |
| `/calibration` | Per-model reliability diagrams |
| `/settings` | All settings including the Source Health embed |

---

## What you should see (the visible changes from this session)

**Palette**: every page now uses the **Slate & Teal Institutional**
look. Light background `#f8f9ff`, teal primary `#006b5f`, sidebar in
white with teal accent stripe on the active item.

**Typography**: Inter for UI text, **JetBrains Mono** for every
numeric (prices, P&L, percents, dates). They're now tabular-aligned.

**Sidebar**: Brand reads "**PFIP Terminal** · INSTITUTIONAL GRADE".
Eight groups instead of four — Overview / Markets / Portfolio / Tax /
Tools / Operations / Settings.

**KPI tiles**: numbers now in teal mono with a small green/amber/red
freshness dot inline before each label.

---

## Known gotchas

1. **Welcome modal won't dismiss** if `setup/status.needs_setup` keeps
   returning `true`. After clicking Seed demo, refresh once.
2. **Postgres password mismatch** is the #1 first-run failure. If
   `pfip-backend` keeps restarting, see
   `docs/runbooks/postgres_password_mismatch.md`.
3. **TypeScript "Cannot find module 'next'"** in your editor is fine —
   it means `node_modules` hasn't been installed yet. Run
   `npm install` in `frontend/` once.
4. **Schedules page shows "Prefect not reachable"** until you've run
   `docker exec pfip-backend python -m pfip.prefect.deploy` once. That
   registers all the cron jobs.

---

## Browser DevTools quick-checks

Open the console on any page and try:

```javascript
// Force the welcome modal to re-show
localStorage.removeItem('pfip:welcome-dismissed'); location.reload();

// Inspect the source-health cache
JSON.parse(localStorage.getItem('REACT_QUERY_OFFLINE_CACHE') || '{}');

// Theme toggle is wired via class on <html>; check current mode
document.documentElement.classList.contains('dark');
```

---

## Reporting issues back

If something looks broken, the most useful thing you can send is:

1. The URL (`/dashboard`, `/tax/harvest`, etc.).
2. A screenshot of the broken view.
3. Whatever's in the browser console (DevTools → Console tab).
4. The relevant lines from `docker compose -f infra\docker-compose.yml logs frontend` if it's a server-side error.

That's enough for me to fix in one round-trip.
