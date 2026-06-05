# Runbook — Prefect flow fails with TypeError on unexpected keyword argument

## Symptoms

Flow run logs show:

```
TypeError: ingest_<name>() got an unexpected keyword argument '<kwarg>'
```

The task retries 3 times (per task config) then the whole flow ends `Failed`.

Example we hit:

```
TypeError: ingest_watchlist() got an unexpected keyword argument 'since'
```

## Cause

Flow code drifted from the adapter's signature. The flow passes keyword arguments that the adapter no longer accepts (or never accepted).

The audit-friendly invariant: every `await ingest_<name>(...)` call in `pfip/prefect/flows/*.py` must match the corresponding `async def ingest_<name>(...)` in `pfip/ingest/...`.

## Fix

1. Find the adapter signature:

   ```powershell
   docker exec pfip-backend grep -rn "^async def ingest_<name>" /app/pfip/ingest/
   ```

2. Compare to the flow's call site. The error message identifies the file + line.

3. Either: change the flow to use the correct kwargs, or extend the adapter to accept the kwargs the flow needs. **Prefer changing the flow** — adapters are reused by tests and one-off scripts.

   In our case, the adapter takes `lookback_days` and computes `since` internally; the flow was passing `since=` and `limit=`. Fix was to convert lookback_hours → lookback_days at the flow level and drop the unsupported kwargs.

4. Re-run:

   ```powershell
   docker exec pfip-backend python -m pfip.prefect.flows.<flow_name>
   ```

   Watchfiles auto-reloads the `--reload` uvicorn process inside the backend container, so no rebuild is needed for `.py` edits.

## Audit script (find all such bugs preemptively)

```powershell
# In WSL / Git Bash:
cd backend
grep -n "await ingest_" pfip/prefect/flows/*.py | grep -v "()"
```

Each match is a call with kwargs — verify the adapter signature matches.

## Prevention

When agents touch both flows and adapters in parallel, signature drift is easy to introduce. Two countermeasures:

1. Pre-commit hook (already configured) running `ruff` + `mypy` catches some of these statically.
2. **The `--reload` watchfiles auto-reloader means signature mismatches surface immediately** on first flow run, not in production. Run each flow manually after merging any change touching the ingest layer.
