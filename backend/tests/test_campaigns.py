"""One campaign per crop: create, forecast, start and stop each on its own."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import main, services
from app.main import create_app


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(settings, store)) as c:
        yield c


def make_rubber(client, target_t=40, weeks=3):
    return client.post("/api/campaigns", json={"crop": "rubber", "target_kg_per_week": target_t * 1000, "weeks": weeks})


def rubber_farmer(store, name="Pak Karet", phone="+62 812 0000 5555"):
    return services.add_farmer(store, {"name": name, "phone": phone, "crop": "rubber",
                                       "language": "Bahasa Indonesia", "village": "Lirik"})


def test_state_says_multi_crop_and_the_old_campaign_gets_its_crop(client, store, settings):
    store.set("campaigns", "current", {"status": "idle", "kind": None})  # as stored before crops existed
    services.recompute_forecast(store, settings)
    state = client.get("/api/state").json()
    assert state["settings"]["multi_crop"] is True
    current = next(c for c in state["campaigns"] if c["id"] == "current")
    assert current["crop"] == "palm" and current["weeks"] == 5 and current["target_kg_per_week"] > 0


def test_create_a_campaign_and_refuse_bad_ones(client):
    r = make_rubber(client)
    assert r.status_code == 200 and r.json()["id"] == "rubber" and r.json()["weeks"] == 3
    assert make_rubber(client).status_code == 409  # one campaign per crop
    assert client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 5000, "weeks": 5}).status_code == 409
    assert client.post("/api/campaigns", json={"crop": "tea", "target_kg_per_week": 5000, "weeks": 5}).status_code == 400
    assert client.post("/api/campaigns", json={"crop": "coffee", "target_kg_per_week": 0, "weeks": 5}).status_code == 400
    assert client.post("/api/campaigns", json={"crop": "coffee", "target_kg_per_week": 5000, "weeks": 13}).status_code == 400
    assert client.post("/api/campaigns", json={"crop": "karet", "target_kg_per_week": 1, "weeks": 1}).status_code == 409


def test_new_crop_has_its_own_forecast_and_palm_keeps_its_ids(client, store):
    make_rubber(client, target_t=40, weeks=3)
    rows = client.get("/api/state").json()["forecast"]
    palm = [r for r in rows if r["crop"] == "palm"]
    rubber = [r for r in rows if r["crop"] == "rubber"]
    assert sorted(r["id"] for r in palm) == ["W1", "W2", "W3", "W4", "W5"]  # unchanged ids for the default crop
    assert sorted(r["id"] for r in rubber) == ["rubber-W1", "rubber-W2", "rubber-W3"]
    assert {r["target_kg"] for r in rubber} == {40_000} and all(r["expected_kg"] == 0 for r in rubber)
    assert palm[0]["target_kg"] == 100_000


def test_a_harvest_only_moves_its_own_crops_forecast(client, store, settings):
    make_rubber(client)
    fid = rubber_farmer(store)
    palm_before = {r["id"]: r["expected_kg"] for r in store.list("forecast") if r["crop"] == "palm"}
    services.record_harvest(store, settings, fid, "rubber", 3000, "2026-10-14", None)
    assert store.get("forecast", "rubber-W1")["expected_kg"] == 3000
    assert {r["id"]: r["expected_kg"] for r in store.list("forecast") if r["crop"] == "palm"} == palm_before


def test_shorter_plan_has_fewer_weeks_and_the_cut_rows_are_removed(client, store, settings):
    make_rubber(client, weeks=3)
    assert store.get("forecast", "rubber-W4") is None
    store.set("campaigns", "rubber", {"weeks": 2}, merge=True)
    services.recompute_forecast(store, settings)
    assert store.get("forecast", "rubber-W3") is None and store.get("forecast", "rubber-W2") is not None


def test_start_calls_only_that_crops_farmers(client, store):
    make_rubber(client)
    fid = rubber_farmer(store)
    r = client.post("/api/campaigns/rubber/start", json={"kind": "collect"})
    assert r.status_code == 200 and r.json()["queued"] == 1 and r.json()["crop"] == "rubber"
    calls = [c for c in store.list("calls") if c["status"] == "queued"]
    assert [c["farmer_id"] for c in calls] == [fid]
    assert store.get("campaigns", "rubber")["status"] == "running"
    assert store.get("campaigns", "current")["status"] != "running"  # palm is untouched


def test_start_with_nobody_to_call_says_so(client):
    make_rubber(client)
    r = client.post("/api/campaigns/rubber/start", json={"kind": "collect"})
    assert r.status_code == 400 and "Rubber farmers" in r.json()["detail"]
    assert client.post("/api/campaigns/coffee/start", json={}).status_code == 400  # no such campaign


def test_gap_fill_for_a_crop_needs_a_gap_and_price_limits(client, store, settings):
    make_rubber(client, target_t=5)
    fid = rubber_farmer(store)
    services.record_harvest(store, settings, fid, "rubber", 100, "2026-10-28", None)  # week 2, far below the target
    r = client.post("/api/campaigns/rubber/start", json={"kind": "gap_fill"})
    assert r.status_code == 400 and "No price limits set for rubber" in r.json()["detail"]
    assert not [c for c in store.list("calls") if c["status"] == "queued"]  # nothing queued before the check


def test_legacy_endpoints_still_run_the_default_crop(client, store):
    r = client.post("/api/campaign/start", json={"kind": "collect"})
    assert r.status_code == 200 and r.json()["crop"] == "palm" and r.json()["queued"] > 0
    assert store.get("campaigns", "current")["status"] == "running"
    assert client.post("/api/campaign/stop").json() == {"status": "stopped", "crop": "palm"}
    assert client.post("/api/campaign/stop", json={"crop": "rubber"}).status_code == 400  # no rubber campaign yet
    make_rubber(client)
    assert client.post("/api/campaign/stop", json={"crop": "rubber"}).json()["crop"] == "rubber"
    assert store.get("campaigns", "rubber")["status"] == "stopped"


def test_the_kill_switch_refuses_new_campaigns(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    off = dataclasses.replace(settings, multi_crop=False)
    with TestClient(create_app(off, store)) as c:
        assert c.get("/api/state").json()["settings"]["multi_crop"] is False
        assert make_rubber(c).status_code == 400


def test_a_call_uses_its_crops_weeks_and_target(client, store, settings):
    make_rubber(client, target_t=40, weeks=3)
    s = services.settings_for_crop(store, settings, "Karet")  # an alias of rubber
    assert (s.weeks, s.target_kg_per_week) == (3, 40_000)
    assert services.settings_for_crop(store, settings, "palm").weeks == settings.weeks


def test_call_now_uses_the_farmers_crop_gap(client, store):
    make_rubber(client, target_t=5)
    fid = rubber_farmer(store)
    cid = services.call_now(store, fid, "collect")
    assert store.get("calls", cid)["gap_week"] is not None  # rubber has a gap in every empty week
