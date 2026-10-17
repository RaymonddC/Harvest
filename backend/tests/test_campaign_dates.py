"""Campaigns run from a start date to an end date; the forecast shows week 1 (next week) to the end date."""

import pytest
from fastapi.testclient import TestClient

from app import calendar_view, main, services
from app.main import create_app


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(settings, store)) as c:
        yield c


def rows_of(store, cid):
    return sorted((r for r in store.list("forecast") if r.get("campaign_id") == cid), key=lambda r: r["week"])


def test_dates_set_the_weeks(client, store, settings):
    # Tests plan from Monday 12 Oct 2026 (week 1).
    r = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 5000,
                                            "start_date": "2026-10-12", "end_date": "2026-11-08"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    camp = store.get("campaigns", cid)
    assert camp["start_date"] == "2026-10-12" and camp["end_date"] == "2026-11-08" and camp["weeks"] == 4
    assert [x["label"] for x in rows_of(store, cid)] == ["W1", "W2", "W3", "W4"]


def test_weeks_before_a_later_start_never_count_as_short(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 5000,
                                              "start_date": "2026-10-26", "end_date": "2026-11-15"}).json()["id"]
    rows = rows_of(store, cid)
    assert [x["before_start"] for x in rows] == [True, True, False, False, False]
    assert not rows[0]["is_gap"] and rows[2]["is_gap"]


def test_bad_dates_are_refused(client):
    base = {"crop": "palm", "target_kg_per_week": 5000}
    assert client.post("/api/campaigns", json={**base, "start_date": "2026-11-10", "end_date": "2026-11-01"}).status_code == 400
    assert client.post("/api/campaigns", json={**base, "start_date": "2026-01-01", "end_date": "2026-02-01"}).status_code == 400
    assert client.post("/api/campaigns", json={**base, "start_date": "2026-11-01"}).status_code == 400
    assert client.post("/api/campaigns", json=base).status_code == 400
    assert client.post("/api/campaigns", json={**base, "start_date": "nope", "end_date": "2026-11-01"}).status_code == 400


def test_edit_dates_and_the_calendar_shows_them(client, store, settings):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 5000,
                                              "start_date": "2026-10-12", "end_date": "2026-11-01"}).json()["id"]
    assert client.put(f"/api/campaigns/{cid}", json={"start_date": "2026-10-12", "end_date": "2026-11-22"}).status_code == 200
    assert len(rows_of(store, cid)) == 6
    ev = calendar_view.events(store, settings, services._date("2026-10-01"), services._date("2026-11-30"), cid)["events"]
    assert [(e["type"], e["date"]) for e in ev if e["type"].startswith("campaign_")] == [
        ("campaign_start", "2026-10-12"), ("campaign_end", "2026-11-22")]


def test_a_long_campaign_shows_at_most_twelve_weeks(client, store):
    cid = client.post("/api/campaigns", json={"crop": "palm", "target_kg_per_week": 5000,
                                              "start_date": "2026-10-12", "end_date": "2027-06-30"}).json()["id"]
    assert len(rows_of(store, cid)) == 12


def test_older_campaigns_without_dates_keep_their_weeks(store, settings):
    assert len(rows_of(store, "current")) == settings.weeks
