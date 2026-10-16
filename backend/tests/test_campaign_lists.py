"""Several campaigns per crop, each with its own farmers; editing and removing campaigns; the calendar."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import calendar_view, main, services
from app.main import create_app


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(settings, store)) as c:
        yield c


def palm_ids(store, settings, cid):
    return {f["id"] for f in services.campaign_members(store, settings, cid)}


def test_farmers_from_before_campaign_lists_belong_to_their_crops_first_campaign(store, settings):
    members = palm_ids(store, settings, "current")
    assert "f01" in members and "b004" in members
    assert all(services.farmer_crop(settings, store.get("farmers", fid)) == "palm" for fid in members)


def test_second_palm_campaign_takes_its_own_farmers_and_forecast(client, store, settings):
    before = {r["label"]: r["expected_kg"] for r in store.list("forecast") if r.get("campaign_id") == "current"}
    services.record_harvest(store, settings, "f01", "palm", 1600, "2026-10-28", None)
    r = client.post("/api/campaigns", json={"crop": "palm", "name": "Palm, Kampar", "target_kg_per_week": 2000,
                                            "weeks": 3, "farmer_ids": ["f01", "f02"]})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert cid.startswith("palm-") and r.json()["name"] == "Palm, Kampar"
    assert palm_ids(store, settings, cid) == {"f01", "f02"}
    assert store.get("farmers", "f02")["to_call"] is True
    assert "f01" not in palm_ids(store, settings, "current")  # a farmer is in one campaign at a time
    rows = sorted((r for r in store.list("forecast") if r.get("campaign_id") == cid), key=lambda r: r["week"])
    assert [r["id"] for r in rows] == [f"{cid}-W1", f"{cid}-W2", f"{cid}-W3"]
    assert rows[2]["expected_kg"] == 1600  # f01's harvest (week 3) moved with them
    after = {r["label"]: r["expected_kg"] for r in store.list("forecast") if r.get("campaign_id") == "current"}
    assert after["W3"] <= before["W3"]


def test_start_calls_only_the_campaigns_farmers(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 3,
                                              "farmer_ids": ["f01", "b004"]}).json()["id"]  # b004 was not called before
    r = client.post(f"/api/campaigns/{cid}/start", json={"kind": "collect"})
    assert r.status_code == 200 and r.json()["queued"] == 2 and r.json()["campaign_id"] == cid
    calls = [c for c in store.list("calls") if c["status"] == "queued"]
    assert {c["farmer_id"] for c in calls} == {"f01", "b004"} and {c["campaign_id"] for c in calls} == {cid}
    assert store.get("campaigns", cid)["status"] == "running"
    assert store.get("campaigns", "current")["status"] != "running"


def test_move_farmers_in_and_out_and_refuse_another_crop(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 3}).json()["id"]
    fid = services.add_farmer(store, {"name": "Pak Karet", "phone": "+62 812 9999 0001", "crop": "rubber",
                                      "language": "Bahasa Indonesia"})
    r = client.put(f"/api/campaigns/{cid}/farmers", json={"add": ["f03", fid], "remove": []}).json()
    assert r["added"] == 1 and len(r["problems"]) == 1 and "Rubber" in r["problems"][0]
    assert client.put(f"/api/campaigns/{cid}/farmers", json={"remove": ["f03"]}).json()["removed"] == 1
    f03 = store.get("farmers", "f03")
    assert "campaign_id" in f03 and f03["campaign_id"] is None  # in the database, in no campaign
    assert "f03" not in palm_ids(store, settings, "current")


def test_add_farmer_to_a_campaign_or_to_the_database_only(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 3}).json()["id"]
    body = {"name": "Bu Baru", "phone": "+62 812 7777 0001", "crop": "palm", "language": "English"}
    fid = client.post("/api/farmers", json={**body, "campaign_id": cid}).json()["id"]
    assert store.get("farmers", fid)["campaign_id"] == cid
    fid2 = client.post("/api/farmers", json={**body, "phone": "+62 812 7777 0002", "campaign_id": ""}).json()["id"]
    assert store.get("farmers", fid2)["campaign_id"] is None
    client.put(f"/api/farmers/{fid}", json={**body, "village": "Kampar"})
    assert store.get("farmers", fid)["campaign_id"] == cid  # editing details keeps the campaign
    bad = client.post("/api/farmers", json={**body, "phone": "+62 812 7777 0003", "crop": "rubber", "campaign_id": cid})
    assert bad.status_code == 400
    csv = "name,phone,crop,language\nPak Satu,+62 812 7777 0004,palm,English"
    client.post("/api/farmers/upload", json={"csv": csv, "campaign_id": cid})
    assert any(f["name"] == "Pak Satu" for f in services.campaign_members(store, settings, cid))


def test_edit_and_delete_a_campaign(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 3,
                                              "farmer_ids": ["f01"]}).json()["id"]
    r = client.put(f"/api/campaigns/{cid}", json={"name": "Kampar", "target_kg_per_week": 3000, "weeks": 4})
    assert r.status_code == 200
    camp = store.get("campaigns", cid)
    assert camp["name"] == "Kampar" and camp["target_kg_per_week"] == 3000 and camp["weeks"] == 4
    assert len([r for r in store.list("forecast") if r.get("campaign_id") == cid]) == 4
    assert client.put(f"/api/campaigns/{cid}", json={"weeks": 13}).status_code == 400
    assert client.delete(f"/api/campaigns/{cid}").json()["farmers_freed"] == 1
    assert store.get("campaigns", cid) is None and store.get("farmers", "f01")["campaign_id"] is None
    assert not [r for r in store.list("forecast") if r.get("campaign_id") == cid]
    assert client.delete("/api/campaigns/current").status_code == 400  # the only one left


def test_agent_and_schedule_by_campaign_id(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 3}).json()["id"]
    client.put(f"/api/campaigns/{cid}/schedule", json={"enabled": True, "channel": "browser"})
    assert store.get("campaigns", cid)["weekly"]["enabled"] is True
    assert not (store.get("campaigns", "current").get("weekly") or {}).get("enabled")


def test_offer_counts_for_the_farmers_campaign(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 2000, "weeks": 5,
                                              "farmer_ids": ["f01"]}).json()["id"]
    o = services.create_offer(store, settings, farmer=store.get("farmers", "f01"), crop="palm", kg=500, price=3240,
                              deliver_week=2, call_id=None)
    assert o["campaign_id"] == cid
    imp = client.get(f"/api/approvals/impact?campaign={cid}").json()
    assert o["id"] in imp["offers"]
    assert o["id"] not in client.get("/api/approvals/impact?campaign=current").json()["offers"]


def test_calendar_lists_weeks_harvests_calls_deals_and_deliveries(client, store, settings):
    services.record_harvest(store, settings, "f01", "palm", 1600, "2026-10-28", None, "firm", 14)
    services.create_offer(store, settings, farmer=store.get("farmers", "f02"), crop="palm", kg=500, price=3240,
                          deliver_week=2, call_id=None)
    services.set_weekly_schedule(store, settings, "current", True)
    client.post("/api/deliveries", json={"farmer_id": "b004", "kg": 900, "date": "2026-10-14"})
    r = client.get("/api/calendar?start=2026-10-12&end=2026-11-15&campaign=current")
    assert r.status_code == 200
    ev = r.json()["events"]
    kinds = {e["type"] for e in ev}
    assert {"week", "harvest", "deal", "delivery", "call_plan"} <= kinds
    f01 = [e for e in ev if e["type"] == "harvest" and e["farmer_id"] == "f01"]
    assert [(e["date"], e["projected"]) for e in f01] == [("2026-10-28", False), ("2026-11-11", True)]
    assert client.get("/api/calendar?start=2026-10-19&end=2027-06-01").status_code == 400
    assert client.get("/api/calendar?start=nope&end=2026-11-01").status_code == 400


def test_calendar_planned_mondays_start_from_today(store, settings):
    services.set_weekly_schedule(store, settings, "current", True)
    out = calendar_view.events(store, settings, dt.date(2026, 10, 1), dt.date(2026, 10, 31), today=dt.date(2026, 10, 14))
    assert [e["date"] for e in out["events"] if e["type"] == "call_plan"] == ["2026-10-19", "2026-10-26"]
