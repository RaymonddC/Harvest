import dataclasses
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import services, track_record
from app.main import create_app

from .conftest import PLAN_START


def test_seed_history_gives_accuracy_and_reliability(store, settings):
    s = track_record.summary(store, settings)
    assert len(s["weeks"]) == 4 and 0.7 < s["accuracy"] < 1
    assert s["farmers_rated"] == 40 and s["reliable"] >= 25 and s["unreliable"] >= 3
    # The forecast keeps what farmers said; the likely figure is lower where unreliable farmers deliver.
    rows = {r["id"]: r["expected_kg"] for r in store.list("forecast") if r.get("week")}
    assert all(s["likely"][w] <= rows[w] for w in rows) and any(s["likely"][w] < rows[w] for w in rows)


def test_promises_snapshot_and_deliveries_make_a_farmer_record(store, settings):
    week = PLAN_START - dt.timedelta(days=7)  # a week with no seed history
    services.record_harvest(store, settings, "f01", "palm", 1000, (week + dt.timedelta(days=2)).isoformat(), None)
    assert track_record.snapshot_promises(store, settings, week) >= 1
    assert track_record.snapshot_promises(store, settings, week) == 0  # never overwritten
    track_record.record_delivery(store, settings, "f01", 600, (week + dt.timedelta(days=3)).isoformat(), "Dewi")
    rec = track_record.farmer_record(store, "f01")
    assert rec["weeks"] == [{"week_start": week.isoformat(), "crop": "palm", "promised": 1000, "delivered": 600}]
    assert rec["reliability"] is None  # one week is not a track record yet
    with pytest.raises(services.ServiceError):
        track_record.record_delivery(store, settings, "f01", 10, (dt.date.today() + dt.timedelta(days=5)).isoformat())


def test_reliability_after_two_weeks_and_missing_delivery_counts_as_zero(store, settings):
    for k, delivered in ((2, 1000), (3, None)):
        week = PLAN_START - dt.timedelta(days=7 * k)
        store.set("promises", f"p-f02-palm-{week}", {"farmer_id": "f02", "crop": "palm", "week_start": week.isoformat(), "kg": 1000})
        if delivered:
            track_record.record_delivery(store, settings, "f02", delivered, week.isoformat())
    # Week 3 back has seed deliveries from other farmers, so f02's missing delivery counts as nothing delivered.
    assert track_record.farmer_record(store, "f02")["reliability"] == 0.5


def test_delivery_csv_upload_matches_farmers_by_phone_or_name(store, settings):
    phone = store.get("farmers", "f01")["phone"]
    day = (PLAN_START - dt.timedelta(days=4)).isoformat()
    csv = f"phone,name,date,kg\n{phone},,{day},700\n,Bu Wati,{day},\"1,200\"\n,Nobody,{day},5\n"
    r = track_record.upload_deliveries(store, settings, csv, "Dewi")
    assert r["added"] == 2 and "line 4" in r["problems"][0]
    with pytest.raises(services.ServiceError):
        track_record.upload_deliveries(store, settings, "a,b\n1,2")


def test_track_record_endpoints(settings, store):
    with TestClient(create_app(settings, store)) as c:
        assert c.get("/api/track-record").json()["farmers_rated"] == 40
        day = (PLAN_START - dt.timedelta(days=4)).isoformat()
        d = c.post("/api/deliveries", json={"farmer_id": "f01", "kg": 500, "date": day}).json()
        assert d["kg"] == 500 and c.get("/api/farmers/f01/track-record").json()["deliveries"][0]["id"] == d["id"]
        assert c.delete(f"/api/deliveries/{d['id']}").status_code == 200
        assert c.post("/api/deliveries", json={"farmer_id": "nope", "kg": 5, "date": day}).status_code == 400


# ---------- rolling weeks and the Monday job ----------

def test_weeks_roll_forward_and_offers_keep_their_calendar_week(store, settings):
    s = dataclasses.replace(settings, plan_start_auto=True)
    offer = services.create_offer(store, s, farmer=store.get("farmers", "b001"), crop="palm", kg=1600, price=3300,
                                  deliver_week=3, call_id=None)
    services.decide_offer(store, s, offer["id"], approve=True)
    rolled = services.roll_weeks(store, s, today=PLAN_START + dt.timedelta(days=1))  # Tuesday of week 1
    assert rolled.plan_start == PLAN_START + dt.timedelta(days=7)
    row = next(r for r in store.list("forecast") if r.get("week_start") == offer["deliver_week_start"])
    assert row["label"] == "W2" and row["approved_in_kg"] == 1600
    assert services.roll_weeks(store, settings, today=PLAN_START + dt.timedelta(days=30)) is settings  # pinned


def test_weekly_job_snapshots_promises_and_starts_weekly_campaigns(store, settings):
    services.set_weekly_schedule(store, settings, "palm", True, "browser")
    r = services.weekly_job(store, settings)
    assert r["started"] == [{"crop": "palm", "campaign_id": "current", "queued": 12, "channel": "browser"}]
    again = services.weekly_job(store, settings)
    assert again["started"] == [] and again["skipped"][0]["why"] == "already calling"
    with pytest.raises(services.ServiceError):
        services.set_weekly_schedule(store, settings, "palm", True, "fax")


def test_weekly_job_endpoint_needs_the_token(settings, store):
    with TestClient(create_app(settings, store)) as c:
        assert c.post("/api/jobs/weekly").status_code == 404  # no JOB_TOKEN: off
    with TestClient(create_app(dataclasses.replace(settings, job_token="t0ken"), store)) as c:
        assert c.post("/api/jobs/weekly", headers={"X-Job-Token": "wrong"}).status_code == 403
        assert c.post("/api/jobs/weekly", headers={"X-Job-Token": "t0ken"}).status_code == 200


# ---------- what approving would do ----------

def test_approval_impact_shows_weeks_cost_and_a_new_gap(store, settings):
    for fid, kg in (("f01", 1600), ("f02", 1400)):
        services.record_harvest(store, settings, fid, "palm", kg, "2026-11-02", None)
    a = services.create_offer(store, settings, farmer=store.get("farmers", "f01"), crop="palm", kg=1600, price=3300,
                              deliver_week=3, call_id=None)
    rival = services.offer_from_rival_quote(store, settings, "rq01")
    imp = services.approval_impact(store, settings, "palm")
    one = imp["offers"][a["id"]]
    assert {"label": "W3", "before_kg": 61000, "after_kg": 62600, "was_gap": True, "is_gap": True} in one["weeks"]
    assert any(w["label"] == "W4" and w["after_kg"] == w["before_kg"] - 1600 for w in one["weeks"])
    assert one["cost"] == 3300 * 1600 and one["premium"] == (3300 - 3100) * 1600 and one["vs_rival_per_kg"] == 20
    assert imp["offers"][rival["id"]]["vs_rival_per_kg"] is None
    assert imp["all_pending"]["new_gaps"] == []
    # Pulling a big volume out of week 4 would open a gap there: the impact says so before approval.
    big = services.create_offer(store, settings, farmer=store.get("farmers", "s01"), crop="palm", kg=1, price=3300,
                                deliver_week=3, call_id=None)
    store.set("offers", big["id"], {"kg": 30000, "from_week": 4, "from_week_start": "2026-11-02"}, merge=True)
    assert services.approval_impact(store, settings, "palm")["offers"][big["id"]]["new_gaps"] == ["W4"]
