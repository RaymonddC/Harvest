"""Numbers added to the real-call allowlist from the dashboard."""

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


def test_a_number_added_in_the_dashboard_can_be_dialled(store, twilio, monkeypatch):
    placed = []
    monkeypatch.setattr(services, "_place_twilio_call", lambda st, s, cid, to: placed.append(to))
    fid = services.add_farmer(store, {"name": "Pak Baru", "phone": "+62 812 3456 7890", "crop": "palm", "language": "English"})
    with pytest.raises(services.ServiceError, match="not on the real-call allowlist"):
        services.dial_now(store, twilio, fid)
    doc = services.allow_number(store, twilio, "+62 812 3456 7890", "Pak Baru")
    assert doc["phone"] == "+6281234567890" and doc["farmer_id"] == fid  # linked to the farmer with that number
    services.dial_now(store, twilio, fid)
    assert placed == ["+6281234567890"]
    assert "2 numbers" in services.phone_calls_note(twilio, store)
    services.disallow_number(store, doc["id"])
    assert not services.number_allowed(store, twilio, "+6281234567890")
    assert services.number_allowed(store, twilio, "+628114617000")  # the server's list still applies


def test_cap_and_switch_off(store, twilio):
    small = dataclasses.replace(twilio, web_allowlist_max=1)
    services.allow_number(store, small, "+62 812 0000 0001")
    services.allow_number(store, small, "+62 812 0000 0001", "again")  # the same number again is fine
    with pytest.raises(services.ServiceError, match="full"):
        services.allow_number(store, small, "+62 812 0000 0002")
    with pytest.raises(services.ServiceError, match="turned off"):
        services.allow_number(store, dataclasses.replace(twilio, web_allowlist_max=0), "+62 812 0000 0003")
    with pytest.raises(services.ServiceError, match="does not look right"):
        services.allow_number(store, twilio, "12")


def test_texts_follow_the_same_allowlist(store, twilio):
    s = dataclasses.replace(twilio, messaging_channel="sms")
    assert "not on the allowlist" in messaging._why_not(store, s, "+6281299998888")
    services.allow_number(store, s, "+6281299998888")
    assert messaging._why_not(store, s, "+6281299998888") is None


def test_api_add_farmer_with_calls_allowed_and_remove(client, store):
    r = client.post("/api/farmers", json={"name": "Bu Telepon", "phone": "+62 813 1111 2222", "crop": "palm",
                                          "language": "English", "allow_calls": True})
    assert r.status_code == 200
    nums = store.list("allowed_numbers")
    assert [(n["phone"], n["farmer_id"]) for n in nums] == [("+6281311112222", r.json()["id"])]
    state = client.get("/api/state").json()
    assert state["settings"]["web_allowlist_max"] == 20 and state["settings"]["server_allowlist"] == ["+628114617000"]
    assert client.delete(f"/api/allowed-numbers/{nums[0]['id']}").status_code == 200
    assert client.post("/api/allowed-numbers", json={"phone": "+62 813 3333 4444", "label": "Office"}).status_code == 200
    assert client.delete("/api/allowed-numbers/n000").status_code == 404
