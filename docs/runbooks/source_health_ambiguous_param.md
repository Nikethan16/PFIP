# Runbook — source_health record_run ProgrammingError: AmbiguousParameter

## Symptoms

After any ingest flow runs, the logs contain:

```
WARNING | pfip.ingest._common.source_health:record_run:77 - source_health record_run(...) failed:
ProgrammingError: (psycopg.errors.AmbiguousParameter)
could not determine data type of parameter $3
LINE 8:             CASE WHEN $3 IS NULL THEN $2 ELSE NULL END,
```

## Cause

psycopg3 prepares the statement with each parameter typed by inference. The original `INSERT INTO source_health` had:

```sql
CASE WHEN :err IS NULL THEN :now ELSE NULL END
```

Every reference of `:err` only appears next to `NULL` — psycopg can't infer the type. It fails before the row reaches the DB.

**The warning is non-fatal** — the ingest flow continues and the actual data rows (OHLCV, news, etc.) still persist. Only the `source_health` row fails to update, so the freshness badges on the UI may be stale.

## Fix

Already applied in `pfip/ingest/_common/source_health.py`. The `:err` parameter is now cast explicitly:

```sql
CASE WHEN CAST(:err AS text) IS NULL THEN :now ELSE NULL END,
:rows, CAST(:err AS text),
```

The cast at first use propagates the type to subsequent references.

## Verify the fix landed

```powershell
docker exec pfip-backend grep -n "CAST(:err AS text)" /app/pfip/ingest/_common/source_health.py
```

Should show two matches.

If you still see the warning after the fix, the backend container hasn't picked up the file change. Either:

```powershell
# Dev (bind-mounted source — watchfiles auto-reloads):
docker exec pfip-backend touch /app/pfip/api/main.py   # forces reload

# Or full restart:
docker compose -f infra\docker-compose.yml restart backend
```

## Why this pattern is brittle

psycopg3 has stricter type inference than psycopg2. Any time a named parameter only appears next to `NULL` (in `CASE WHEN`, `COALESCE`, etc.), add an explicit `CAST(:param AS <type>)` at the first occurrence.
