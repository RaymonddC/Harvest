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


def login(client, role):
    r = client.post("/api/auth/login", json={"role": role})
    assert r.status_code == 200
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
def test_other_roles_are_refused(client, role):
    r = client.post("/api/campaign/stop", headers=login(client, role))
    assert r.status_code == 403 and "planner" in r.json()["detail"]


def test_actions_need_a_valid_token(client, secured):
    assert client.post("/api/campaign/stop").status_code == 401
    assert client.post("/api/campaign/stop", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.post("/api/campaign/stop", headers={"Authorization": "Basic abc"}).status_code == 401
    forged, _ = auth.mint_token(dataclasses.replace(secured, jwt_secret="o" * 32), "planner")
    assert client.post("/api/campaign/stop", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_expired_token_is_refused(client, secured):
    token, _ = auth.mint_token(secured, "planner", ttl_seconds=-5)
    r = client.post("/api/campaign/stop", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_every_planner_action_is_protected(client):
    actions = [
        ("put", "/api/limits/palm", {"floor_price": 2900, "ceiling_price": 3350, "reference_price": 3100}),
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
    ]
    for method, path, body in actions:
        r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert r.status_code == 401, (method, path, r.status_code)


def test_reads_and_the_call_client_stay_open(client):
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/forecast.csv").status_code == 200
    assert client.get("/healthz").status_code == 200


def test_me_reports_the_signed_in_role(client):
    r = client.get("/api/auth/me", headers=login(client, "viewer")).json()
    assert r["role"] == "viewer" and r["name"] == "Guest viewer"
    assert client.get("/api/auth/me").status_code == 401


def test_auth_can_be_switched_off(settings, store):
    open_settings = dataclasses.replace(settings, auth_required=False)
    with TestClient(create_app(open_settings, store)) as c:
        assert c.post("/api/campaign/stop").status_code == 200
