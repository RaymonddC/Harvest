import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app


@pytest.fixture
def secured(settings):
    return dataclasses.replace(settings, auth_required=True, jwt_secret="t" * 32)


@pytest.fixture
def client(secured, store):
    with TestClient(create_app(secured, store)) as c:
        yield c


def login(client, role=None, user_id=None):
    r = client.post("/api/auth/login", json={"role": role} if role else {"user_id": user_id})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_returns_a_token_for_each_role(client):
    for role in ("planner", "viewer", "farmer"):
        body = client.post("/api/auth/login", json={"role": role}).json()
        assert body["role"] == role and body["token"] and body["exp"] > 0
    assert client.post("/api/auth/login", json={"role": "planner"}).json()["name"] == "Dewi"


def test_login_rejects_an_unknown_role(client):
    assert client.post("/api/auth/login", json={"role": "admin"}).status_code == 400


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


def test_login_by_user_and_the_people_list(client):
    people = client.get("/api/auth/people").json()["people"]
    assert {p["id"] for p in people} >= {"user-dewi", "user-budi", "user-guest", "user-farmer"}
    body = client.post("/api/auth/login", json={"user_id": "user-budi"}).json()
    assert body["name"] == "Budi" and body["role"] == "coordinator"
    assert body["capabilities"] == ["campaign.run", "farmers.manage"]
    assert client.post("/api/auth/login", json={"user_id": "nobody"}).status_code == 400
    assert client.post("/api/auth/login", json={}).status_code == 400


def test_coordinator_runs_campaigns_but_cannot_decide_or_change_prices(client):
    h = login(client, user_id="user-budi")
    assert client.post("/api/campaign/stop", headers=h).status_code == 200
    assert client.post("/api/offers/x/approve", headers=h).status_code == 403
    assert client.put("/api/limits/palm", headers=h, json={"floor_price": 1, "ceiling_price": 3, "reference_price": 2}).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403


def test_offer_records_who_approved_it(client, store):
    h = login(client, user_id="user-dewi")
    offer_id = client.post("/api/rival-quotes/rq01/offer", headers=h).json()["id"]
    client.post(f"/api/offers/{offer_id}/approve", headers=h)
    saved = store.get("offers", offer_id)
    assert saved["decided_by"] == "Dewi" and saved["decided_by_id"] == "user-dewi"


def test_turning_a_user_off_or_changing_their_role_takes_effect_at_once(client):
    admin = login(client, user_id="user-dewi")
    budi = login(client, user_id="user-budi")
    assert client.post("/api/campaign/stop", headers=budi).status_code == 200
    client.put("/api/users/user-budi", headers=admin, json={"name": "Budi", "role": "viewer", "active": True})
    assert client.post("/api/campaign/stop", headers=budi).status_code == 403
    client.put("/api/users/user-budi", headers=admin, json={"name": "Budi", "role": "viewer", "active": False})
    assert client.post("/api/campaign/stop", headers=budi).status_code == 401
    assert "user-budi" not in {p["id"] for p in client.get("/api/auth/people").json()["people"]}


def test_users_page_api(client, store):
    admin = login(client, user_id="user-dewi")
    listing = client.get("/api/users", headers=admin).json()
    assert {r["id"] for r in listing["roles"]} == {"planner", "coordinator", "viewer", "farmer"}
    assert "users.admin" in listing["capabilities"]
    made = client.post("/api/users", headers=admin, json={"name": "  Sari  Wulan ", "role": "coordinator"}).json()
    assert made["name"] == "Sari Wulan" and made["role"] == "coordinator" and made["active"] is True
    assert client.post("/api/users", headers=admin, json={"name": "", "role": "planner"}).status_code == 400
    assert client.post("/api/users", headers=admin, json={"name": "X", "role": "boss"}).status_code == 400
    assert client.delete(f"/api/users/{made['id']}", headers=admin).status_code == 200
    assert store.get("users", made["id"]) is None


def test_the_last_user_manager_cannot_be_removed_or_lose_the_right(client):
    admin = login(client, user_id="user-dewi")
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "viewer", "active": True})
    assert r.status_code == 400 and "keep the right to manage users" in r.json()["detail"]
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "planner", "active": False})
    assert r.status_code == 400
    r = client.delete("/api/users/user-dewi", headers=admin)
    assert r.status_code == 400  # also the account you are signed in with
    # with a second planner, the first may step down
    client.post("/api/users", headers=admin, json={"name": "Rina", "role": "planner"})
    r = client.put("/api/users/user-dewi", headers=admin, json={"name": "Dewi", "role": "viewer", "active": True})
    assert r.status_code == 200


def test_every_capability_is_enforced_by_some_endpoint():
    import re
    from pathlib import Path
    from app import access
    source = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    used = set(re.findall(r'need\("([a-z.]+)"\)', source))
    assert used == set(access.CAPABILITIES)


def test_reads_and_the_call_client_stay_open(client):
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/forecast.csv").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_me_reports_the_signed_in_role(client):
    r = client.get("/api/auth/me", headers=login(client, "viewer")).json()
    assert r["role"] == "viewer" and r["name"] == "Guest viewer" and r["capabilities"] == []
    assert client.get("/api/auth/me").status_code == 401


def test_auth_can_be_switched_off(settings, store):
    open_settings = dataclasses.replace(settings, auth_required=False)
    with TestClient(create_app(open_settings, store)) as c:
        assert c.post("/api/campaign/stop").status_code == 200
