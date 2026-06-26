"""Auth router: single-user JWT against a bcrypt-hashed password in env.

Login is protected by a Redis-backed failed-attempt lockout (brute-force
defense — the app is internet-exposed via Tailscale Funnel). After
``_MAX_FAILS`` failures for an email within ``_WINDOW_S`` seconds, further
attempts get HTTP 429 with ``Retry-After`` until the window expires. A
successful login clears the counter. The limiter is **fail-open**: if Redis is
unavailable it never blocks a legitimate login.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, status
from loguru import logger

from pfip.api.deps import CurrentUser, SettingsDep
from pfip.core.contracts import CurrentUser as CurrentUserModel, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Login brute-force lockout (Redis-backed, fail-open) -------------------
_MAX_FAILS = 8  # failures allowed within the window before lockout
_WINDOW_S = 900  # 15-minute sliding lockout window
_redis_client = None  # lazy singleton (redis.asyncio.Redis)


def _get_redis(settings: SettingsDep):
    """Lazy async Redis client for rate-limit counters; None if unavailable."""
    global _redis_client
    if _redis_client is None:
        try:
            from redis.asyncio import Redis

            _redis_client = Redis.from_url(
                settings.redis_url, socket_connect_timeout=2, decode_responses=True
            )
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning(f"auth rate-limit: redis init failed (fail-open): {exc}")
            return None
    return _redis_client


def _fail_key(email: str) -> str:
    return f"auth:fail:{email.lower().strip()}"


async def _enforce_lockout(settings: SettingsDep, email: str) -> None:
    """Raise 429 if this email is currently locked out. Fail-open on Redis error."""
    r = _get_redis(settings)
    if r is None:
        return
    key = _fail_key(email)
    try:
        n = await r.get(key)
        if n is not None and int(n) >= _MAX_FAILS:
            ttl = await r.ttl(key)
            retry = max(int(ttl), 1) if ttl and ttl > 0 else _WINDOW_S
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(retry)},
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning(f"auth rate-limit: check failed (fail-open): {exc}")


async def _record_failure(settings: SettingsDep, email: str) -> None:
    r = _get_redis(settings)
    if r is None:
        return
    key = _fail_key(email)
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, _WINDOW_S)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning(f"auth rate-limit: record failed: {exc}")


async def _clear_failures(settings: SettingsDep, email: str) -> None:
    r = _get_redis(settings)
    if r is None:
        return
    try:
        await r.delete(_fail_key(email))
    except Exception:  # noqa: BLE001 — best-effort
        pass


def _issue_token(email: str, settings: SettingsDep) -> TokenResponse:
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_access_token_ttl_minutes)
    payload = {
        "sub": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.nextauth_secret, algorithm=settings.jwt_algorithm)
    return TokenResponse(token=token, expiresAt=exp)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, settings: SettingsDep) -> TokenResponse:
    """Exchange email+password for a JWT.

    Credentials are compared against ``PFIP_USER_EMAIL`` and
    ``PFIP_USER_PASSWORD_HASH`` (bcrypt) from env.
    """
    submitted_email = body.email.lower().strip()
    # Brute-force guard first: a locked-out email gets 429 before any cred work.
    await _enforce_lockout(settings, submitted_email)

    configured_email = settings.pfip_user_email.lower().strip()
    if submitted_email != configured_email:
        await _record_failure(settings, submitted_email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    hashed = settings.pfip_user_password_hash.strip()
    if not hashed:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PFIP_USER_PASSWORD_HASH is not configured",
        )
    try:
        ok = bcrypt.checkpw(body.password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid stored password hash: {exc}",
        ) from exc
    if not ok:
        await _record_failure(settings, submitted_email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    await _clear_failures(settings, submitted_email)
    return _issue_token(configured_email, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(user: CurrentUser, settings: SettingsDep) -> TokenResponse:
    """Return a fresh token for the current authenticated user."""
    return _issue_token(user, settings)


@router.get("/me", response_model=CurrentUserModel)
async def me(user: CurrentUser) -> CurrentUserModel:
    """Return the current user identity."""
    return CurrentUserModel(email=user)
