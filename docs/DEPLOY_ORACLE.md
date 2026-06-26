# PFIP Deployment Runbook — Oracle ARM VM

> Deploy **PFIP** (3rd app) onto an existing Oracle ARM VM that already runs two apps,
> **without touching the running apps**. Code comes from GitHub; secrets (`.env`) come from your laptop.
>
> This runbook has the repo's real entrypoints already filled in and four hosting-specific
> corrections baked in (backend `.env` location, pnpm, frontend build-time env, alembic). Follow it
> top to bottom.

## The VM (already provisioned)
- Public IP: **140.245.226.147**, SSH user: **ubuntu**, OS: Ubuntu 24.04 ARM64 (2 OCPU / 12 GB)
- Connect: `ssh -i $ORACLE_KEY -o ServerAliveInterval=60 ubuntu@140.245.226.147`
- Python **3.12.3** and Node **20.20.2** already installed.
- Redis already running on `127.0.0.1:6379` (shared) — PFIP uses logical **DB 1**.
- Already running (**DO NOT DISTURB**): OPPs Finder (8801/8802), Agent_System (8800), GitHub Actions runner.

## Locked decisions
- **Database: Neon** (external). PFIP's `DATABASE_URL` points at Neon. Do **not** self-host Postgres.
- **Redis: share the existing instance**, logical DB 1 → `REDIS_URL=redis://127.0.0.1:6379/1`.
- **Run via systemd + venv** (NOT Docker) — match the other two apps.
- **Ports:** backend **8000**, frontend **3000**.
- Add **4 GB swap** before starting (OOM safety for the daily pipeline).
- Daily pipeline runs as a **systemd timer**, `MemoryMax=2500M`, off-peak, not overlapping CI builds.

## Repo entrypoints (resolved)
| Thing | Value |
|---|---|
| Backend dir | `backend` |
| Backend ASGI app | `pfip.api.main:app` |
| Frontend dir | `frontend` (package manager: **pnpm 9.6.0**) |
| Pipeline entrypoint | `python -m scripts.run_daily_pipeline` (run from `backend/`) |
| Migrations | Alembic, 9 revisions; `alembic upgrade head` from `backend/` (reads `DATABASE_URL`) |
| Deploy branch | **`main`** |

---

## PREREQUISITES (on the laptop)
1. Oracle VM SSH key on the laptop, e.g. `~/oracle_key`; `chmod 600 ~/oracle_key`; `export ORACLE_KEY=~/oracle_key`.
2. The PFIP repo with its working **`.env`**. Note its path (`<path-to-PFIP>`).

---

## PHASE 0 — Push latest PFIP code (laptop)
```bash
cd <path-to-PFIP>
git status            # must be clean
git push origin main  # deploy from main
```

## PHASE 1 — Add swap (VM, one-time)
```bash
ssh -i $ORACLE_KEY ubuntu@140.245.226.147
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf
free -h      # confirm 4G swap present
```

## PHASE 2 — Clone PFIP (VM)
```bash
git clone git@github.com:Nikethan16/PFIP.git ~/pfip
cd ~/pfip   # defaults to main — no branch checkout needed
```

## PHASE 3 — Copy secrets from laptop to VM

### 3a. Backend `.env` → **must land in `backend/`** (CORRECTION 1)
The backend loads config via pydantic `env_file=".env"`, resolved **relative to the working
directory**. The API service runs with `WorkingDirectory=…/pfip/backend` (required — the `pfip`
package lives under `backend/`), so the file must be at `~/pfip/backend/.env`:

