# PFIP Login Credentials

## Default login

| Field | Value |
|---|---|
| **URL** | http://localhost:3000 |
| **Email** | `suresh.sahoo@cbcinc.ai` |
| **Password** | `pfip-local-2026` |

These are pre-set in your `.env` file. You can log in immediately once the stack is up.

---

## Change the password

Later, when you want a password you picked yourself:

```powershell
cd C:\Users\gaura\OneDrive\Desktop\PFIP_app
python .\scripts\make_password_hash.py
```

It prompts for a new password and prints a `$2b$12$...` hash. Copy the hash, then:

```powershell
notepad .env
```

Replace the value of `PFIP_USER_PASSWORD_HASH=` with the new hash. Save. Restart the backend:

```powershell
docker compose -f infra/docker-compose.yml restart backend
```

You can now log in with the new password.

---

## Change the email

Same file, same idea:

```powershell
notepad .env
```

Change `PFIP_USER_EMAIL=suresh.sahoo@cbcinc.ai` to whatever you prefer, save, restart backend.

---

## Rotate NEXTAUTH_SECRET (optional but recommended)

The default `NEXTAUTH_SECRET` was generated for you. To rotate it later:

```powershell
.\scripts\gen_nextauth_secret.ps1
```

Copy the output, paste into `.env` replacing the existing value, save, restart:

```powershell
docker compose -f infra/docker-compose.yml restart frontend backend
```

Rotating invalidates any active sessions — you'll need to log in again.
