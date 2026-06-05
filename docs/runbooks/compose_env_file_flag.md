# Runbook — Docker Compose can't resolve `.env` (variable not set / abort)

> **2026-06-04 audit note.** Auth-critical secrets in `infra/docker-compose.yml` now use
> the **fail-loud** `${VAR:?error message}` form (`NEXTAUTH_SECRET`, `POSTGRES_PASSWORD`).
> The old fail-**open** defaults (`:-pfip_dev`, `:-dev-change-me`) are gone, so a missing
> `--env-file` (or a genuinely unset secret) no longer *silently* substitutes a dev value —
> compose now **aborts at startup**. The symptom below changed accordingly.

## Symptoms

`docker compose up` aborts immediately with an error like:

```
error while interpolating services.timescaledb.environment.[]:
  required variable POSTGRES_PASSWORD is missing a value: set POSTGRES_PASSWORD in .env
```

or the same for `NEXTAUTH_SECRET`. The stack never starts.

For non-fail-loud vars (the many `${VAR:-default}` ones that remain for *non-secret*
config), the older failure mode can still bite: a service env var at runtime uses the
fallback default instead of the real `.env` value, e.g.:

- `docker exec pfip-backend printenv SOME_OPTIONAL_VAR` → the `:-default` value, not the
  real `.env` value.

## Cause

Docker Compose has **two layers** of env handling:

1. **`env_file: ../.env`** in a service definition → values loaded into the *container's environment* at runtime. Not interpolated by compose.
2. **`environment:` block with `${VAR:?...}` (required) or `${VAR:-default}` (optional)** → substituted by compose at *YAML parse time*. Compose only reads from `.env` for this substitution if `--env-file .env` is passed (or if `.env` is in the same directory as the compose file).

Our compose file is at `infra/docker-compose.yml` and `.env` is at the project root. Compose's auto-discovery looks next to the compose file → finds nothing. For `${VAR:?}` secrets that now means a hard abort; for `${VAR:-default}` config it means the default is used.

## Diagnosis

If the symptom is the **abort**: the named variable (`POSTGRES_PASSWORD` / `NEXTAUTH_SECRET`) is either truly absent from `.env` **or** compose isn't reading `.env` because `--env-file .env` was omitted. Confirm both:

```powershell
Select-String "POSTGRES_PASSWORD","NEXTAUTH_SECRET" .env   # are they actually set?
```

If the symptom is a wrong **optional** value at runtime:

```powershell
docker exec <container> printenv <SUSPECTED_VAR>
```

Compare with `.env` contents. If the running container's value matches the **default** in the compose file instead of the **.env** value, compose didn't read `.env` for that substitution.

## Fix

Pass `--env-file .env` whenever invoking compose:

```powershell
docker compose -f infra\docker-compose.yml --env-file .env up -d --force-recreate <service>
```

`--force-recreate` is important — `restart` reuses the existing container with old env values.

## Prevention

Set both env variables once per shell session:

```powershell
$env:COMPOSE_FILE = "infra\docker-compose.yml"
$env:COMPOSE_ENV_FILES = ".env"
```

Plain `docker compose up -d` now picks up both correctly. Add to `$PROFILE` to persist.

The wrappers in `scripts/up.ps1`, `scripts/up.sh`, and `Makefile` already pass `--env-file` explicitly.
