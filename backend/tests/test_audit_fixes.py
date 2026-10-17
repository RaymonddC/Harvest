"""Fixes from the 16 Oct audit (AUDIT.md) that are not about access or Twilio."""
import dataclasses
import datetime as dt

import pytest

from app import config, rules_engine, services
from app.tools import CallSession, ToolHandlers

from .test_tools import make


# ---------- tools ----------

def test_a_tool_that_blows_up_returns_an_error_instead_of_ending_the_call(store, settings, monkeypatch):
    h, _ = make(store, settings)

    def boom(self):
        raise KeyError("store hiccup")

    monkeypatch.setattr(ToolHandlers, "_tool_get_farmer", boom)
    r = h.dispatch("get_farmer", {})
    assert "error" in r and "KeyError" in r["error"]


@pytest.mark.parametrize("crop", ["a/b", "", "x" * 60])
def test_a_crop_name_that_would_break_a_document_id_is_refused(store, settings, crop):
    h, _ = make(store, settings)
    before = len(store.list("harvests"))
    r = h.dispatch("record_harvest", {"crop": crop, "kg": 1000, "ready_date": "2026-11-02", "confirmed_by_farmer": False})
    assert "error" in r and len(store.list("harvests")) == before


@pytest.mark.parametrize("kg", [float("nan"), float("inf"), -5, 0])
def test_a_harvest_volume_must_be_a_real_positive_number(store, settings, kg):
    h, _ = make(store, settings)
    r = h.dispatch("record_harvest", {"crop": "palm", "kg": kg, "ready_date": "2026-11-02", "confirmed_by_farmer": False})
    assert "error" in r


def test_check_offer_calls_nan_an_invalid_volume(store):
    limits = services.get_limits(store, "palm")
    d = rules_engine.check_offer(limits, -1, float("nan"), None)
    assert d.decision == "invalid"


def test_an_offer_cannot_be_saved_for_more_kilograms_than_were_priced(store, settings):
    h, _ = make(store, settings, farmer_id="b001", kind="gap_fill")
    h.dispatch("check_offer", {"crop": "palm", "kg": 1600})
    r = h.dispatch("save_offer", {"crop": "palm", "kg": 150000, "price_per_kg": 3220})
    assert "error" in r and not store.list("offers")
    assert h.dispatch("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3220})["saved"] is True


def test_create_offer_refuses_a_nonsense_volume(store, settings):
    farmer = store.get("farmers", "b001")
    for kg in (-1, 0, float("nan"), 10**9):
        with pytest.raises(services.ServiceError):
            services.create_offer(store, settings, farmer=farmer, crop="palm", kg=kg, price=3220, deliver_week=3, call_id=None)


# ---------- farmers and calls ----------

def test_adding_the_same_phone_again_keeps_do_not_call(store, settings):
    farmer = store.get("farmers", "f01")
    row = {"id": "", "name": farmer["name"], "phone": farmer["phone"], "crop": "palm", "language": "Bahasa Indonesia"}
    fid = services.add_farmer(store, dict(row), settings=settings)
    store.set("farmers", fid, {"do_not_call": True, "to_call": False}, merge=True)
    again = services.add_farmer(store, dict(row), settings=settings)
    assert again == fid and store.get("farmers", fid)["do_not_call"] is True and store.get("farmers", fid)["to_call"] is False


def test_a_retry_call_stays_in_its_campaign(store, settings):
    farmer = store.get("farmers", "b001")
    cid = services.queue_call(store, farmer, "gap_fill", gap_week=3, campaign_id="current", gap_start="2026-11-02")
    services.finish_call(store, settings, cid, ended_cleanly=False, outcome=None, summary=None, consent=False, transcript=[])
    retry = [c for c in store.list("calls") if c.get("attempt") == 2][0]
    assert retry["campaign_id"] == "current" and retry["gap_week_start"] == "2026-11-02"


def test_a_call_finds_its_short_week_by_date_after_the_weeks_roll(store, settings):
    call = {"gap_week": 3, "gap_week_start": (settings.plan_start + dt.timedelta(days=14)).isoformat()}
    assert services.call_gap_week(call, settings) == 3
    rolled = dataclasses.replace(settings, plan_start=settings.plan_start + dt.timedelta(days=7))  # Monday came
    assert services.call_gap_week(call, rolled) == 2
    assert services.call_gap_week({"gap_week": 4}, rolled) == 4  # an old call without a date keeps its number


def test_calls_left_on_the_line_by_a_restart_are_closed_and_free_the_campaign(store, settings):
    farmer = store.get("farmers", "f01")
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat()
    cid = services.queue_call(store, farmer, "collect")
    store.set("calls", cid, {"status": "on_call", "started_at": old}, merge=True)
    fresh = services.queue_call(store, store.get("farmers", "f02"), "collect")
    phone = services.queue_call(store, store.get("farmers", "f03"), "collect", channel="twilio")
    store.set("calls", phone, {"created_at": old}, merge=True)  # an old phone call: left to Twilio's status callback
    assert services.reap_stale_calls(store, settings) == 1
    assert store.get("calls", cid)["status"] == "dropped" and store.get("calls", cid)["reaped"]
    assert store.get("calls", fresh)["status"] == "queued" and store.get("calls", phone)["status"] == "queued"


def test_the_mills_clock_is_seven_hours_ahead_of_utc():
    sunday_evening_utc = dt.datetime(2026, 10, 18, 20, 0, tzinfo=dt.timezone.utc)  # Monday 03:00 in Jakarta
    assert sunday_evening_utc.astimezone(config.LOCAL_TZ).date() == dt.date(2026, 10, 19)
    assert config.today_local() in (dt.datetime.now(dt.timezone.utc).date(), dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1))
