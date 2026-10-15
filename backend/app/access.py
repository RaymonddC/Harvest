"""Who may do what: capabilities, roles and users.

A CAPABILITY is one thing the system can permit. The set is closed and lives here, because each one
is checked by a guard on a real endpoint (`auth.require`); a test fails when one is not enforced.
A ROLE is data in the `roles` collection: a named bundle of capabilities. A USER is data in the
`users` collection: a name and one role. Approvals record the user who decided, not a setting.

The default roles and users are written once, when the collections are empty, and never overwritten,
so edits made on the Users page survive a redeploy.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from .store import Store, new_id

CAPABILITIES: dict[str, str] = {
    "campaign.run": "Start and stop call campaigns, call a farmer now",
    "limits.edit": "Change the fair price range",
    "offers.decide": "Approve, reject or undo offers",
    "farmers.manage": "Add, edit, delete and upload farmers",
    "demo.reset": "Reset the demo data",
    "users.admin": "Add, change and remove users",
    "calls.listen": "Listen to the recording of a call",
}

# Capabilities added after roles were first saved: the built-in role gets each one once (a planner who later
# takes it away is not given it again, because the grant is remembered on the role).
NEW_DEFAULT_GRANTS = [("planner", "calls.listen")]

DEFAULT_ROLES: dict[str, dict] = {
    "planner": {"label": "Planner", "capabilities": list(CAPABILITIES),
                "description": "The mill's planner. Runs campaigns, sets price limits, approves deals and manages users."},
    "coordinator": {"label": "Coordinator", "capabilities": ["campaign.run", "farmers.manage"],
                    "description": "Runs campaigns and keeps the farmer list, but cannot change prices or approve deals."},
    "viewer": {"label": "Viewer", "capabilities": [],
               "description": "A guest. Watches the forecast, offers and calls, but changes nothing."},
    "farmer": {"label": "Farmer", "capabilities": [],
               "description": "Answers the agent's phone calls in this browser, playing the farmer."},
}

# Roles that exist only so the hackathon demo can be explored: a guest who watches, and a stand-in for the
# farmer who answers the agent's call in the browser. Real farmers never sign in; the agent phones them.
# Kept in code (not in the stored role) so it also applies to roles already saved in Firestore.
DEMO_ROLES = frozenset({"viewer", "farmer"})

DEFAULT_USERS: list[tuple[str, str, str, str]] = [
    ("user-dewi", "Dewi", "planner", "dewi"),
    ("user-budi", "Budi", "coordinator", "budi"),
    ("user-guest", "Guest viewer", "viewer", "guest"),
    ("user-farmer", "Farmer", "farmer", "farmer"),
]
DEFAULT_USERNAMES = {user_id: username for user_id, _, _, username in DEFAULT_USERS}

# Passwords are stored as salted PBKDF2-SHA256 hashes, never as text.
PBKDF2_ROUNDS = 120_000
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


class AccessError(ValueError):
    """A users or roles change that is refused. The message says what to do instead."""


def ensure_defaults(store: Store) -> None:
    """Write the default roles and users when there are none. Never overwrites an edit."""
    if not store.list("roles"):
        for role_id, role in DEFAULT_ROLES.items():
            store.set("roles", role_id, {**role, "builtin": True})
    for role_id, cap in NEW_DEFAULT_GRANTS:
        role = store.get("roles", role_id)
        if role and role.get("builtin") and cap not in role.get("capabilities", []) and cap not in role.get("granted_defaults", []):
            store.set("roles", role_id, {"capabilities": [*role.get("capabilities", []), cap],
                                         "granted_defaults": [*role.get("granted_defaults", []), cap]}, merge=True)
    if not store.list("users"):
        for user_id, name, role, username in DEFAULT_USERS:
            store.set("users", user_id, {"name": name, "role": role, "active": True, "username": username})


def ensure_credentials(store: Store, demo_password: str) -> None:
    """Give every user a username, and the built-in demo accounts the demo password, once.

    Users from before passwords existed get a username made from their name. A built-in account
    with no password gets the demo password and is marked `demo_login`, so the sign-in page can
    offer it as a demo account; setting its own password on the Users page clears that mark.
    Other users without a password cannot sign in until someone gives them one.
    """
    ensure_defaults(store)
    taken = {u.get("username") for u in store.list("users") if u.get("username")}
    for user in sorted(store.list("users"), key=lambda u: u["id"]):
        changes = {}
        if not user.get("username"):
            base = DEFAULT_USERNAMES.get(user["id"]) or _slug(user.get("name", "")) or "user"
            name, n = base, 2
            while name in taken:
                name, n = f"{base}{n}", n + 1
            taken.add(name)
            changes["username"] = name
        if not user.get("password_hash") and demo_password and user["id"] in DEFAULT_USERNAMES:
            changes.update(password_hash=hash_password(demo_password), demo_login=True)
        if changes:
            store.set("users", user["id"], changes, merge=True)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", (name or "").lower()).strip(".")[:32]


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    try:
        scheme, rounds, salt, digest = (stored or "").split("$")
        if scheme != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(got.hex(), digest)
    except ValueError:
        return False


_DUMMY_HASH = hash_password("not-a-real-password")


def authenticate(store: Store, username: str, password: str) -> dict | None:
    """The active user with this username and password, or None. Unknown names take as long as
    wrong passwords, so the answer time does not tell which usernames exist."""
    wanted = (username or "").strip().lower()
    user = next((u for u in store.list("users") if u.get("username") == wanted and u.get("active", True)), None)
    if not user or not user.get("password_hash"):
        check_password(password or "", _DUMMY_HASH)
        return None
    return user if check_password(password or "", user["password_hash"]) else None


def get_role(store: Store, role_id: str) -> dict | None:
    return store.get("roles", role_id)


def capabilities_of(store: Store, role_id: str) -> set[str]:
    """What a role may do. An unknown role may do nothing."""
    role = get_role(store, role_id)
    return {c for c in (role or {}).get("capabilities", []) if c in CAPABILITIES}


def holds_users_admin(store: Store, user: dict) -> bool:
    return bool(user.get("active", True)) and "users.admin" in capabilities_of(store, user["role"])


def _check_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not 1 <= len(name) <= 60:
        raise AccessError("Give the user a name of 1 to 60 characters.")
    return name


def _check_username(store: Store, username: str, user_id: str | None) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AccessError("Give a username of 2 to 32 characters: lower-case letters, digits, dots, dashes "
                          "or underscores, starting with a letter or digit.")
    if any(u.get("username") == username and u["id"] != user_id for u in store.list("users")):
        raise AccessError(f"The username {username!r} is taken.")
    return username


def _check_password(password: str) -> str:
    if not 8 <= len(password or "") <= 200:
        raise AccessError("Give a password of at least 8 characters.")
    return password


def _check_role(store: Store, role: str) -> str:
    if not get_role(store, role):
        raise AccessError(f"Unknown role {role!r}.")
    return role


def _must_keep_an_admin(store: Store, changed_id: str, after: dict | None) -> None:
    """Refuse a change that would leave nobody able to manage users."""
    others = [u for u in store.list("users") if u["id"] != changed_id]
    if after is not None:
        others.append({**after, "id": changed_id})
    if not any(holds_users_admin(store, u) for u in others):
        raise AccessError("At least one active user must keep the right to manage users. "
                          "Give another user that role first.")


def add_user(store: Store, name: str, role: str, username: str, password: str) -> dict:
    user = {"name": _check_name(name), "role": _check_role(store, role), "active": True,
            "username": _check_username(store, username, None),
            "password_hash": hash_password(_check_password(password)), "demo_login": False}
    user_id = new_id("user")
    store.set("users", user_id, user)
    return {**user, "id": user_id}


def update_user(store: Store, user_id: str, name: str, role: str, active: bool,
                username: str | None = None, password: str | None = None) -> dict:
    """Change a user. A blank username or password keeps the current one."""
    current = store.get("users", user_id)
    if not current:
        raise AccessError("User not found.")
    user = {"name": _check_name(name), "role": _check_role(store, role), "active": bool(active)}
    if username:
        user["username"] = _check_username(store, username, user_id)
    if password:
        user.update(password_hash=hash_password(_check_password(password)), demo_login=False)
    _must_keep_an_admin(store, user_id, user)
    store.set("users", user_id, user, merge=True)
    return {**current, **user, "id": user_id}


def delete_user(store: Store, user_id: str, acting_id: str | None) -> None:
    if not store.get("users", user_id):
        raise AccessError("User not found.")
    if user_id == acting_id:
        raise AccessError("You cannot delete the account you are signed in with.")
    _must_keep_an_admin(store, user_id, None)
    store.delete("users", user_id)


def public_user(store: Store, user: dict) -> dict:
    role = get_role(store, user["role"]) or {}
    return {"id": user["id"], "name": user["name"], "role": user["role"],
            "role_label": role.get("label", user["role"]), "active": bool(user.get("active", True)),
            "demo": user["role"] in DEMO_ROLES, "username": user.get("username", ""),
            "has_password": bool(user.get("password_hash")), "demo_login": bool(user.get("demo_login"))}
