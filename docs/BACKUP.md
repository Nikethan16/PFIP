# PFIP Backup & Disaster Recovery

Backups are non-negotiable from Stage 0. You lose OHLCV history and you've lost weeks of
ingest work; you lose the portfolio ledger and you've lost ground truth for P&L and tax.
Everything below is automatable via the scripts in `/scripts/` (owned by another agent —
this doc is the spec and the runbook that wraps them).

---

## 1. What we back up

| Asset            | Source                                      | Tool                        | Frequency |
| ---------------- | ------------------------------------------- | --------------------------- | --------- |
| TimescaleDB      | `pfip-timescaledb` container                | `pg_dump --format=custom`   | nightly   |
| Qdrant           | `pfip-qdrant` container                     | Qdrant snapshot API         | nightly   |
| MLflow artifacts | `mlflow_data` volume (`/mlflow/artifacts`)  | `rsync -a`                  | nightly   |
| `.env`           | repo root                                   | GPG-encrypted copy          | on change |
| `/docs/`         | repo                                        | git (already version-ed)    | on commit |
| Telegram session | `/backend/pfip/ingest/telegram/*.session`   | GPG-encrypted copy          | weekly    |
| Alembic history  | `/backend/alembic/versions/`                | git                         | on commit |

What we **don't** back up:

- Docker volumes for Redis (ephemeral cache, rebuildable).
- Prefect server DB (re-registered from `/schedules/`).
- Uptime Kuma config (takes 2 minutes to recreate; optional).
- `data/kb_sources/` (large, copyrighted — you re-acquire from source).
- `node_modules`, `.next`, `__pycache__` (build outputs).

---

## 2. Where we store backups

Two-tier strategy ("3-2-1" adapted for solo):

1. **Local encrypted external drive.** Mount point e.g. `E:\pfip_backups\`. Drive has its
   own BitLocker layer separate from the working disk.
2. **Cloud, via rclone.** Backblaze B2 is the cheapest for Indian users paying in INR;
   Google Drive works too if you already have the quota. Configure `rclone config` with a
   remote named `pfip-cloud`. All uploads happen to an encrypted remote
   (`rclone config` → crypt wrapper → points at the B2/Drive bucket).

The nightly script writes to the local drive first, verifies checksums, then syncs to the
cloud remote. If the local drive is absent, the script still syncs straight to cloud but
emits a Telegram alert.

---

## 3. Schedule

| Job                           | Time (IST)     | Owner     | Artifact location                           |
| ----------------------------- | -------------- | --------- | ------------------------------------------- |
| Full backup (all of section 1)| 01:00 daily    | Prefect   | `E:\pfip_backups\YYYY-MM-DD\` + cloud mirror|
| Checksum verify (last 7)      | 01:30 daily    | Prefect   | logs only                                   |
| Monthly archive (1st of month)| 01:45 monthly  | Prefect   | separate `monthly/` prefix                  |
| Quarterly restore drill       | 1st Sat / qtr  | manual    | documented below                            |

Implemented in `/scripts/backup.py` (Prefect flow) and `/scripts/backup.ps1`
(PowerShell wrapper for manual / scheduled task use).

---

## 4. Retention

- **30** daily snapshots (rolling).
- **12** monthly snapshots (first-of-month, kept 1 year).
- **5** yearly snapshots (first-of-Jan, kept 5 years).

Pruning logic runs at the tail of the nightly job. Cloud remote has the same retention
policy expressed as rclone lifecycle rules.

Storage estimate at steady state: TimescaleDB dump ~200 MB/yr per asset, Qdrant snapshot
~100 MB once KB is ingested, MLflow grows with model count. Total budget: **~20 GB/yr**.

---

## 5. Restore drill (quarterly, first run documented here)

Pick a recent backup and practise restoring it into a disposable Docker environment. Do
**not** restore over production volumes unless recovering from real data loss.

```powershell
# 1. Stop the running stack (or use a throwaway profile)
docker compose -f infra/docker-compose.yml down

# 2. Spin up a scratch TimescaleDB container
docker run -d --name pfip-restore-test `
  -e POSTGRES_PASSWORD=restoretest `
  -p 55432:5432 `
  timescale/timescaledb:2.15.2-pg16

# 3. Restore the most recent dump
$latest = Get-ChildItem E:\pfip_backups -Directory | Sort-Object Name -Desc | Select-Object -First 1
docker exec -i pfip-restore-test pg_restore -U postgres -d postgres `
  --create --clean --if-exists `
  < "$($latest.FullName)\timescaledb.dump"

# 4. Row-count sanity check
docker exec -it pfip-restore-test psql -U postgres -d pfip -c `
  "SELECT symbol, count(*) FROM ohlcv GROUP BY 1 ORDER BY 2 DESC LIMIT 10;"

# 5. Qdrant snapshot restore
docker run -d --name pfip-qdrant-restore `
  -p 56333:6333 `
  -v "$($latest.FullName)/qdrant:/qdrant/snapshots" `
  qdrant/qdrant:v1.9.3
# then POST to /collections/{name}/snapshots/recover per Qdrant docs

# 6. Tear down scratch containers
docker rm -f pfip-restore-test pfip-qdrant-restore
```

Record the result (pass / fail + duration) in `docs/ONBOARDING.md` section 4.

**First restore drill: TODO(user) — run within 2 weeks of Stage 0 sign-off.**

---

## 6. Disaster scenarios

| Scenario                              | Recovery                                                                              |
| ------------------------------------- | ------------------------------------------------------------------------------------- |
| Single service container dies         | `docker compose up -d <service>`; data intact in named volume.                        |
| Named volume corrupted                | Restore from last night's backup (section 5).                                         |
| Workstation disk fails                | New box → install prereqs → `git clone` → restore `.env` from encrypted copy → restore DB/Qdrant/MLflow → `docker compose up`. |
| External drive lost/stolen            | Cloud remote is source of truth; verify encryption passphrase not reused.             |
| Ransomware                            | Restore from cloud (immutable bucket versioning on Backblaze B2 with Object Lock).    |
| `.env` leak                           | Rotate every key per `docs/SECURITY.md` section 8; re-issue `NEXTAUTH_SECRET`.        |
| Accidentally committed secret         | Rotate first, then `git filter-repo` to scrub, force-push, notify providers.          |

---

## 7. Operational checklist

- [ ] `scripts/backup.py` wired as a Prefect deployment (schedule: daily 01:00 IST).
- [ ] `scripts/restore.py` exists and was dry-run tested once.
- [ ] External backup drive mounted and BitLocker-encrypted.
- [ ] `rclone config` set up with a crypt-wrapped remote named `pfip-cloud`.
- [ ] Backblaze B2 (or Drive) bucket has object-lock / versioning enabled.
- [ ] First restore drill completed and logged in `ONBOARDING.md`.
- [ ] Alert rule in Uptime Kuma for "no successful backup in 36h".
