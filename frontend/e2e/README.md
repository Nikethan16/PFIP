# PFIP end-to-end tests (Playwright)

Drives a real browser against the app **as a logged-in user**, sweeps every
page, runs a few interaction flows, and **flags what's broken** — failed API
calls, "data not loading" (backend shape drift), JS crashes, and unexpected
logouts. Screenshots of every page land in the HTML report so you can also
eyeball "this looks empty/wrong".

By default it runs against the **live VM** (`https://apps.tail1d9a60.ts.net:8443`).

## One-time setup

```bash
cd frontend
pnpm install                      # picks up @playwright/test
pnpm exec playwright install chromium
cp e2e/.env.example e2e/.env.local   # then edit e2e/.env.local with your creds
```

`e2e/.env.local` (gitignored):

```
PFIP_E2E_EMAIL=srinikethan9@gmail.com
PFIP_E2E_PASSWORD=********
# PFIP_E2E_BASE_URL=https://apps.tail1d9a60.ts.net:8443   # default
# PFIP_E2E_BASE_URL=http://localhost:3000                 # local dev instead
```

## Run

```bash
pnpm test:e2e            # headless sweep + interactions
pnpm test:e2e:headed     # watch it drive the browser
pnpm test:e2e:ui         # Playwright's interactive runner (great for debugging)
pnpm test:e2e:report     # open the last HTML report (screenshots, traces)
```

## What you get

- **`e2e/report/FINDINGS.md`** — a one-glance list of problems per page: which
  API call failed (status + path), which page had a data/schema mismatch, which
  threw a JS error. Printed to the console at the end of every run too.
- **`e2e/report/html/`** — the full Playwright HTML report: every page's
  screenshot, plus traces for any failure (time-travel through the run).

## What it checks

| Check | How | Severity |
|-------|-----|----------|
| Page returns a non-error document | navigation status `< 400` | ❌ fail |
| Not bounced to `/login` | URL assertion | ❌ fail |
| No failed backend calls | listens for `/api/v1/*` responses `>= 400` | ❌ fail |
| **Data actually loaded** | catches the API client's `[apiFetch] schema validation failed` console error | ❌ fail |
| No uncaught JS errors | `pageerror` listener | ❌ fail |
| Other console errors | `console.error` (minus a benign allowlist) | ⚠️ reported |

Interaction flows (all non-destructive on live data):

- **Goals** — runs a Monte-Carlo projection, asserts the result renders.
- **Chat** — asks the agent one question, asserts a streamed answer (real LLM call).
- **Portfolio import** — a **dry-run** CSV preview (`dry_run=true`, nothing persisted).

## Extending

- **Add a page:** append to `ROUTES` in `e2e/smoke.spec.ts`.
- **Add a flow:** drop a test in `e2e/interactions.spec.ts` using the `issues`
  fixture so failures get aggregated into FINDINGS.md.
- **Silence benign console noise:** add a substring to `BENIGN_CONSOLE` in
  `e2e/fixtures.ts`.
- **CI:** set `PFIP_E2E_EMAIL` / `PFIP_E2E_PASSWORD` as secrets and run
  `pnpm test:e2e` — `workers=1`, `retries=1` are already configured for CI.
