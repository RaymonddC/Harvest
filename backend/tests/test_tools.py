import random

import pytest
from google.genai import types

from app import services
from app.prompt import build_system_instruction
from app.tools import TOOL_DECLARATIONS, CallSession, ToolHandlers


def make(store, settings, farmer_id="f01", kind="collect", gap_week=3, offer=None):
    farmer = store.get("farmers", farmer_id)
    session = CallSession(call_id="call-test", farmer=farmer, kind=kind, gap_week=gap_week, offer=offer)
    return ToolHandlers(store, settings, session), session


def test_declarations_are_valid_for_live_api():
    tool = types.Tool(function_declarations=TOOL_DECLARATIONS)
    assert [d.name for d in tool.function_declarations] == [
        "get_farmer", "record_harvest", "get_reference_price", "check_offer", "save_offer", "end_call"]


def test_record_harvest_reads_back_before_saving(store, settings):
    h, _ = make(store, settings)
    r = h.dispatch("record_harvest", {"crop": "kelapa sawit", "kg": 1600, "ready_date": "2026-11-02",
                                      "confirmed_by_farmer": False})
    assert r["saved"] is False and "1,600 kg of Palm FFB" in r["read_back"]
    assert h.last_ui["captured"] == {"crop": "Palm FFB", "kg": 1600, "ready": "W4 · Mon",
                                     "confidence": "Firm", "status": "waiting"}
    assert store.get("harvests", "h-f01-palm") is None


def test_record_harvest_refuses_to_save_without_a_matching_read_back(store, settings):
    h, _ = make(store, settings)
    args = {"crop": "palm", "kg": 1600, "ready_date": "2026-11-02", "confirmed_by_farmer": True}
    assert h.dispatch("record_harvest", args)["saved"] is False  # never read back
    h.dispatch("record_harvest", {**args, "confirmed_by_farmer": False})
    assert h.dispatch("record_harvest", {**args, "kg": 2000})["saved"] is False  # numbers changed
    assert store.get("harvests", "h-f01-palm") is None
    assert h.dispatch("record_harvest", args)["saved"] is True


def test_record_harvest_updates_forecast_and_replaces_corrections(store, settings):
    h, _ = make(store, settings)
    before = store.get("forecast", "W4")["expected_kg"]
    h.dispatch("record_harvest", {"crop": "Palm FFB", "kg": 1600, "ready_date": "2026-11-02",
                                  "confirmed_by_farmer": False})
    r = h.dispatch("record_harvest", {"crop": "Palm FFB", "kg": 1600, "ready_date": "2026-11-02",
                                      "confirmed_by_farmer": True})
    assert r["saved"] and r["week_label"] == "W4"
    assert store.get("forecast", "W4")["expected_kg"] == before + 1600
    h.dispatch("record_harvest", {"crop": "palm", "kg": 1800, "ready_date": "2026-11-02",
                                  "confirmed_by_farmer": False})
    h.dispatch("record_harvest", {"crop": "palm", "kg": 1800, "ready_date": "2026-11-02",
                                  "confidence": "unsure", "confirmed_by_farmer": True})
    assert store.get("forecast", "W4")["expected_kg"] == before + 900  # unsure counts half


def test_reference_price_does_not_leak_limits(store, settings):
    h, _ = make(store, settings)
    r = h.dispatch("get_reference_price", {"crop": "sawit"})
    assert r["reference_price"] == 3100 and r["currency"] == "IDR"
    assert "3350" not in str(r) and "2900" not in str(r)


def test_check_offer_result_hides_limits_but_ui_gets_rail(store, settings):
    h, _ = make(store, settings, farmer_id="b001", kind="gap_fill")
    r = h.dispatch("check_offer", {"crop": "palm", "kg": 1600})
    assert "3350" not in str(r) and "2900" not in str(r)
    assert h.last_ui["rail"]["ceiling"] == 3350 and h.last_ui["rail"]["offer"] == 3220


