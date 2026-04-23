# PFIP Security — Stage 0 Checklist

Security posture for a solo-built, local-first platform. Derived from plan **Section 11.7**.
Everything below must be green before Stage 0 sign-off.

Threat model in one line: single operator, single workstation, no inbound from internet,
secrets-on-disk are the main exposure. Harden the disk, harden the perimeter, rotate keys.

---

## 1. Full-disk encryption

**Windows (primary):** enable BitLocker on the drive holding `PFIP_app/` *before* you
populate `.env`.

```powershell
# Check status
manage-bde -status

# Enable on C: (requires TPM or USB recovery key, admin prompt)
manage-bde -on C: -RecoveryPassword

# Save the recovery key somewhere you control (password manager, not the same disk)
```

Linux equivalent (if you later move to a Linux workstation or VPS): LUKS on the root
filesystem, passphrase unlock at boot.

Checklist:

- [ ] BitLocker **On** for every drive that touches the repo or backups.
- [ ] Recovery key exported to a password manager entry labelled `PFIP BitLocker`.
- [ ] Drive locks automatically on sleep (Group Policy → BitLocker → "Require startup PIN").

---

## 2. Windows Defender Firewall

Default stance: block all inbound; allow outbound. Docker Desktop exposes host ports on
`localhost`, but a misconfigured "Public" profile can leak them onto the LAN.

```powershell
# Confirm Defender profile for your active network is Private (not Public)
Get-NetConnectionProfile

# If it says Public, change it:
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private

# Block inbound on PFIP ports just in case (localhost traffic is unaffected)
New-NetFirewallRule -DisplayName "Block PFIP inbound" `
  -Direction Inbound -Action Block `
  -LocalPort 3000,3001,4200,5000,5432,6333,6334,6379,8000,11434 `
  -Protocol TCP
```

Checklist:

- [ ] Active network profile is **Private** (never `Public` while PFIP is running).
- [ ] Inbound rule above is present (`Get-NetFirewallRule -DisplayName "Block PFIP inbound"`).
- [ ] Docker Desktop → Settings → Resources → Network: "Expose daemon on tcp://..." is **off**.

---

## 3. Never expose ports publicly

Rules of thumb:

- The backend (`8000`) and frontend (`3000`) are **localhost-only**.
- Do not port-forward on your router. Do not put them behind a bare public nginx.
- If you need remote access, use Tailscale (see section 7) — it gives you a WireGuard tunnel
  without opening inbound holes.
- If you ever deploy to a VPS, bind all services to `127.0.0.1` inside the VPS and reach
  them via SSH tunnel or Tailscale only.

Checklist:

- [ ] No router port-forwarding rules point to this machine.
- [ ] `docker compose ps` shows all host ports bound (no `0.0.0.0:*` on cloud hosts).

---

## 4. SSH keys (only if a VPS is added)

Until a VPS is provisioned this section is N/A. When it is:

- Generate a dedicated ed25519 key: `ssh-keygen -t ed25519 -f ~/.ssh/pfip_vps -C pfip-vps`.
- Upload only the public key; passphrase the private key.
- Disable password auth on the VPS (`PasswordAuthentication no`).
- Disable root login (`PermitRootLogin no`).
- Restrict by source IP if your ISP gives a stable prefix.

Checklist (when VPS exists):

- [ ] Password auth disabled in `/etc/ssh/sshd_config`.
- [ ] Root login disabled.
- [ ] Fail2ban installed.
- [ ] Tailscale on both ends (see section 7); SSH only over tailnet.

---

## 5. `.env` handling

The `.env` file holds every API key and the NextAuth secret. Treat it like a password.

Rules:

- Never commit `.env`. The repo `.gitignore` already excludes it — verify with
  `git check-ignore .env` (should print `.env`).
- Never paste `.env` contents into chats, tickets, screenshots.
- Keep a backup copy encrypted separately (see `docs/BACKUP.md` section on `.env`).
- Rotate secrets **quarterly**; rotate *immediately* on suspected compromise.

Quarterly rotation checklist (calendar this — first Saturday of Jan / Apr / Jul / Oct):

- [ ] Generate new `NEXTAUTH_SECRET` (`openssl rand -base64 32`).
- [ ] Regenerate `PFIP_USER_PASSWORD_HASH` (`python scripts/make_password_hash.py`).
- [ ] Rotate API keys: Coinbase, FRED, Finnhub, Tiingo, FMP, Polygon, NewsAPI, MarketAux,
      Reddit, Neynar, Groq. Revoke old tokens in each provider's dashboard.
- [ ] Rotate Telegram API hash/session if the dedicated account exists.
- [ ] Rotate Sentry DSN if leak suspected.
- [ ] Restart stack: `docker compose down && docker compose up -d`.
- [ ] Tick the entry in `docs/ONBOARDING.md` section 6.

---

## 6. Telegram account hygiene

If you enable Telegram ingest (Telethon) **or** outbound alerts (bot):

- Use a **dedicated Telegram account** — not your personal phone number. Buy a cheap
  secondary SIM or use a second-number service for the OTP.
- The Telethon session file (`*.session`) grants full access to that account. It lives at
  `/backend/pfip/ingest/telegram/pfip_session.session` and is gitignored (see
  `.gitignore` line for `*.session`).
- The alert bot token (`TELEGRAM_BOT_TOKEN`) is only useful to send messages into one
  chat ID; still, revoke via @BotFather if leaked.

Checklist:

- [ ] Telegram ingest account is **not** the primary personal account.
- [ ] `pfip_session.session` is **not** in `git ls-files`.
- [ ] Bot chat ID is confirmed and restricted to you.

---

## 7. Tailscale tunnel (optional, recommended when away from LAN)

If you want to hit the dashboard from your phone on cellular without exposing ports:

- Install Tailscale on the workstation and phone.
- Join both to the same tailnet.
- Browse to `http://100.x.y.z:3000` (the tailnet IP) — no router changes needed.

Do **not** enable Tailscale "Serve" / "Funnel" (which expose to public internet) unless you
deliberately want that and have added auth on top.

Checklist (optional):

- [ ] Tailscale installed on both ends.
- [ ] MagicDNS enabled for readable hostnames.
- [ ] Tailscale ACLs locked to the operator's identity only.

---

## 8. Quarterly secret rotation — one-page checklist

Copy this into a ticket each quarter.

```
Date: ____/____/______

[ ] NEXTAUTH_SECRET regenerated
[ ] PFIP_USER_PASSWORD_HASH regenerated
[ ] Coinbase API key/secret rotated
[ ] FRED API key rotated
[ ] Finnhub API key rotated
[ ] Tiingo API key rotated
[ ] FMP API key rotated
[ ] Polygon API key rotated
[ ] NewsAPI key rotated
[ ] MarketAux key rotated
[ ] Reddit client secret rotated
[ ] Neynar key rotated
[ ] Groq API key rotated
[ ] Telegram API hash rotated (if dedicated account)
[ ] Sentry DSN rotated (if suspected leak)
[ ] BitLocker recovery key verified still-accessible in password manager
[ ] Restart stack; /health/deep green
[ ] ONBOARDING.md row ticked
```
