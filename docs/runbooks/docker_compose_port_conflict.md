# Runbook — docker compose port conflict on Windows

## Symptoms

- `docker compose up` fails with
  `Error starting userland proxy: listen tcp 0.0.0.0:5432: bind: address already in use`
  (or 3000 / 8000 / 6379 / any other PFIP port).
- `docker compose ps` shows the offending service as `exited (125)`.
- Very common on Windows when PostgreSQL, IIS, Hyper-V, or a previous Node dev server has
  claimed the port.

## Diagnosis

1. Identify the process holding the port:
   ```powershell
   # For port 5432
   netstat -ano | Select-String ":5432"
   Get-Process -Id <PID>   # resolve the PID from netstat output
   ```
2. Common culprits on Windows:
   | Port  | Frequent occupant                                     |
   | ----- | ----------------------------------------------------- |
   | 3000  | Another Node / CRA dev server                         |
   | 5432  | Native PostgreSQL install (service `postgresql-x64-16`) |
   | 6379  | Memurai / native Redis install                        |
   | 8000  | Python `http.server`, Django dev, Jupyter             |
   | 4200  | Angular CLI                                           |
   | 5000  | Flask dev server, AirPlay Receiver on older macOS     |
3. Alternatively, ask Docker:
   ```powershell
   docker ps --filter "publish=5432"
   ```

## Fix

### Primary — stop the other process

- If it's a Windows service:
  ```powershell
  Get-Service postgresql* | Stop-Service
  Set-Service postgresql-x64-16 -StartupType Manual   # stop auto-start
  ```
- If it's an orphan Node process: `Stop-Process -Id <PID> -Force`.

### Fallback — remap PFIP to a free port

Every port is parameterised in `.env`. Pick a free port and override:

```powershell
# In .env
TIMESCALEDB_PORT=55432
REDIS_PORT=56379
BACKEND_PORT=58000
FRONTEND_PORT=53000
```

Then restart:

```powershell
docker compose -f infra/docker-compose.yml down
docker compose -f infra/docker-compose.yml --env-file .env up -d
```

Remember to update any bookmarks / client configs to the new port.

### Nuclear

- Uninstall the conflicting Windows service entirely (e.g. native PostgreSQL) if it's
  unused.
- If Hyper-V reserved the port (`HNS` / `excluded port range`), reboot then:
  ```powershell
  netsh int ipv4 show excludedportrange protocol=tcp
  # if 5432 is excluded, restart "Host Network Service" or recreate Docker's NAT
  ```

## Prevention

- Document any non-default ports you chose in `docs/ONBOARDING.md` section 3.
- Run the preflight check before first up:
  ```powershell
  foreach ($p in 3000,3001,4200,5000,5432,6333,6334,6379,8000,11434) {
    if ((Test-NetConnection -ComputerName localhost -Port $p -WarningAction SilentlyContinue).TcpTestSucceeded) {
      Write-Warning "Port $p already in use"
    }
  }
  ```
- Don't install native PostgreSQL or Redis alongside PFIP. If you must, put them on
  non-default ports.

## Last occurred

None yet (Stage 0 fresh install).
