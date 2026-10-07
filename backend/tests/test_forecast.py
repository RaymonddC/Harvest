import datetime as dt

from app import services
from app.forecast import compute_forecast, gap_reasons, shortlist, week_index
from app.seed_data import BASELINE_TONNES, build_seed

from .conftest import PLAN_START


def test_week_index_bounds():
    assert week_index("2026-10-12", PLAN_START, 5) == 1
    assert week_index("2026-10-18", PLAN_START, 5) == 1
    assert week_index("2026-10-19", PLAN_START, 5) == 2
    assert week_index("2026-11-15", PLAN_START, 5) == 5
    assert week_index("2026-11-16", PLAN_START, 5) is None
    assert week_index("2026-10-11", PLAN_START, 5) is None
    assert week_index("not a date", PLAN_START, 5) is None


def test_seed_matches_wireframe(store):
    rows = sorted(store.list("forecast"), key=lambda r: r["week"])
    assert [r["expected_kg"] for r in rows] == [t * 1000 for t in BASELINE_TONNES]
    assert [r["is_gap"] for r in rows] == [False, False, True, False, False]
    w3 = rows[2]
    assert w3["gap_kg"] == 39_000
    assert w3["unsure_count"] == 6
    assert len(w3["shortlist"]) == 15 and sum(p["kg"] for p in w3["shortlist"]) == 22_800
    assert w3["note"] == ("31 farmers moved delivery to week 4 after late rain, and 6 answers were "
                          "unsure, so they count for half.")


def test_shortlist_with_rival_covers_gap_after_harvest_calls(store, settings):
    # Pak Rahmat, Bu Wati and Pak Joko answer their harvest calls with week-4 harvests.
    for fid, kg in (("f01", 1600), ("f02", 1400), ("f03", 1200)):
        services.record_harvest(store, settings, fid, "palm", kg, "2026-11-02", None)
    w3 = store.get("forecast", "W3")
    farmers_kg = sum(p["kg"] for p in w3["shortlist"])
    assert len(w3["shortlist"]) == 18 and farmers_kg == 27_000
    assert farmers_kg + store.get("rival_quotes", "rq01")["kg"] == w3["gap_kg"]


def test_pulling_the_whole_shortlist_forward_leaves_no_new_gap(store, settings):
    for fid, kg in (("f01", 1600), ("f02", 1400), ("f03", 1200)):
        services.record_harvest(store, settings, fid, "palm", kg, "2026-11-02", None)
    for p in store.get("forecast", "W3")["shortlist"]:
        farmer = store.get("farmers", p["farmer_id"])
        offer = services.create_offer(store, settings, farmer=farmer, crop="palm", kg=p["kg"], price=3300,
                                      deliver_week=3, call_id=None)
        services.decide_offer(store, settings, offer["id"], approve=True)
    rival = services.offer_from_rival_quote(store, settings, "rq01")
    services.decide_offer(store, settings, rival["id"], approve=True)
    rows = sorted(store.list("forecast"), key=lambda r: r["week"])
    assert rows[2]["expected_kg"] == 100_000
    assert not any(r["is_gap"] for r in rows)


def test_seed_is_deterministic_and_synthetic():
    a = build_seed(PLAN_START, "Bahasa Indonesia")
    b = build_seed(PLAN_START, "Bahasa Indonesia")
    assert a == b
    assert all(" 0000 " in f["phone"] for f in a["farmers"].values())


def test_unsure_counts_half_and_approved_pull_forward_moves_volume():
    harvests = [{"id": "h1", "kg": 1000, "ready_date": "2026-10-27"},
                {"id": "h2", "kg": 1000, "ready_date": "2026-10-27", "confidence": "unsure"}]
    offers = [{"status": "approved", "kg": 400, "deliver_week": 2, "from_week": 3},
              {"status": "pending", "kg": 300, "deliver_week": 2, "from_week": 3},
              {"status": "rejected", "kg": 999, "deliver_week": 2}]
    rows = compute_forecast(harvests, offers, PLAN_START, 5, 1000, 0.2)
    assert rows[1]["expected_kg"] == 400 and rows[1]["pending_kg"] == 300 and rows[1]["approved_in_kg"] == 400
    assert rows[2]["expected_kg"] == 1100 and rows[2]["unsure_count"] == 1


def test_shortlist_skips_busy_harvests_and_suppliers():
    farmers = [{"id": "a", "can_pull_forward": True, "name": "A"},
               {"id": "b", "can_pull_forward": True, "name": "B"},
               {"id": "c", "can_pull_forward": False, "name": "C"},
               {"id": "s", "can_pull_forward": True, "type": "supplier", "name": "S"}]
    harvests = [{"id": "ha", "farmer_id": "a", "kg": 500, "ready_date": "2026-11-02"},
                {"id": "hb", "farmer_id": "b", "kg": 900, "ready_date": "2026-11-02"},
                {"id": "hc", "farmer_id": "c", "kg": 900, "ready_date": "2026-11-02"},
                {"id": "hs", "farmer_id": "s", "kg": 900, "ready_date": "2026-11-02"}]
    offers = [{"status": "pending", "harvest_id": "hb"}]
    assert [p["farmer_id"] for p in shortlist(3, farmers, harvests, offers, PLAN_START, 5)] == ["a"]


def test_gap_reasons_without_moves():
    r = gap_reasons(3, [{"id": "x", "kg": 10, "ready_date": "2026-10-27"}], PLAN_START, 5)
    assert r == {"farmers_in_week": 1, "unsure_in_week": 0, "farmers_next_week": 0, "moved_out": 0,
                 "moved_reasons": []}
    note = services.gap_note_text({"week": 3, "gap_kg": 39000, "reasons": r})
    assert note.startswith("Only 1 farmers expect to deliver in week 3")


def test_csv_export(store):
    lines = services.forecast_csv(store).strip().splitlines()
    assert lines[0].startswith("week,week_start")
    assert lines[3].startswith("W3,2026-10-26,61000") and lines[3].rstrip().endswith("yes")


def test_plan_start_is_monday():
    from app.config import next_monday
    for d in range(14):
        day = dt.date(2026, 10, 1) + dt.timedelta(days=d)
        nm = next_monday(day)
        assert nm.weekday() == 0 and nm > day
