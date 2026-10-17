"""Segments, churn signals, notes with follow-ups, and payment of deliveries (crm.py)."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import crm, main, services, track_record
from app.main import create_app


def farmer(store):
    return next(f for f in store.list("farmers") if f.get("type", "farmer") == "farmer")


def test_segment_from_reliability_size_and_certification():
    assert crm.segment_of({"usual_kg_week": 1200, "certification": "RSPO"}, 0.95) == \
        {"reliability": "reliable", "size": "large", "certified": "yes"}
    assert crm.segment_of({"usual_kg_week": 700}, 0.7) == {"reliability": "mixed", "size": "medium", "certified": "no"}
    assert crm.segment_of({}, None)["reliability"] == "new" and crm.segment_of({}, 0.3)["reliability"] == "unreliable"
    assert crm.check_segment({"size": "large", "certified": "any"}) == {"size": "large"}
    with pytest.raises(crm.CrmError):
        crm.check_segment({"size": "huge"})


def test_a_campaign_aimed_at_a_segment_calls_only_those_farmers(store, settings):
    members = services.campaign_members(store, settings, "current")
    reasons = sorted(services.call_list(store, settings, members))
    big = set(reasons[:4])
    for f in members:
        store.set("farmers", f["id"], {"usual_kg_week": 1500 if f["id"] in big else 300}, merge=True)
    services.update_campaign(store, settings, "current", segment={"size": "large"})
    services.start_campaign(store, settings, "collect", "current")
    called = {c["farmer_id"] for c in store.list("calls") if c["status"] == "queued"}
    assert called == big
    services.stop_campaign(store, settings, "current")
    services.update_campaign(store, settings, "current", segment={})
    assert store.get("campaigns", "current")["segment"] is None


def test_churn_signals():
    today = dt.date(2026, 11, 20)
    missed = [{"kind": "collect", "status": "dropped", "outcome": "no_answer", "ended_at": f"2026-11-1{i}"} for i in (1, 2)]
    notes = [{"kind": "feedback", "rating": 2, "at": "2026-11-15"}]
    offers = [{"status": "approved", "deliver_week_start": "2026-11-02", "delivered_kg": 0}]
    keys = [s["key"] for s in crm.churn_signals({}, 0.4, missed, notes, offers, today)]
    assert keys == ["stopped_answering", "under_delivers", "unhappy", "selling_elsewhere"]
    assert crm.churn_signals({}, 0.95, [], [], [], today) == []
    complaint = [{"kind": "complaint", "text": "late payment", "done": False}]
    assert [s["key"] for s in crm.churn_signals({}, None, [], complaint, [], today)] == ["unhappy"]


def test_notes_follow_ups_and_feedback(store):
    f = farmer(store)
    n = crm.add_note(store, f["id"], "call", "Called about the harvest; call back Friday", follow_up_on="2026-11-06", by="Dewi")
    assert n["follow_up_on"] == "2026-11-06" and n["done"] is False and n["by"] == "Dewi"
    assert crm.set_note_done(store, n["id"], True, "Dewi")["done"] is True
    fb = crm.add_note(store, f["id"], "feedback", "", rating=4)
    assert fb["rating"] == 4
    with pytest.raises(crm.CrmError):
        crm.add_note(store, f["id"], "feedback", "", rating=9)
    with pytest.raises(crm.CrmError):
        crm.add_note(store, f["id"], "gossip", "x")
    assert crm.delete_note(store, fb["id"]) == {"deleted": fb["id"]}


def test_payment_of_a_delivery_and_the_unpaid_total(store, settings):
    f = farmer(store)
    d = track_record.record_delivery(store, settings, f["id"], 1000, dt.date.today().isoformat())
    o = crm.overview(store)
    assert o["unpaid"]["count"] >= 1
    paid = crm.set_paid(store, d["id"], True, "TRF-0042", "Dewi")
    assert paid["paid"] is True and paid["payment_ref"] == "TRF-0042"
    assert crm.overview(store)["unpaid"]["count"] == o["unpaid"]["count"] - 1
    assert crm.set_paid(store, d["id"], False)["payment_ref"] is None


def test_crm_api(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    f = farmer(store)
    with TestClient(create_app(settings, store)) as c:
        r = c.post(f"/api/farmers/{f['id']}/notes", json={"kind": "complaint", "text": "Paid late", "follow_up_on": "2026-11-09"})
        assert r.status_code == 200
        assert c.put(f"/api/notes/{r.json()['id']}/done", json={"done": True}).json()["done"] is True
        o = c.get("/api/crm?campaign=current").json()
        assert f["id"] in o["farmers"] and "segment" in o["farmers"][f["id"]]
        assert c.post("/api/farmers/nobody/notes", json={"kind": "note", "text": "x"}).status_code == 404
        assert c.put("/api/campaigns/current", json={"segment": {"size": "tiny"}}).status_code == 400
