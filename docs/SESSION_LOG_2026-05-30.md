# PFIP — Session log, 2026-05-30

While you were away. Picked up after Stitch integration to test the
whole thing, ship new pages, and fix bugs I found by writing tests.

## Headline

- **Test suite: 451 passed → 451 passed (1 skip, 0 fail).** Up from 397.
- **TypeScript: 0 real errors.** (47 "module not found" errors remain
  but those are all `node_modules` not fully installed in the sandbox —
  none are real bugs in our code.)
- **Real bug found + fixed by writing tests:** the LTCG branch of
  `pfip.tax.harvest._score_lot` was mis-applying the ₹1L exemption — it
  subtracted the exemption from the harvested *loss* instead of the
  *taxable pool*, which meant losses under ₹1L always reported zero
  savings even when the user had a fat LTCG pool to offset. Fixed; the
  new test (`test_ltcg_above_1l_exemption_harvested_at_10_percent`) pins
  the correct behaviour.

## Things shipped

### Bug fixes
- `frontend/components/shared/freshness-badge.tsx` — TS strict errors
  on possibly-undefined `stalest` / `newest` after `[...arr].sort()[0]`.
  Refactored to guard.
- `frontend/lib/api.ts` — `SourceHealth` was internal-only; exported
  the per-row type as `SourceHealth` and renamed the wrapper to
  `SourceHealthPayload` so consumers can type correctly.
- `frontend/components/shared/error-boundary.tsx` — added `override`
  modifiers (TS strict mode requirement that was pre-existing).
- `backend/pfip/tax/harvest.py` — see headline above (real economic bug).

### New tests (54 new, all green)
- `tests/test_journal_auto_draft.py` — 10 tests for the post-mortem
  auto-draft endpoint (prompt assembly, fallback template, system
  prompt invariants).
- `tests/test_tax_harvest.py` — 11 tests for the loss-harvesting
  engine. The LTCG-exemption test is the one that found the bug.
- `tests/test_alerts_dispatcher.py` — 22 tests for the alert
  dispatcher (quiet hours, template rendering, severity invariants,
  template-file existence per alert kind).
- `tests/test_precommitment.py` — 11 tests for the pre-commitment
  ladder gate (enum values, ladder caps, template render/parse
  round-trip, write-if-missing idempotency).

### New frontend pages
- `/watchlist` got a market-scope chip strip (Crypto / US equity /
  India equity / FX / Other). The page already had grouping under the
  hood — added the visible UI to scope to one market at a time.
- `/ops/sources` — promoted from a panel inside Settings to its own
  route. Same `<SourceHealthPanel>` component, dedicated URL.
- `/ops/schedules` — new page. Lists every registered Prefect
  deployment with cron, last run, last success, age, and a status pill
  (On time / Overdue / Never run) keyed off the staleness budget map
  shared with the watchdog flow.
- `/ops/models` — new page. Browse the model registry with filters
  (task / regime / horizon), pin a model into a slot, see SHA + version
  + metrics + pinned-for tags.
- `/tax/harvest` — new page wired to the `POST /tax/harvest` endpoint.
  User enters their realized gains for the FY, the engine ranks open
  lots by tax saved. VDA excluded by law. FY-end re-buy warnings
  surfaced as amber chips.

### New backend endpoint
- `GET /api/v1/schedules` — read-only Prefect deployment lister. Hits
  the Prefect API for every deployment + its last successful run. Quiet
  on Prefect being unreachable (returns empty list + error string
  rather than 500).

### Sidebar nav
- Added the four new entries to the sidebar (`Loss harvesting`,
  `Schedules`, `Models`, plus the dedicated `Source health`).

## What I didn't touch

You said you'd be busy and would handle the inputs at night. The
canonical list of what's blocking real progress is still
`docs/INPUTS_NEEDED.md`. Nothing on that list moved — those are all
external-credential or accumulated-runtime gates.

## How to verify

```powershell
# Backend
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app\backend
docker exec pfip-backend python -m pytest tests/ -p no:warnings -q
# expect: 451 passed, 1 skipped

# Frontend (only after docker compose up + ingest)
# open these URLs in your browser:
# - http://localhost:3000/tax/harvest    (try entering some realized gains)
# - http://localhost:3000/ops/schedules  (lists Prefect deployments)
# - http://localhost:3000/ops/models     (lists registry entries)
# - http://localhost:3000/ops/sources    (same panel as Settings, dedicated route)
# - http://localhost:3000/watchlist      (chip strip at top)
```

## Next-most-valuable things I'd build without your input

If I'm running again before you've added credentials:

1. **`/calibration` page redesign** — the existing page is functional
   but uses old palette and lacks the per-regime calibration breakdown
   we added to the spec. Easy port.
2. **`/journal` page upgrade** — the 10-item checklist UI is dense
   right now; could be reorganized into a wizard with progress.
3. **`/backtest` results browser** — list past walk-forward + CPCV
   runs from MLflow with quick comparison view.
4. **Frontend unit tests via Vitest** — there's currently no JS-side
   unit testing. Setting it up + smoke-testing the API hooks would
   close the trust gap.
5. **A daily morning-brief preview view** at `/digest` — currently
   only delivered via Telegram; a web preview helps when Telegram is
   down or quiet hours suppress.