```bash
# run on the LAPTOP:
scp -i $ORACLE_KEY <path-to-PFIP>/.env ubuntu@140.245.226.147:~/pfip/backend/.env
```
Then on the VM, edit `~/pfip/backend/.env`:
- Set `REDIS_URL=redis://127.0.0.1:6379/1`
- Confirm `DATABASE_URL` is the **Neon** string with `?sslmode=require`, and that it has **no
  `&hostaddr=...` pin** (that's a Windows-only DNS workaround; the IP would be stale on the VM).

### 3b. Frontend `.env.local` (CORRECTION 3)
The frontend reads `frontend/.env.local` (NOT the root `.env`). `NEXT_PUBLIC_API_URL` is **compiled
in at build time**, so it must be a URL the **browser** can reach. Create `~/pfip/frontend/.env.local`:

```bash
cat > ~/pfip/frontend/.env.local <<'EOF'
NEXT_PUBLIC_API_URL=http://140.245.226.147:8000/api/v1
BACKEND_URL=http://127.0.0.1:8000
NEXTAUTH_URL=http://140.245.226.147:3000
NEXTAUTH_SECRET=PASTE_SAME_VALUE_AS_BACKEND_NEXTAUTH_SECRET
EOF
```
⚠️ `NEXTAUTH_SECRET` **must equal** the backend's (`NEXTAUTH_SECRET` in `~/pfip/backend/.env`) — the
backend verifies the JWT signed with it. If you'll reach the app over Tailscale instead of the public
IP, use the MagicDNS name in `NEXT_PUBLIC_API_URL` and `NEXTAUTH_URL`.

## PHASE 4 — Build (VM)

### Backend
```bash
cd ~/pfip/backend
python3.12 -m venv .venv
./.venv/bin/pip install --upgrade pip wheel
./.venv/bin/pip install -r requirements.txt    # ARM wheels; compiles cleanly
./.venv/bin/alembic upgrade head                # no-op if Neon already at head; safe
```
> Note: the venv lives at `~/pfip/backend/.venv` (created from inside `backend/`). The unit files
> below reference that path.

### Frontend — **pnpm, not npm** (CORRECTION 2)
```bash
cd ~/pfip/frontend
corepack enable && corepack prepare pnpm@9.6.0 --activate
pnpm install --frozen-lockfile
pnpm build
```

## PHASE 5 — systemd units (VM)

`/etc/systemd/system/pfip-api.service`
```ini
[Unit]
Description=PFIP API (FastAPI / uvicorn)
After=network-online.target redis-server.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/pfip/backend
Environment=PYTHONPATH=/home/ubuntu/pfip/backend
ExecStart=/home/ubuntu/pfip/backend/.venv/bin/uvicorn pfip.api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3
MemoryMax=1G

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/pfip-web.service`
```ini
[Unit]
Description=PFIP web (Next.js)
After=network-online.target pfip-api.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/pfip/frontend
Environment=NODE_ENV=production
ExecStart=/home/ubuntu/pfip/frontend/node_modules/.bin/next start -p 3000
Restart=on-failure
RestartSec=3
MemoryMax=600M

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/pfip-pipeline.service` (oneshot, run by timer)
```ini
[Unit]
Description=PFIP daily pipeline (ingest->features->regime->signals)
After=network-online.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/pfip/backend
Environment=PYTHONPATH=/home/ubuntu/pfip/backend
ExecStart=/home/ubuntu/pfip/backend/.venv/bin/python -m scripts.run_daily_pipeline
MemoryMax=2500M
TimeoutStartSec=2400
```

`/etc/systemd/system/pfip-pipeline.timer`
```ini
[Unit]
Description=Run PFIP pipeline daily (off-peak)

[Timer]
# 02:30 UTC = 08:00 IST. Must NOT overlap CI runner builds.
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

## PHASE 6 — Start & enable (VM)
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pfip-api pfip-web
sudo systemctl enable --now pfip-pipeline.timer
sudo systemctl status pfip-api pfip-web --no-pager
```

## PHASE 7 — Verify (VM)
```bash
systemctl is-active pfip-api pfip-web
sudo ss -tlnp | grep -E ':8000|:3000'
curl -fsS http://127.0.0.1:8000/api/v1/health && echo OK
journalctl -u pfip-api -n 40 --no-pager
journalctl -u pfip-web -n 40 --no-pager
free -h
# optional pipeline dry-run (watch peak RAM):
sudo systemctl start pfip-pipeline.service && journalctl -u pfip-pipeline -f
```

## ACCESS
- API: `http://140.245.226.147:8000`  Web: `http://140.245.226.147:3000` (or over Tailscale).
- These bind `0.0.0.0`. To keep them private (as the architecture intends), reach them over
  Tailscale and/or restrict with the firewall — do not open Oracle security-list ingress unless you
  deliberately want public access.

## SUCCESS CRITERIA
- `pfip-api` + `pfip-web` active; ports 8000/3000 listening; `/api/v1/health` returns 200; logs clean.
- `free -h`: several GB still free at steady state (~3 GB used across all 3 apps).
- Pipeline run peaks under ~2.5 GB and completes; no other service OOM-killed.
- OPPs Finder (8801/8802) and Agent_System (8800) still running untouched.

## IF SOMETHING'S WRONG — collect:
`free -h`, `systemctl status pfip-*`, and the failing `journalctl -u pfip-* -n 80 --no-pager`.

## Common gotchas (mapped to the corrections)
- **Backend 500s / "field required" on boot** → `.env` not found: it must be at `~/pfip/backend/.env`
  (Correction 1), not the repo root.
- **`pnpm: not found` / lockfile errors** → use pnpm via corepack, not npm (Correction 2).
- **UI loads but every API call fails in the browser** → `NEXT_PUBLIC_API_URL` was baked as
  `localhost` at build; rebuild with the VM/Tailscale URL (Correction 3).
- **Login/session fails** → frontend and backend `NEXTAUTH_SECRET` don't match (Correction 3).

## Backup / restore (managed Postgres + TimescaleDB)

The prod DB has the **timescaledb** extension (2 hypertables), so restores need a
timescaledb-enabled target — a naive `pg_restore` into vanilla Postgres won't work.

**Backups (automated):** `backend/scripts/backup_neon.sh` runs daily via the
`pfip-backup.timer` systemd timer (**03:30 UTC**, ~1h after the pipeline). It `pg_dump`s
`DATABASE_URL` in compressed custom format to `~/pfip-backups/pfip-<ts>.dump`, verifies the
archive (`pg_restore --list` must show objects), and keeps the newest **14**. Uses the
**pg_dump v18** client (`/usr/lib/postgresql/18/bin`, from the PGDG apt repo) — must be ≥ the
server version (Neon is PG 18). Run on demand: `bash backend/scripts/backup_neon.sh`.
Each dump is ~3 MB (DB ~74 MB). Tune via `PFIP_BACKUP_DIR` / `PFIP_BACKUP_KEEP`.
**Offsite (recommended):** also push dumps to Oracle Object Storage / another host so a VM
loss doesn't lose them.

**Restore (drill or real) — into a timescaledb-enabled target:**
```bash
# 1) target server must have timescaledb in shared_preload_libraries (+restart)
psql -d TARGET -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
psql -d TARGET -c "SELECT timescaledb_pre_restore();"
pg_restore --no-owner --no-privileges -d TARGET ~/pfip-backups/pfip-<ts>.dump
psql -d TARGET -c "SELECT timescaledb_post_restore();"
```
Restoring back to the managed provider: create a fresh DB / branch there (it already has
timescaledb configured) and run the same `pre_restore`/`pg_restore`/`post_restore` sequence —
never restore over the live prod DB. The dump is integrity-checked on every backup run, so a
known-good archive is always on disk; the `pre/post_restore` wrap is the one timescaledb-specific
step that a plain-Postgres runbook would miss.
