# Runbook — Prefect flow stuck in RUNNING > 2h

## Symptoms

- Prefect UI (http://localhost:4200) shows a flow run in `Running` state well past its
  expected duration.
- Downstream flows queue up waiting for the stuck one.
- Uptime Kuma alert on "flow duration breached SLA".

## Diagnosis

1. Open the run in the UI; check last log line. Common patterns:
   - Last log hours ago → worker probably died.
   - Logs still ticking but slow → task stuck in a network call.
2. From the CLI, list running flow runs:
   ```powershell
   docker exec -it pfip-prefect prefect flow-run ls --state Running
   ```
3. Inspect the worker:
   ```powershell
   docker exec -it pfip-backend prefect worker inspect
   ```
4. Check DB for dangling transactions (a common cause of stuck ingest flows):
   ```sql
   SELECT pid, state, now() - query_start AS age, query
   FROM pg_stat_activity WHERE state != 'idle' ORDER BY age DESC LIMIT 10;
   ```

## Fix

### Primary

- Cancel the flow run cleanly:
  ```powershell
  docker exec -it pfip-prefect prefect flow-run cancel <run-id>
  ```
- If a DB query is blocking, terminate it:
  ```sql
  SELECT pg_terminate_backend(<pid>);
  ```
- Restart the Prefect worker (not the server):
  ```powershell
  docker compose -f infra/docker-compose.yml restart backend
  ```

### Fallback

- Force-state the run to `Crashed` via the API so retries engage:
  ```powershell
  docker exec -it pfip-prefect prefect flow-run set-state <run-id> --state CRASHED
  ```
- Disable the schedule temporarily until root-caused:
  ```powershell
  docker exec -it pfip-prefect prefect deployment set-schedule <name>/<deployment> --no-schedule
  ```

### Nuclear

- Restart the whole Prefect stack:
  ```powershell
  docker compose -f infra/docker-compose.yml restart prefect backend
  ```
- If the Prefect server DB got corrupted, remove the `prefect_data` volume and
  re-register deployments from `/schedules/` (config is the source of truth).

## Prevention

- Every task wrapped with `timeout_seconds=` appropriate to its job.
- Retries: `retries=3, retry_delay_seconds=60` on all ingest tasks.
- Kill-switch: Prefect deployment flag `pause_if_runtime_gt=7200` (2h) auto-cancels long runs.
- Heartbeat: worker health-check emits a log line every 60s; Uptime Kuma watches it.
- Dashboard card on frontend Ops page lists flows with age > their SLA.

## Last occurred

None yet (Stage 0 fresh install).
