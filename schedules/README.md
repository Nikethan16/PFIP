# PFIP — Scheduled Tasks

Operational rhythm for PFIP, per Section 12.2 of the plan. **Skipping a
scheduled task is itself a signal** — a missed monthly calibration report means
the signal layer is unmonitored.

Two execution layers are used, each chosen for what it does best:

| Layer | Runs | Used for | Survives | Lives in |
|---|---|---|---|---|
| **Prefect deployments** | Inside `pfip-backend` (via Prefect server + worker) | Code-level flows: ingest, features, briefs, shadow-portfolio, post-mortems, calibrations | Host reboot (via Docker `restart: unless-stopped`) | `prefect_deployments.py` |
| **Windows Task Scheduler** | On the Windows host | Things that must work even when the Docker stack is down: nightly backup, quarterly restore drill | Host reboot | `register_windows_tasks.ps1` + `windows_task_scheduler.xml` |

Why two layers? Prefect runs inside Docker, so Prefect cannot reliably do the
thing that matters most when Docker is broken: back the data up or verify that
backups actually restore. Those live on the host.

## Task catalogue — Section 12.2

| Cadence | Local (IST) | UTC cron | Task | Runs on | Stage live |
|---|---|---|---|---|---|
| Daily | 00:35 | `5 0 * * *` | `ingest-btc-daily` | Prefect | 1 |
| Daily | 05:40 | `10 0 * * *` | `compute-features-daily` | Prefect | 1 |
| Daily | 07:00 | `30 1 * * *` | `morning-brief` | Prefect | 1 |
| Daily (weekdays) | 17:30 | `0 12 * * 1-5` | `market-close-summary` | Prefect | 1 |
| Daily | 23:30 | `0 18 * * *` | `shadow-reconcile-daily` | Prefect | 4 |
| Weekly Sat | 09:00 | `30 3 * * 6` | `arxiv-digest` | Prefect | 3 |
| Weekly Sun | 19:00 | `30 13 * * 0` | `weekly-post-mortem` | Prefect | 3 |
| Monthly (first Sat) | 10:00 | `30 4 1-7 * 6` | `monthly-calibration` | Prefect | 4 |
| Monthly (last Sun) | 19:00 | `30 13 25-31 * 0` | `monthly-shadow-rollup` | Prefect | 4 |
| Nightly | 03:15 | — | `PFIP-Nightly-Backup` | Windows Task Scheduler | 0 |
| Quarterly (first Sat of Jan/Apr/Jul/Oct) | 10:00 | — | `PFIP-Quarterly-RestoreDrill` | Windows Task Scheduler | 0 |

IST → UTC = -05:30. The `1-7 * 6` day-of-month trick for "first Saturday" and
`25-31 * 0` for "last Sunday" are standard cron idioms.

## Setup — run in this order

### 1) Prefect deployments

```powershell
# Inside the backend container where Prefect is installed
docker exec -i pfip-backend python /app/schedules/prefect_deployments.py plan
docker exec -i pfip-backend python /app/schedules/prefect_deployments.py apply --stage 0
```

The `--stage N` flag tells the registrar which deployments should be ACTIVE vs
PAUSED. At Stage 0, everything registers PAUSED except `ingest-btc-daily` and
`morning-brief` (wait, those are Stage 1 — so nothing is active yet, which is
correct: no code flows exist at Stage 0).

Bump the `--stage` argument as you advance through the roadmap and re-run
`apply`. Pause/resume without re-registration:

```powershell
docker exec -i pfip-backend python /app/schedules/prefect_deployments.py pause
docker exec -i pfip-backend python /app/schedules/prefect_deployments.py resume
```

### 2) Windows host tasks

```powershell
# As Administrator
.\schedules\register_windows_tasks.ps1

# Verify
Get-ScheduledTask -TaskName 'PFIP-*' | Format-Table TaskName, State, @{n='NextRun';e={(Get-ScheduledTaskInfo $_).NextRunTime}}

# Uninstall
.\schedules\register_windows_tasks.ps1 -Unregister

# Export as XML (for archival / porting to a new machine)
.\schedules\register_windows_tasks.ps1 -Export
```

The XML template (`windows_task_scheduler.xml`) is a readable reference — the
registrar script is the canonical installer.

## What to do when a task misses

1. Check Prefect UI at `http://localhost:4200` — failed runs show with a
   retry/rerun button and full stderr.
2. Check Windows Task Scheduler history for host tasks.
3. Update the matching runbook under `/docs/runbooks/` with the incident and
   fix (see Appendix D of the plan).

## Rules of thumb

- **Never** put secrets in scheduled-task XML or deployment parameters. Use the
  `.env` mounted into `pfip-backend`.
- **Always** prefer Prefect for anything that reads/writes the database or
  calls external APIs — Prefect handles retries, concurrency, and observability.
- **Use Windows Task Scheduler** only for host-level operations: backup,
  restore drill, dependency sweeps, OS-level checks.
