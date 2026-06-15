# PFIP Overnight Run Log

Start: 2026-04-23 ~22:40 IST
Agent: Claude Opus 4.7 (Claude Code)
Budget: 6 hours wall-clock, stop by 06:00 IST

Format: timestamp — what changed — outcome. URLs cited inline when research drove a decision.

---

## 22:40 — Preflight & prior state

- User had already run `uv pip install -r backend/requirements.txt` into `backend/.venv` earlier in this session. That install hit a prefect/uvicorn conflict; fix already merged: `prefect==2.19.5` → `prefect>=2.20,<3` (user approved option 1). Install now succeeds; all 9 sanity imports green.
- Docker Desktop running; had 6 conflicting `opportunity_scraper-*` containers holding ports 3000 and 6379. Stopped (not removed) so PFIP can bind. Can be re-started later.
- `.env` exists with `NEXTAUTH_SECRET` and `PFIP_USER_PASSWORD_HASH` populated. Per §4 rail, treating as read-only.

## 22:45 — FIRST_RUN.ps1 attempt 1 — parse error

- PS 5.1 decoded the script's em-dashes as windows-1252, breaking string terminators. Rewrote file to UTF-8-with-BOM and replaced `—` with `-`. Non-semantic edit.

## 22:50 — FIRST_RUN.ps1 attempt 2 — docker build failure

Two real problems surfaced during backend image build:
1. **Docker build context = 1.63 GB** — root cause: `backend/.venv/` (~1.5 GB from the host install) was being shipped into the build context because no `.dockerignore` existed. Frontend had the same gap.
2. **`catboost==1.2.5` wheel download timeout** — `uv` default `UV_HTTP_TIMEOUT=30s` is too short for the ~350 MB catboost wheel on a flaky link.
3. **Compose warning** — `"TGiw16n8QJuldThSDXywIOE86Jtf0shQlfDK3llePYURr" variable is not set`. Root cause: NEXTAUTH_SECRET in `.env` contains a `$` followed by alphanumerics, which compose treats as `${VAR}` substitution. Can't edit `.env` per §4 — documenting only; will deal with NextAuth fallout at Tier 5 if it breaks login.

**Fixes applied:**
- Wrote [backend/.dockerignore](backend/.dockerignore) and [frontend/.dockerignore](frontend/.dockerignore).
- Set `UV_HTTP_TIMEOUT=600` in [backend/Dockerfile](backend/Dockerfile).

## 22:55 — Git snapshot

- `git init` (repo was not initialized), committed pre-overnight state.

---

# === OVERNIGHT RUN 2 — 2026-06-15 (Opus, autonomous ~5h) ===

## Phase 0 — Bootstrap (start ~22:40 UTC)

- **Branch discrepancy:** task body names `claude/amazing-noether-va818n`, but the
  environment is checked out on `claude/gallant-knuth-92qz1j` (the branch that
  exists on origin and matches the explicit Git Branch Requirements). Developing on
  `claude/gallant-knuth-92qz1j` and logging this. Will NOT push to a non-existent
  differently-named branch without permission.
- Tool versions: Python 3.11.15 (repo targets 3.12 — noting, not blocking),
  pip 24.0, Node v22.22.2, pnpm 10.33.0.
- `DATABASE_URL` set (Neon), `APP_ENV` set. `FEATURE_ML_SIGNALS` NOT set (correct — leave off).
- Frontend `pnpm install`: OK (exit 0, 753 pkgs).
- Backend `pip install -r requirements.txt`: running (large ML deps).

## Phase 0 result (~22:55 UTC)

- Backend install hit two real env-specific failures on this container:
  1. **Debian system-setuptools `install_layout` bug** broke legacy `setup.py`
     wheel builds for `ta`, `ebooklib==0.18`, `pyaes`, `sgmllib3k`. Fix: force
     PEP517 isolated builds (`PIP_USE_PEP517=1 --use-pep517`).
  2. **Debian-managed packages without RECORD** (PyJWT 2.7.0, wheel) blocked pip
     uninstall/upgrade. Fix: `--ignore-installed` on the full install.
  Final: `PIP_USE_PEP517=1 pip install --use-pep517 --ignore-installed -r requirements.txt`
  → exit 0, `pip check` clean, numpy 1.26.4 / pandas 2.2.2 pins intact.
  NOTE: GitHub Actions runners use clean Python 3.12 → none of these env bugs apply there.
- Frontend `pnpm install` exit 0.

## Phase 1 — Green build (~23:05 UTC)

- **Frontend**: `pnpm test` → 83 passed / 0 failed (4 files).
- **Backend**: `pytest` → **649 passed, 6 skipped, 0 failed** (RC 0).
- **CRITICAL SAFETY BUG FOUND + FIXED**: the real-DB integration suite
  (`tests/integration/`) TRUNCATEs `ohlcv, portfolio_tx, holdings, fx_rates`
  before each test and used whatever `DATABASE_URL` pointed at. Here
  `DATABASE_URL` is the **production Neon URL** — a plain `pytest` would have
  wiped live data had Neon been reachable. (It is NOT reachable from this
  sandbox: TCP to Neon:5432 times out — network policy blocks it — so the
  earlier run errored on connect and truncated nothing. Verified Neon data was
  never touched.) Fix: `tests/integration/_harness.py` now refuses to run the
  destructive suite unless `DATABASE_URL` is a localhost/throwaway host or
  `PFIP_ALLOW_DESTRUCTIVE_DB_TESTS=1` is set. CI is unaffected (it uses a
  localhost `services: postgres` container). Integration tests now SKIP cleanly
  here instead of hanging.
- Other Phase-1 fixes folded in (see Phase 4): `/assets/search` endpoint + the
  `_FakeResult.all()` test-shim it needs.

## Phase 3 note (blocker, found early)

- `alembic upgrade head` against $DATABASE_URL and direct Neon row-count queries
  CANNOT run from this sandbox — outbound to Neon:5432 is blocked by the network
  policy (TCP connect times out; DNS resolves to 13.251.17.193). Phase 3 will be
  driven entirely through GitHub Actions (the runner reaches Neon): the
  Backfill/Daily-ingest workflows run `alembic upgrade head` themselves.
