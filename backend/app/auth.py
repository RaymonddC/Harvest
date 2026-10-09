"""Demo-mode sign-in: pick a role, get a signed token. There is no password.

The token only decides which planner actions the browser may call. Reads stay open (the data is
synthetic) and so does the farmer's call page. Swap `login` for a real identity check, such as
Firebase Auth, before any real data goes in; everything downstream only sees the token's role.
"""

from __future__ import annotations

import time

import jwt
from fastapi import Header, HTTPException

from .config import Settings

# role -> display name. "farmer" has no planner rights; it exists so the login page can route to the call client.
ROLES = ("planner", "viewer", "farmer")


def display_name(settings: Settings, role: str) -> str:
    return {"planner": settings.planner_name, "viewer": "Guest viewer", "farmer": "Farmer"}[role]


def mint_token(settings: Settings, role: str, *, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Return (token, expiry as a unix timestamp)."""
    if role not in ROLES:
        raise ValueError(f"Unknown role {role!r}.")
    now = int(time.time())
    exp = now + (settings.jwt_ttl_seconds if ttl_seconds is None else ttl_seconds)
    claims = {"sub": role, "role": role, "name": display_name(settings, role), "iat": now, "exp": exp}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256"), exp


def read_token(settings: Settings, authorization: str | None) -> dict:
    """Claims of a valid `Authorization: Bearer ...` header. 401 when missing, bad or expired."""
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(401, "Sign in first.")
    try:
        claims = jwt.decode(value.strip(), settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(401, "Your session expired. Sign in again.") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, "Sign in first.") from e
    if claims.get("role") not in ROLES:
        raise HTTPException(401, "Sign in first.")
    return claims


def planner_dependency(settings: Settings):
    """FastAPI dependency for every action that changes data: planner role only."""

    def require_planner(authorization: str | None = Header(default=None)) -> None:
        if not settings.auth_required:
            return
        claims = read_token(settings, authorization)
        if claims["role"] != "planner":
            raise HTTPException(403, "Only the planner role can do this. Switch role on the sign-in page.")

    return require_planner
