# Runbook — TimescaleDB password authentication failed

## Symptoms

Backend logs (or `alembic upgrade head` output) show:

```
psycopg.OperationalError: connection failed: connection to server at "...", port 5432 failed: FATAL:  password authentication failed for user "pfip"
```

## Cause

Two distinct password values fall out of sync:

1. **The password stored in the TimescaleDB volume** — set the very first time the volume was initialized from `POSTGRES_PASSWORD` env var.
2. **The password in the backend's connection string** (`DATABASE_URL`).

If `.env` is edited **after** the volume is initialized, the volume keeps the old password while `DATABASE_URL` carries the new one — the two diverge and auth fails.

> **2026-06-04 audit note.** `POSTGRES_PASSWORD` is now a fail-loud `${POSTGRES_PASSWORD:?...}`
> in compose — the old `${POSTGRES_PASSWORD:-pfip_dev}` fallback was removed. So running
> `docker compose up` without `--env-file .env` no longer *silently* substitutes a dev
> default; it **aborts before any service starts** (see
> `compose_env_file_flag.md`). That removes one historical cause of this mismatch — the
> remaining cause is editing `.env` after the volume was already initialized with a
> different password.

## Diagnosis

```powershell
docker exec pfip-backend printenv DATABASE_URL
Select-String "POSTGRES_PASSWORD" .env
```

If the password embedded in `DATABASE_URL` doesn't match the value in `.env`, this is the bug.

## Fix (no data loss)

1. **Recreate backend with the env-file flag** so compose interpolates `.env` correctly:

   ```powershell
   docker compose -f infra\docker-compose.yml --env-file .env up -d --force-recreate backend
   docker exec pfip-backend printenv DATABASE_URL   # verify password matches .env
   ```

2. **Reset the DB user password** to match `.env`. TimescaleDB's local Unix socket has `trust` auth so we can do it without the password:

   ```powershell
   docker exec pfip-timescaledb psql -U pfip -d pfip -c "ALTER USER pfip WITH PASSWORD 'pfip_dev_change_me';"
   ```

   Adjust the value in single quotes if your `.env` uses a different password.

3. **Retry the failing command** (e.g. `docker exec pfip-backend alembic upgrade head`).

## Prevention

Set the compose env-file once per PowerShell session so plain `docker compose` calls always interpolate correctly:

```powershell
$env:COMPOSE_FILE = "infra\docker-compose.yml"
$env:COMPOSE_ENV_FILES = ".env"
```

Or persist in `$PROFILE`. The `scripts/up.ps1` wrapper already does this.

## Last resort (data loss)

If trust-auth on the socket also fails:

```powershell
docker compose -f infra\docker-compose.yml down
docker volume rm pfip_timescale_data
docker compose -f infra\docker-compose.yml --env-file .env up -d
docker exec pfip-backend alembic upgrade head
```

Loses ingested data; safe to re-ingest via the Prefect flows.
