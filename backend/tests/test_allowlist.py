"""Who real calls may reach: farmers with Agent calls on (the toggle on each farmer), plus REAL_CALL_ALLOWLIST."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import main, messaging, services
from app.main import create_app


@pytest.fixture
def twilio(settings):
    return dataclasses.replace(settings, twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from_number="+18000000000",
                               public_base_url="https://example.test", real_calls_enabled=True,
                               real_call_allowlist=("+628114617000",))


@pytest.fixture
def client(twilio, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(twilio, store)) as c:
        yield c


def test_turning_agent_calls_on_lets_the_agent_phone_the_farmer(store, twilio, monkeypatch):
    placed = []
    monkeypatch.setattr(services, "_place_twilio_call", lambda st, s, cid, to: placed.append(to))
    fid = services.add_farmer(store, {"name": "Pak Baru", "phone": "+62 812 3456 7890", "crop": "palm", "language": "English"})
    with pytest.raises(services.ServiceError, match="Agent calls is off"):
        services.dial_now(store, twilio, fid)
    store.set("farmers", fid, {"agent_calls": True}, merge=True)
    services.dial_now(store, twilio, fid)
    assert placed == ["+6281234567890"]
    assert "2 numbers" in services.phone_calls_note(twilio, store)
    store.set("farmers", fid, {"agent_calls": False}, merge=True)
    assert not services.number_allowed(store, twilio, "+6281234567890")
    assert services.number_allowed(store, twilio, "+628114617000")  # the server's list still applies


def test_texts_follow_the_same_rule(store, twilio):
    s = dataclasses.replace(twilio, messaging_channel="sms")
    fid = services.add_farmer(store, {"name": "Bu Teks", "phone": "+62 812 9999 8888", "crop": "palm", "language": "English"})
    assert "not on the allowlist" in messaging._why_not(store, s, "+6281299998888")
    store.set("farmers", fid, {"agent_calls": True}, merge=True)
    assert messaging._why_not(store, s, "+6281299998888") is None


def test_api_add_farmer_with_agent_calls_and_toggle_it(client, store):
    r = client.post("/api/farmers", json={"name": "Bu Telepon", "phone": "+62 813 1111 2222", "crop": "palm",
                                          "language": "English", "agent_calls": True})
    assert r.status_code == 200 and store.get("farmers", r.json()["id"])["agent_calls"] is True
    fid = r.json()["id"]
    assert client.put(f"/api/farmers/{fid}/agent-calls", json={"agent_calls": False}).json()["agent_calls"] is False
    assert store.get("farmers", fid)["agent_calls"] is False
    assert client.put("/api/farmers/nobody/agent-calls", json={"agent_calls": True}).status_code == 404
    assert client.post("/api/allowed-numbers", json={"phone": "+62 813 3333 4444"}).status_code in (404, 405)
