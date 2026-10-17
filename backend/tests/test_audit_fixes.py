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


# ---------- a week that is already full ----------

def _fill(store, week, kg):
    store.set("forecast", f"W{week}", {"expected_kg": kg}, merge=True)


def _say(h, date, confirmed=False, kg=1600):
    return h.dispatch("record_harvest", {"crop": "palm", "kg": kg, "ready_date": date, "confirmed_by_farmer": confirmed})


def test_a_farmer_naming_a_full_week_is_offered_the_next_week_with_room(store, settings):
    _fill(store, 2, 100_000)                                   # W2 (from 19 Oct) has what the mill asked for; W3 is short
    h, session = make(store, settings, farmer_id="f01")
    r = _say(h, "2026-10-21")
    assert r["saved"] is False and r["status"] == "week_full" and r["week"] == "W2"
    assert r["suggested_week"] == "W3" and r["suggested_from"] == "2026-10-26" and "W3" in r["say"]
    assert store.get("harvests", "h-f01-palm") is None or store.get("harvests", "h-f01-palm")["ready_date"] != "2026-10-21"


def test_the_farmer_can_agree_to_the_suggested_week(store, settings):
    _fill(store, 2, 100_000)
    h, _ = make(store, settings, farmer_id="f01")
    _say(h, "2026-10-21")
    assert _say(h, "2026-10-27")["status"] == "waiting_for_read_back"
    assert _say(h, "2026-10-27", confirmed=True)["saved"] is True
    assert store.get("harvests", "h-f01-palm")["ready_date"] == "2026-10-27"
    assert "week_full" not in store.get("harvests", "h-f01-palm")


def test_a_farmer_who_keeps_the_full_week_is_never_refused_and_the_planner_sees_it(store, settings):
    _fill(store, 2, 100_000)
    h, _ = make(store, settings, farmer_id="f01")
    assert _say(h, "2026-10-21")["status"] == "week_full"
    assert _say(h, "2026-10-21")["status"] == "waiting_for_read_back"   # same date again: no second warning
    saved = _say(h, "2026-10-21", confirmed=True)
    assert saved["saved"] is True
    assert store.get("harvests", "h-f01-palm")["week_full"]["kept_by_farmer"] is True


def test_a_farmers_own_harvest_is_not_counted_against_their_own_date(store, settings):
    # b001's harvest (1,600 kg on 7 Nov) sits in W4. Make W4 exactly full with it included: confirming the same date is fine.
    _fill(store, 4, 100_000 - 400)
    store.set("harvests", "h-b001-palm", {"kg": 1600}, merge=True)
    h, _ = make(store, settings, farmer_id="b001")
    assert _say(h, "2026-11-07")["status"] == "waiting_for_read_back"


def test_no_week_with_room_later_says_so_and_still_lets_the_farmer_decide(store, settings):
    h, _ = make(store, settings, farmer_id="f01")
    r = _say(h, "2026-11-10")                                    # W5 is over the target and the horizon ends there
    assert r["status"] == "week_full" and r["suggested_week"] is None and "no later week" in r["say"]


def test_approving_an_offer_into_a_week_that_filled_meanwhile_is_refused_unless_forced(store, settings):
    farmer = store.get("farmers", "b001")
    offer = services.create_offer(store, settings, farmer=farmer, crop="palm", kg=1600, price=3300, deliver_week=3, call_id=None)
    services.recompute_forecast(store, settings)
    _fill(store, 3, 100_000)                                      # other supply filled W3 while the offer waited
    with pytest.raises(services.WeekFull) as e:
        services.decide_offer(store, settings, offer["id"], approve=True)
    assert e.value.status == 409 and "W3" in str(e.value) and "approve it anyway" in str(e.value)
    assert store.get("offers", offer["id"])["status"] == "pending"
    assert services.decide_offer(store, settings, offer["id"], approve=True, allow_full=True)["status"] == "approved"


def test_an_offer_into_a_week_that_still_has_a_gap_approves_normally(store, settings):
    farmer = store.get("farmers", "b001")
    offer = services.create_offer(store, settings, farmer=farmer, crop="palm", kg=1600, price=3300, deliver_week=3, call_id=None)
    assert services.decide_offer(store, settings, offer["id"], approve=True)["status"] == "approved"


def test_the_approve_endpoint_answers_409_and_accepts_allow_full(store, settings):
    from fastapi.testclient import TestClient
    from app.main import create_app

    farmer = store.get("farmers", "b001")
    offer = services.create_offer(store, settings, farmer=farmer, crop="palm", kg=1600, price=3300, deliver_week=3, call_id=None)
    _fill(store, 3, 100_000)
    with TestClient(create_app(settings, store)) as c:
        r = c.post(f"/api/offers/{offer['id']}/approve")
        assert r.status_code == 409 and "already filled" in r.json()["detail"]
        assert c.post(f"/api/offers/{offer['id']}/approve?allow_full=true").json()["status"] == "approved"
