"""Who may do what: capabilities, roles and users.

A CAPABILITY is one thing the system can permit. The set is closed and lives here, because each one
is checked by a guard on a real endpoint (`auth.require`); a test fails when one is not enforced.
A ROLE is data in the `roles` collection: a named bundle of capabilities. A USER is data in the
`users` collection: a name and one role. Approvals record the user who decided, not a setting.

The default roles and users are written once, when the collections are empty, and never overwritten,
so edits made on the Users page survive a redeploy.
"""

from __future__ import annotations

from .store import Store, new_id

CAPABILITIES: dict[str, str] = {
    "campaign.run": "Start and stop call campaigns, call a farmer now",
    "limits.edit": "Change the fair price range",
    "offers.decide": "Approve, reject or undo offers",
    "farmers.manage": "Add, edit, delete and upload farmers",
    "demo.reset": "Reset the demo data",
    "users.admin": "Add, change and remove users",
}

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

DEFAULT_USERS: list[tuple[str, str, str]] = [
    ("user-dewi", "Dewi", "planner"),
    ("user-budi", "Budi", "coordinator"),
    ("user-guest", "Guest viewer", "viewer"),
    ("user-farmer", "Farmer", "farmer"),
]


class AccessError(ValueError):
    """A users or roles change that is refused. The message says what to do instead."""


def ensure_defaults(store: Store) -> None:
    """Write the default roles and users when there are none. Never overwrites an edit."""
    if not store.list("roles"):
        for role_id, role in DEFAULT_ROLES.items():
            store.set("roles", role_id, {**role, "builtin": True})
    if not store.list("users"):
        for user_id, name, role in DEFAULT_USERS:
            store.set("users", user_id, {"name": name, "role": role, "active": True})


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


def add_user(store: Store, name: str, role: str) -> dict:
    user = {"name": _check_name(name), "role": _check_role(store, role), "active": True}
    user_id = new_id("user")
    store.set("users", user_id, user)
    return {**user, "id": user_id}


def update_user(store: Store, user_id: str, name: str, role: str, active: bool) -> dict:
    if not store.get("users", user_id):
        raise AccessError("User not found.")
    user = {"name": _check_name(name), "role": _check_role(store, role), "active": bool(active)}
    _must_keep_an_admin(store, user_id, user)
    store.set("users", user_id, user, merge=True)
    return {**user, "id": user_id}


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
            "role_label": role.get("label", user["role"]), "active": bool(user.get("active", True))}
