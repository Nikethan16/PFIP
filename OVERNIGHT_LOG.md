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
