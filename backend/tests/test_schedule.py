"""Automatic calls on chosen days at a chosen hour (Asia/Jakarta), run by the hourly job."""

import dataclasses
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import main, services
from app.main import create_app

WIB = services.SCHEDULE_TZ


def at(y, m, d, h):
    return dt.datetime(y, m, d, h, 5, tzinfo=WIB)


def test_campaign_starts_on_its_days_and_hour_only_once(store, settings):
    services.set_weekly_schedule(store, settings, "current", True, "browser", [1, 3], "07:00")  # Tue and Thu at 07:00
    w = store.get("campaigns", "current")["weekly"]
    assert w["days"] == [1, 3] and w["time"] == "07:00" and services.schedule_text(w) == "Tue, Thu at 07:00"
    assert services.scheduled_calls(store, settings, at(2026, 10, 20, 6))["started"] == []   # Tuesday 06:05: too early
    r = services.scheduled_calls(store, settings, at(2026, 10, 20, 7))                     # Tuesday 07:05
    assert [x["campaign_id"] for x in r["started"]] == ["current"]
    assert services.scheduled_calls(store, settings, at(2026, 10, 20, 7))["started"] == []   # same slot again: nothing
    assert services.scheduled_calls(store, settings, at(2026, 10, 21, 7))["started"] == []   # Wednesday


def test_bookkeeping_runs_once_a_week_from_monday_six(store, settings):
    assert "bookkeeping" not in services.scheduled_calls(store, settings, at(2026, 10, 19, 5))  # Monday 05:05
    assert "bookkeeping" in services.scheduled_calls(store, settings, at(2026, 10, 19, 6))
    assert "bookkeeping" not in services.scheduled_calls(store, settings, at(2026, 10, 20, 9))
    assert "bookkeeping" in services.scheduled_calls(store, settings, at(2026, 10, 27, 9))      # the next week


def test_bad_schedules_are_refused(store, settings):
    with pytest.raises(services.ServiceError, match="at least one day"):
        services.set_weekly_schedule(store, settings, "current", True, "browser", [], "06:00")
    with pytest.raises(services.ServiceError, match="on the hour"):
        services.set_weekly_schedule(store, settings, "current", True, "browser", [0], "06:30")
    with pytest.raises(services.ServiceError):
        services.set_weekly_schedule(store, settings, "current", True, "browser", [9], "06:00")


def test_api_schedule_and_job(settings, store, monkeypatch):
    s = dataclasses.replace(settings, job_token="secret")
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(s, store)) as c:
        r = c.put("/api/campaigns/current/schedule", json={"enabled": True, "channel": "browser", "days": [0, 1, 2, 3, 4], "time": "08:00"})
        assert r.status_code == 200 and r.json()["days"] == [0, 1, 2, 3, 4]
        assert services.schedule_text(store.get("campaigns", "current")["weekly"]) == "Monday to Friday at 08:00"
        assert c.post("/api/jobs/weekly", headers={"X-Job-Token": "secret"}).status_code == 200
        assert c.post("/api/jobs/weekly", headers={"X-Job-Token": "nope"}).status_code == 403
        assert c.post("/api/jobs/run-all", headers={"X-Job-Token": "secret"}).json()["started"]
