"""Auth router: single-user JWT against a bcrypt-hashed password in env."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, status

from pfip.api.deps import CurrentUser, SettingsDep
from pfip.core.contracts import CurrentUser as CurrentUserModel, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


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
    configured_email = settings.pfip_user_email.lower().strip()
    if body.email.lower().strip() != configured_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return _issue_token(configured_email, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(user: CurrentUser, settings: SettingsDep) -> TokenResponse:
    """Return a fresh token for the current authenticated user."""
    return _issue_token(user, settings)


@router.get("/me", response_model=CurrentUserModel)
async def me(user: CurrentUser) -> CurrentUserModel:
    """Return the current user identity."""
    return CurrentUserModel(email=user)
