"""Who gets a harvest call: no answer, an unsure answer, a harvest date that has passed, or marked to call."""

import datetime as dt

from app import services


def test_reasons(store, settings):
    today = dt.date(2026, 10, 14)
    f = {"id": "x", "name": "X"}
    assert services.call_reason(f, None, today) == "no_answer"
    assert services.call_reason(f, {"ready_date": "2026-10-10", "confidence": "firm"}, today) == "date_passed"
    assert services.call_reason(f, {"ready_date": "2026-10-10", "confidence": "firm", "every_days": 14}, today) is None
    assert services.call_reason(f, {"ready_date": "2026-10-20", "confidence": "unsure"}, today) == "unsure"
    assert services.call_reason(f, {"ready_date": "2026-10-20", "confidence": "firm"}, today) is None
    assert services.call_reason({**f, "to_call": True}, {"ready_date": "2026-10-20", "confidence": "firm"}, today) == "flagged"
    assert services.call_reason({**f, "do_not_call": True}, None, today) is None
    assert services.call_reason({**f, "type": "supplier"}, None, today) is None


def test_harvest_calls_go_to_the_call_list(store, settings):
    members = services.campaign_members(store, settings, "current")
    reasons = services.call_list(store, settings, members)
    assert "unsure" in reasons.values() and "no_answer" in reasons.values()
    r = services.start_campaign(store, settings, "collect", "current")
    queued = {c["farmer_id"] for c in store.list("calls") if c["status"] == "queued"}
    assert r["queued"] == len(reasons) and queued == set(reasons)