def test_save_offer_rejects_model_chosen_price(store, settings):
    h, _ = make(store, settings, farmer_id="b001", kind="gap_fill")
    assert "error" in h.dispatch("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3300})
    assert not store.list("offers")


def test_negotiation_flow_from_the_design(store, settings):
    # Offer 3,220, farmer counters 3,300, inside the ceiling: accept and save as pending.
    h, _ = make(store, settings, farmer_id="b001", kind="gap_fill")
    first = h.dispatch("check_offer", {"crop": "palm", "kg": 1600})
    assert first["price_per_kg"] == 3220 and first["deliver_week"] == "W3"
    counter = h.dispatch("check_offer", {"crop": "palm", "kg": 1600, "farmer_counter_price": 3300})
    assert counter["decision"] == "accept" and counter["price_per_kg"] == 3300
    assert h.last_ui["rail"]["offer"] == 3220 and h.last_ui["rail"]["counter"] == 3300
    saved = h.dispatch("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3300})
    offer = store.get("offers", saved["offer_id"])
    assert offer["status"] == "pending" and offer["deliver_week"] == 3 and offer["from_week"] == 4
    assert offer["negotiation"]["first_offer"] == 3220 and offer["negotiation"]["counter"] == 3300
    assert store.get("forecast", "W3")["pending_kg"] == 1600
    assert store.get("forecast", "W3")["expected_kg"] == 61_000  # pending does not count


def test_escalation_records_request_without_pending_offer(store, settings):
    h, _ = make(store, settings, farmer_id="b002", kind="gap_fill")
    h.dispatch("check_offer", {"crop": "palm", "kg": 1600})
    r = h.dispatch("check_offer", {"crop": "palm", "kg": 1600, "farmer_counter_price": 3600})
    assert r["decision"] == "escalate" and r["allowed"] is False and r["price_per_kg"] == 3350
    saved = h.dispatch("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3600, "escalate": True})
    assert saved["status"] == "escalated"
    offer = store.list("offers")[0]
    assert offer["status"] == "escalated" and offer["price_per_kg"] == 3350 and offer["requested_price"] == 3600
    # The ceiling, handed back as the best price, can still be agreed for less volume.
    ok = h.dispatch("save_offer", {"crop": "palm", "kg": 800, "price_per_kg": 3350})
    assert ok["status"] == "pending"


def test_escalated_offer_needs_limits_that_cover_the_request(store, settings):
    h, _ = make(store, settings, farmer_id="b002", kind="gap_fill")
    h.dispatch("check_offer", {"crop": "palm", "kg": 1600})
    h.dispatch("check_offer", {"crop": "palm", "kg": 1600, "farmer_counter_price": 3600})
    h.dispatch("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3600, "escalate": True})
    offer = store.list("offers")[0]
    # The stored price is the ceiling, but the farmer asked for 3,600, so approval is refused.
    with pytest.raises(services.ServiceError, match="outside the current floor and ceiling"):
        services.decide_offer(store, settings, offer["id"], approve=True)
    assert store.get("offers", offer["id"])["status"] == "escalated"

    old = store.get("limits", "palm")
    services.set_limits(store, "palm", floor=old["floor_price"], ceiling=3600,
                        reference=old["reference_price"])
    approved = services.decide_offer(store, settings, offer["id"], approve=True)
    saved = store.get("offers", offer["id"])
    assert approved["price_per_kg"] == 3600
    assert saved["status"] == "approved" and saved["price_per_kg"] == 3600 and saved["quoted_price"] == 3350

    # Undo puts it back to escalated at the quoted ceiling.
    services.undo_offer(store, settings, offer["id"])
    saved = store.get("offers", offer["id"])
    assert saved["status"] == "escalated" and saved["price_per_kg"] == 3350 and saved["requested_price"] == 3600


def test_no_offers_without_gap_or_on_confirm_calls(store, settings):
    h, _ = make(store, settings, gap_week=None)
    assert "error" in h.dispatch("check_offer", {"crop": "palm", "kg": 100})
    h, _ = make(store, settings, kind="confirm")
    assert "error" in h.dispatch("check_offer", {"crop": "palm", "kg": 100})


def test_end_call_and_bad_input(store, settings):
    h, session = make(store, settings)
    assert "error" in h.dispatch("delete_everything", {})
    assert "error" in h.dispatch("record_harvest", {"crop": "palm"})
    assert "error" in h.dispatch("record_harvest", {"crop": "palm", "kg": 5, "ready_date": "next week",
                                                    "confirmed_by_farmer": True})
    assert "error" in h.dispatch("get_reference_price", {"crop": "durian"})
    h.dispatch("end_call", {"outcome": "completed", "summary": "1.6 t for W4.", "transcript_consent": True})
    assert session.ended and session.consent and h.last_ui == {"consent": True}


def test_farmer_who_says_stop_is_never_queued_again(store, settings):
    call_id = services.queue_call(store, store.get("farmers", "f01"), "collect")
    services.finish_call(store, settings, call_id, ended_cleanly=True, outcome="stopped",
                         summary="Asked not to be called again.", consent=False, transcript=[])
    assert store.get("farmers", "f01")["do_not_call"] is True

    services.start_campaign(store, settings, "collect")
    assert not any(c["farmer_id"] == "f01" for c in store.list("calls") if c["status"] == "queued")

    with pytest.raises(services.ServiceError):
        services.call_now(store, "f01")


def test_prompt_has_disclosure_two_step_read_back_and_no_limits(store, settings):
    farmer = store.get("farmers", "f01")
    text = build_system_instruction(settings, farmer, "collect", 3)
    assert "AI assistant calling for Koperasi Sawit Maju" in text
    assert "Bahasa Indonesia" in text and "Palm FFB" in text
    assert "confirmed_by_farmer false" in text and "W3" in text
    for secret in ("3350", "3,350", "2900", "2,900", "ceiling", "floor"):
        assert secret not in text
    confirm = build_system_instruction(settings, farmer, "confirm", None,
                                       offer={"kg": 1600, "crop": "palm", "price_per_kg": 3300.0,
                                              "deliver_week": 3, "currency": "IDR"})
    assert "1600 kg of Palm FFB at 3300.0 IDR" in confirm


def test_prices_never_leave_limits_in_random_negotiations(store, settings):
    rng = random.Random(1)
    limits = services.get_limits(store, "palm")
    for _ in range(50):
        h, session = make(store, settings, farmer_id="b003", kind="gap_fill")
        for _ in range(rng.randint(1, 8)):
            counter = rng.choice([None, rng.uniform(2000, 4000)])
            r = h.dispatch("check_offer", {"crop": "palm", "kg": 1000, "farmer_counter_price": counter})
            if r.get("price_per_kg") is not None:
                assert limits.within(r["price_per_kg"])
        assert all(limits.within(p) for p in session.quoted_prices.get("palm", ()))
