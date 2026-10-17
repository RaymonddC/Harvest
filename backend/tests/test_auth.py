import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app


DEMO = "demo-pass-123"
USERNAMES = {"planner": "dewi", "coordinator": "budi", "viewer": "guest", "farmer": "farmer"}


@pytest.fixture
def secured(settings):
    return dataclasses.replace(settings, auth_required=True, jwt_secret="t" * 32, demo_password=DEMO)


@pytest.fixture
def client(secured, store):
    with TestClient(create_app(secured, store)) as c:
        yield c


def login(client, role=None, username=None, password=DEMO):
    r = client.post("/api/auth/login", json={"username": username or USERNAMES[role], "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_returns_a_token_for_each_built_in_account(client):
    for role, username in USERNAMES.items():
        body = client.post("/api/auth/login", json={"username": username, "password": DEMO}).json()
        assert body["role"] == role and body["token"] and body["exp"] > 0
    assert client.post("/api/auth/login", json={"username": " DEWI ", "password": DEMO}).json()["name"] == "Dewi"


def test_login_needs_the_right_password(client):
    for body in ({"username": "dewi", "password": "wrong-password"}, {"username": "nobody", "password": DEMO},
                 {"username": "dewi", "password": ""}, {}, {"role": "planner"}, {"user_id": "user-dewi"}):
        r = client.post("/api/auth/login", json=body)
        assert r.status_code == 401 and r.json()["detail"] == "Wrong username or password.", body


def test_planner_can_act(client):
    assert client.post("/api/campaign/stop", headers=login(client, "planner")).status_code == 200


@pytest.mark.parametrize("role", ["viewer", "farmer"])
def test_roles_without_rights_are_refused(client, role):
    r = client.post("/api/campaign/stop", headers=login(client, role))
    assert r.status_code == 403 and role in r.json()["detail"]


def test_actions_need_a_valid_token(client, secured):
    assert client.post("/api/campaign/stop").status_code == 401
    assert client.post("/api/campaign/stop", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.post("/api/campaign/stop", headers={"Authorization": "Basic abc"}).status_code == 401
    forged, _ = auth.mint_token(dataclasses.replace(secured, jwt_secret="o" * 32),
                                {"id": "user-dewi", "name": "Dewi", "role": "planner"})
    assert client.post("/api/campaign/stop", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token_is_refused(client, secured):
    token, _ = auth.mint_token(secured, {"id": "user-dewi", "name": "Dewi", "role": "planner"}, ttl_seconds=-5)
    r = client.post("/api/campaign/stop", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_every_planner_action_is_protected(client):
    actions = [
        ("put", "/api/limits/palm", {"floor_price": 2900, "ceiling_price": 3350, "reference_price": 3100}),
        ("post", "/api/farmers", {"name": "X", "phone": "+62 812 0000 1234", "crop": "palm", "language": "Bahasa Indonesia"}),
        ("put", "/api/farmers/f001", {"name": "X", "phone": "+62 812 0000 1234", "crop": "palm", "language": "Bahasa Indonesia"}),
        ("delete", "/api/farmers/f001", None),
        ("post", "/api/farmers/upload", {"csv": "name,phone,crop,language\n"}),
        ("post", "/api/campaign/start", {"kind": "collect"}),
        ("post", "/api/campaign/stop", None),
        ("post", "/api/farmers/f001/call", {}),
        ("post", "/api/farmers/f001/dial", {}),
        ("post", "/api/offers/x/approve", None),
        ("post", "/api/offers/x/reject", None),
        ("post", "/api/offers/x/undo", None),
        ("post", "/api/rival-quotes/x/offer", None),
        ("post", "/api/forecast/recompute", None),
        ("post", "/api/demo/reset", None),
        ("get", "/api/users", None),
        ("post", "/api/users", {"name": "X", "role": "viewer"}),
        ("put", "/api/users/user-guest", {"name": "X", "role": "viewer", "active": True}),
        ("delete", "/api/users/user-guest", None),
    ]
    for method, path, body in actions:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert r.status_code == 401, (method, path, r.status_code)


def test_demo_accounts_and_login_by_username(client):
    demo = client.get("/api/auth/demo").json()
    assert demo["password"] == DEMO
    assert [a["username"] for a in demo["accounts"]] == ["dewi", "budi", "guest", "farmer"]
    assert {a["id"] for a in demo["accounts"] if a["demo"]} == {"user-farmer", "user-guest"}
    assert all("password_hash" not in a for a in demo["accounts"])
    body = client.post("/api/auth/login", json={"username": "budi", "password": DEMO}).json()
    assert body["name"] == "Budi" and body["role"] == "coordinator"
    assert body["capabilities"] == ["campaign.run", "farmers.manage"]


def test_passwords_are_stored_hashed_and_a_new_password_ends_the_demo_login(client, store):
    login(client, "planner")  # the first sign-in gives the built-in accounts their credentials
    saved = store.get("users", "user-budi")
    assert saved["username"] == "budi" and saved["demo_login"] is True
    assert DEMO not in saved["password_hash"] and saved["password_hash"].startswith("pbkdf2_sha256$")
    admin = login(client, "planner")
    r = client.put("/api/users/user-budi", headers=admin,
                   json={"name": "Budi", "role": "coordinator", "active": True, "password": "budi-own-pass"})
    assert r.status_code == 200 and "password_hash" not in r.json()
    assert client.post("/api/auth/login", json={"username": "budi", "password": DEMO}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "budi", "password": "budi-own-pass"}).status_code == 200
    assert "budi" not in [a["username"] for a in client.get("/api/auth/demo").json()["accounts"]]
    # a blank password on an edit keeps the current one
    client.put("/api/users/user-budi", headers=admin, json={"name": "Budi B", "role": "coordinator", "active": True})
    assert client.post("/api/auth/login", json={"username": "budi", "password": "budi-own-pass"}).status_code == 200


def test_an_empty_demo_password_turns_the_demo_accounts_off(settings, store):
    closed = dataclasses.replace(settings, auth_required=True, jwt_secret="t" * 32, demo_password="")
    with TestClient(create_app(closed, store)) as c:
        assert c.get("/api/auth/demo").json() == {"password": "", "accounts": []}
        assert c.post("/api/auth/login", json={"username": "dewi", "password": ""}).status_code == 401


def test_older_users_get_a_username_but_no_password(client, store):
    store.set("users", "user-old", {"name": "Old Timer", "role": "viewer", "active": True})
    client.get("/api/auth/demo")
    old = store.get("users", "user-old")
    assert old["username"] == "old.timer" and not old.get("password_hash")
    assert client.post("/api/auth/login", json={"username": "old.timer", "password": DEMO}).status_code == 401


def test_coordinator_runs_campaigns_but_cannot_decide_or_change_prices(client):
    h = login(client, "coordinator")
    assert client.post("/api/campaign/stop", headers=h).status_code == 200
    assert client.post("/api/offers/x/approve", headers=h).status_code == 403
    assert client.put("/api/limits/palm", headers=h, json={"floor_price": 1, "ceiling_price": 3, "reference_price": 2}).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403


def test_offer_records_who_approved_it(client, store):
    h = login(client, "planner")
    offer_id = client.post("/api/rival-quotes/rq01/offer", headers=h).json()["id"]
    client.post(f"/api/offers/{offer_id}/approve", headers=h)
    saved = store.get("offers", offer_id)
    assert saved["decided_by"] == "Dewi" and saved["decided_by_id"] == "user-dewi"


def test_turning_a_user_off_or_changing_their_role_takes_effect_at_once(client):
    admin = login(client, "planner")
    budi = login(client, "coordinator")
    assert client.post("/api/campaign/stop", headers=budi).status_code == 200
    client.put("/api/users/user-budi", headers=admin, json={"name": "Budi", "role": "viewer", "active": True})
    assert client.post("/api/campaign/stop", headers=budi).status_code == 403
    client.put("/api/users/user-budi", headers=admin, json={"name": "Budi", "role": "viewer", "active": False})
    assert client.post("/api/campaign/stop", headers=budi).status_code == 401
    assert "user-budi" not in {a["id"] for a in client.get("/api/auth/demo").json()["accounts"]}
    assert client.post("/api/auth/login", json={"username": "budi", "password": DEMO}).status_code == 401


def test_users_page_api(client, store):
    admin = login(client, "planner")
    listing = client.get("/api/users", headers=admin).json()
    assert {r["id"] for r in listing["roles"]} == {"planner", "coordinator", "viewer", "farmer"}
    assert "users.admin" in listing["capabilities"]
    new = {"name": "  Sari  Wulan ", "role": "coordinator", "username": "Sari", "password": "sari-pass-1"}
    made = client.post("/api/users", headers=admin, json=new).json()
    assert made["name"] == "Sari Wulan" and made["role"] == "coordinator" and made["active"] is True
    assert made["username"] == "sari" and made["has_password"] is True and "password_hash" not in made
    assert client.post("/api/auth/login", json={"username": "sari", "password": "sari-pass-1"}).status_code == 200
    for bad in ({"name": "", "role": "planner"}, {"name": "X", "role": "boss"},
                {"name": "X", "role": "viewer", "username": "sari", "password": "long-enough"},  # taken
                {"name": "X", "role": "viewer", "username": "x y", "password": "long-enough"},  # bad characters
                {"name": "X", "role": "viewer", "username": "xavier", "password": "short"}):
        assert client.post("/api/users", headers=admin, json={"username": "ok.name", "password": "long-enough", **bad}).status_code == 400, bad
    assert client.delete(f"/api/users/{made['id']}", headers=admin).status_code == 200
    assert store.get("users", made["id"]) is None


def test_the_last_user_manager_cannot_be_removed_or_lose_the_right(client):
    admin = login(client, "planner")
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "viewer", "active": True})
    assert r.status_code == 400 and "keep the right to manage users" in r.json()["detail"]
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "planner", "active": False})
    assert r.status_code == 400
    r = client.delete("/api/users/user-dewi", headers=admin)
    assert r.status_code == 400  # also the account you are signed in with
    # with a second planner, the first may step down
    client.post("/api/users", headers=admin, json={"name": "Rina", "role": "planner", "username": "rina", "password": "rina-pass-1"})
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "viewer", "active": True})
    assert r.status_code == 200


