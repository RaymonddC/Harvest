"""Demo-mode sign-in: pick a person, get a signed token. There is no password.

The token names a user. On every request the user and their role are read again from the store, so
turning a user off or changing their role takes effect at once. What a user may do comes from
`access.py` (capabilities held by their role). Reads stay open (the data is synthetic) and so does
the farmer's call page. Swap `login` for a real identity check, such as Firebase Auth, before any
real data goes in; the guards downstream only see a user id.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from fastapi import Header, HTTPException

from . import access
from .config import Settings
from .store import Store


@dataclass(frozen=True)
class Actor:
    id: str
    name: str
    role: str
    capabilities: frozenset[str]


def mint_token(settings: Settings, user: dict, *, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Return (token, expiry as a unix timestamp)."""
    now = int(time.time())
    exp = now + (settings.jwt_ttl_seconds if ttl_seconds is None else ttl_seconds)
    claims = {"sub": user["id"], "role": user["role"], "name": user["name"], "iat": now, "exp": exp}
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
    if not claims.get("sub"):
        raise HTTPException(401, "Sign in first.")
    return claims


def actor_for(store: Store, user: dict) -> Actor:
    return Actor(user["id"], user["name"], user["role"], frozenset(access.capabilities_of(store, user["role"])))


def current_actor(settings: Settings, store: Store, authorization: str | None) -> Actor:
    """The signed-in user as they are now. 401 when the account was removed or turned off."""
    access.ensure_defaults(store)
    claims = read_token(settings, authorization)
    user = store.get("users", claims["sub"])
    if not user or not user.get("active", True):
        raise HTTPException(401, "This account was removed or turned off. Sign in again.")
    return actor_for(store, user)


def demo_actor(store: Store) -> Actor:
    """Used when sign-in is switched off (local runs and tests): the first planner, with every right."""
    access.ensure_defaults(store)
    users = sorted((u for u in store.list("users") if u.get("active", True)), key=lambda u: u["id"])
    name = next((u["name"] for u in users if u["role"] == "planner"), "Planner")
    return Actor("demo", name, "planner", frozenset(access.CAPABILITIES))


def require(settings: Settings, store: Store, capability: str):
    """FastAPI dependency: the caller's role must hold `capability`. Returns the Actor."""
    if capability not in access.CAPABILITIES:
        raise ValueError(f"Unknown capability {capability!r}; declare it in access.py.")

    def guard(authorization: str | None = Header(default=None)) -> Actor:
        if not settings.auth_required:
            return demo_actor(store)
        actor = current_actor(settings, store, authorization)
        if capability not in actor.capabilities:
            raise HTTPException(403, f"Your role ({actor.role}) is not allowed to do this: "
                                     f"{access.CAPABILITIES[capability].lower()}. Switch user on the sign-in page.")
        return actor

    return guard
