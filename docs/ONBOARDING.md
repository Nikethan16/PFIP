# PFIP Onboarding — Resume-After-Pause Playbook

Template from plan **Appendix E**. Read this top-to-bottom when coming back after any
multi-week pause. Takes ~20 minutes to re-establish context; fully updatable as stages
progress.

---

## 1. Where we are

- **Current stage:** Stage 0 — freshly scaffolded, not yet brought up.
- **Tier state:** Tier-S scaffolding in place (infra + ingest + auth + contracts).
  Tier-A modules (signals, backtest) stubbed. Tier-B (agent, KB) skeletons only.
- **Last verified run:** not yet — `docker compose up` has not been executed on the host.
- **Next milestone:** `docs/checklists/stage_gate_0.md` — sign off Stage 0.

Update this section after every stage graduation.

---

## 2. Active decisions

Four open decisions from plan Section 16 block Stage 0 completion. See root
`PLACEHOLDERS.md` section 1 for the latest state. Short version:

1. Starting market for Stage 1 — default is BTC.
2. Dedicated Telegram account for Telethon — not yet created.
3. Hetzner ARM VPS (~$5/mo) as secondary — not provisioned.
4. Auto-execution aspiration — advisory-only today; broker adapter module is empty.

Resolve or explicitly defer each before advancing to Stage 1.

---

## 3. Stack restart (PowerShell)

After any reboot, long pause, or Docker Desktop reinstall:

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app

# 1. Confirm Docker Desktop is running (system tray icon green)
docker version

# 2. Pull any image updates (safe; no data loss)
docker compose -f infra/docker-compose.yml pull

# 3. Start the stack detached
#    NEXTAUTH_SECRET and POSTGRES_PASSWORD are mandatory (compose uses ${VAR:?} and aborts
#    if either is unset). All host ports bind to 127.0.0.1 (loopback) — nothing on the LAN.
#    After pulling new code, run `pnpm install` in frontend/ first (Next bump + middleware).
docker compose -f infra/docker-compose.yml --env-file .env up -d

# 4. Wait ~60 seconds, then status
Start-Sleep -Seconds 60
docker compose -f infra/docker-compose.yml ps

# 5. Deep health check
curl http://localhost:8000/api/v1/health/deep
```

If any service shows `unhealthy` or `exited`, jump to the matching runbook in
`docs/runbooks/`.

---

## 4. What's in-flight

Track currently-active work here. At Stage 0 bring-up:

- [ ] First `docker compose up` on this machine.
- [ ] `.env` populated with critical secrets (see `PLACEHOLDERS.md` section 2).
- [ ] BTC daily ingest Prefect flow run once successfully.
- [ ] First backup artifact produced and verified non-empty.
- [ ] Stage 0 checklist (`docs/checklists/stage_gate_0.md`) fully green.

Add new rows as stages unlock; strike through when done (leave in place for history).

---

## 5. Known issues

None observed yet (nothing has been run). Seed entries to watch for:

- Windows Defender can block the bcrypt hash script the first time it runs — allow it.
- Docker Desktop WSL integration sometimes loses the default distro after Windows updates;
  reopen Settings → Resources → WSL Integration and toggle it.
- Port 5432 may already be taken by a native PostgreSQL install — see
  `docs/runbooks/docker_compose_port_conflict.md`.

---

## 6. This month's scheduled tasks

From plan Section 12.2 (full table in `docs/SCHEDULED_TASKS.md`). At Stage 0 only the
infra-hygiene ones are active:

| Cadence     | Task                                             | Owner     | Status        |
| ----------- | ------------------------------------------------ | --------- | ------------- |
| Daily 01:00 | Nightly backup (TimescaleDB + Qdrant + MLflow)   | Prefect   | not wired yet |
| Weekly Sun  | Docker image update check                        | manual    | manual only   |
| Monthly 1st Sat | Calibration report (empty until Stage 4)     | Prefect   | Stage 4       |
| Quarterly   | Restore-from-backup drill (run from Stage 0)     | manual    | TODO(user)    |
| Quarterly   | Tier-S/A/B tracker review                        | manual    | TODO(user)    |
| Quarterly   | Dependency update sweep (`uv lock --upgrade`)    | manual    | TODO(user)    |
| Quarterly   | Rotate secrets in `.env`                         | manual    | TODO(user)    |

---

## 7. Contacts

Fill these once, then refer. All are `TODO(user):` until resolved.

```
Chartered Accountant
  Name:        TODO(user)
  Firm:        TODO(user)
  Email:       TODO(user)
  Phone:       TODO(user)
  Last synced: TODO(user)  # date of last tax/portfolio handoff

Primary broker (Indian equities)
  Name:        TODO(user)  # e.g. Zerodha / Groww
  Login URL:   TODO(user)
  Client ID:   TODO(user)

Crypto exchange
  Name:        TODO(user)  # e.g. CoinDCX / WazirX
  KYC ref:     TODO(user)

US brokerage (if any)
  Name:        TODO(user)  # e.g. IBKR / Vested
  Account ID:  TODO(user)

Bank (INR settlement)
  Name:        TODO(user)
  Relationship mgr: TODO(user)

Cloud provider (once VPS added)
  Hetzner account: TODO(user)
  Tailscale tailnet: TODO(user)
```

Keep the non-secret bits here; real credentials belong only in `.env`.

---

## 8. Quick-reference links

- Plan: `../PFIP_v0.5/financial_intelligence_platform_plan.md`
- Tracker: `../PFIP_v0.5/tracker.md`
- Contracts: `./CONTRACTS.md`
- Architecture: `./ARCHITECTURE.md`
- Security: `./SECURITY.md`
- Backup & DR: `./BACKUP.md`
- Runbooks: `./runbooks/`
- Checklists: `./checklists/`
- Placeholders: `../PLACEHOLDERS.md`
