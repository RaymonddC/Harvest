"""Mills: the nearest one to a plot, the road and truck-time estimate, the catchment, and where they are used."""

import pytest

from app import mills, prompt, purchase_order


def test_nearest_mill_distance_and_truck_time():
    ms = [{"id": "a", "name": "A", "lat": 0.0, "lng": 0.0}, {"id": "b", "name": "B", "lat": 1.0, "lng": 1.0}]
    n = mills.nearest(ms, {"plot_lat": 0.1, "plot_lng": 0.0})
    assert n["mill_id"] == "a" and n["km"] == pytest.approx(11.1, abs=0.1)
    assert n["road_km"] == pytest.approx(n["km"] * mills.ROAD_FACTOR, abs=0.1)
    assert n["minutes"] == round(n["road_km"] / mills.TRUCK_KMH * 60) and not n["far"]
    assert mills.nearest(ms, {}) is None and mills.nearest([], {"plot_lat": 0, "plot_lng": 0}) is None
    far = mills.nearest(ms, {"plot_lat": 0.0, "plot_lng": 0.6})  # ~67 km straight, ~87 by road, ~174 min
    assert far["far"] and "h" in mills.travel_text(far)


def test_add_edit_delete_and_checks(store):
    m = mills.add(store, "  New mill ", "0.5", 101.5)
    assert m["name"] == "New mill" and store.get("mills", m["id"])["lat"] == 0.5
    assert mills.update(store, m["id"], "Renamed", 0.6, 101.6)["name"] == "Renamed"
    with pytest.raises(mills.MillError):
        mills.add(store, "", 0, 0)
    with pytest.raises(mills.MillError):
        mills.add(store, "X", 95, 0)
    mills.delete(store, m["id"])
    assert not store.get("mills", m["id"])


def test_seed_has_mills_and_catchment_covers_mapped_farmers(store):
    rows = mills.catchment(store)
    assert len(rows) == 2 and sum(r["farmers"] for r in rows) == sum(
        1 for f in store.list("farmers") if f.get("plot_lat") is not None and f.get("plot_lng") is not None)


def test_confirm_call_says_where_to_bring_the_fruit(store, settings):
    farmer = store.list("farmers")[0]
    offer = {"kg": 1000, "crop": "palm", "price_per_kg": 3200, "deliver_week": 1}
    text = prompt.build_system_instruction(settings, farmer, "confirm", None, offer=offer, deliver_to="Mill A, about 14 km by road")
    assert "where to bring the fruit: Mill A" in text
    assert "where to bring" not in prompt.build_system_instruction(settings, farmer, "confirm", None, offer=offer)


def test_purchase_order_names_the_nearest_mill(store, settings):
    farmer = next(f for f in store.list("farmers") if f.get("plot_lat") is not None)
    assert purchase_order._deliver_to(store, farmer).startswith("Sawit Maju mill")
    assert purchase_order._deliver_to(store, {"id": "x"}) is None