def test_every_capability_is_enforced_by_some_endpoint():
    import re
    from pathlib import Path
    from app import access
    source = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    used = set(re.findall(r'need\("([a-z.]+)"\)', source))
    assert used == set(access.CAPABILITIES)


def test_every_read_needs_a_sign_in_but_any_signed_in_user_may_read(client):
    """AUDIT.md A1: the live data holds farmer phone numbers and transcripts, so nothing under /api is open any more."""
    for path in ("/api/state", "/api/forecast.csv", "/api/crm", "/api/calendar", "/api/track-record", "/api/answers.csv",
                 "/api/traceability.csv", "/api/surplus?week=1", "/api/approvals/impact", "/api/supply"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/stream").status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    viewer = login(client, "viewer")
    assert client.get("/api/state", headers=viewer).status_code == 200
    assert client.get("/api/forecast.csv", headers=viewer).status_code == 200
    assert client.get("/healthz").status_code == 200 and client.get("/config.js").status_code == 200
    assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 401  # reachable, just wrong


def test_the_401_carries_cors_headers_so_the_browser_can_read_it(client):
    r = client.get("/api/state", headers={"Origin": "https://example.web.app"})
    assert r.status_code == 401 and r.headers.get("access-control-allow-origin")


def test_me_reports_the_signed_in_role(client):
    r = client.get("/api/auth/me", headers=login(client, "viewer")).json()
    assert r["role"] == "viewer" and r["name"] == "Guest viewer" and r["capabilities"] == []
    assert client.get("/api/auth/me").status_code == 401


def test_auth_can_be_switched_off(settings, store):
    open_settings = dataclasses.replace(settings, auth_required=False)
    with TestClient(create_app(open_settings, store)) as c:
        assert c.post("/api/campaign/stop").status_code == 200
