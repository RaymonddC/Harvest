"""Mill operations: capacity and surplus, supply by period, grading and payment, official price, traceability."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import main, mill_ops, purchase_order, services, track_record
from app.main import create_app

D = dt.date.fromisoformat


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(settings, store)) as c:
        yield c


def test_weeks_over_capacity_are_a_surplus_with_farmers_to_move(store, settings):
    w5 = next(r for r in store.list("forecast") if r["id"] == "W5")
    assert w5["capacity_kg"] == 17_000 * 6 and w5["is_surplus"] and w5["surplus_kg"] > 0
    farmers = mill_ops.surplus_farmers(store, settings, "current", 5)
    assert farmers and farmers[0]["kg"] >= farmers[-1]["kg"]


def test_reschedule_moves_the_harvest_and_texts_the_farmer(store, settings):
    fid = mill_ops.surplus_farmers(store, settings, "current", 5)[0]["farmer_id"]
    old = store.get("harvests", f"h-{fid}-palm")["ready_date"]
    new = (D(old) + dt.timedelta(days=7)).isoformat()
    r = mill_ops.reschedule_harvest(store, settings, fid, new, "mill full")
    h = store.get("harvests", f"h-{fid}-palm")
    assert r["to"] == new and h["ready_date"] == new and h["rescheduled_from"] == old
    assert any(m.get("kind") == "reschedule" for m in store.list("messages"))
    with pytest.raises(services.ServiceError, match="later date"):
        mill_ops.reschedule_harvest(store, settings, fid, old)
    with pytest.raises(services.ServiceError, match="three weeks"):
        mill_ops.reschedule_harvest(store, settings, fid, (D(new) + dt.timedelta(days=30)).isoformat())


def test_supply_by_day_week_month_year(store, settings):
    start, end = settings.plan_start, settings.plan_start + dt.timedelta(days=34)
    days = mill_ops.supply_series(store, settings, "current", "day", start, end, today=start)
    assert len(days["rows"]) == 35
    sunday = next(r for r in days["rows"] if D(r["start"]).weekday() == 6)
    assert sunday["capacity_kg"] == 0 and sunday["target_kg"] == 0  # the mill does not run on Sundays
    weeks = mill_ops.supply_series(store, settings, "current", "week", start, end, today=start)
    assert len(weeks["rows"]) == 5
    assert sum(r["expected_kg"] for r in weeks["rows"]) == pytest.approx(sum(r["expected_kg"] for r in days["rows"]), abs=10)
    assert weeks["rows"][0]["capacity_kg"] == 102_000 and weeks["rows"][4]["is_surplus"]
    assert all(r["trucks"] >= 0 for r in days["rows"])
    months = mill_ops.supply_series(store, settings, "current", "month", start - dt.timedelta(days=40), end, today=start)
    assert months["rows"][0]["delivered_kg"] > 0  # the seeded weighbridge history, net of deductions
    years = mill_ops.supply_series(store, settings, "current", "year", D("2026-01-01"), D("2027-12-31"), today=start)
    assert [r["label"] for r in years["rows"]] == ["2026", "2027"]
    with pytest.raises(services.ServiceError):
        mill_ops.supply_series(store, settings, "current", "hour", start, end)


def test_grading_net_weight_and_payment_from_the_purchase_order(store, settings):
    o = services.create_offer(store, settings, farmer=store.get("farmers", "f01"), crop="palm", kg=1500, price=3300,
                              deliver_week=1, call_id=None)
    services.decide_offer(store, settings, o["id"], approve=True)
    day = settings.plan_start.isoformat()
    d = track_record.record_delivery(store, settings, "f01", 1000, day, "Weighbridge", deductions={"unripe": 4, "dirt": 1})
    assert d["deduction_pct"] == 5 and d["net_kg"] == 950 and d["price_basis"] == "purchase order"
    assert d["price_per_kg"] == 3300 and d["amount"] == 950 * 3300 and d["po_number"].startswith("PO-")
    assert store.get("offers", o["id"])["delivered_kg"] == 950
    other = track_record.record_delivery(store, settings, "b004", 800, day)
    assert other["price_basis"] == "reference price" and other["net_kg"] == 800
    name, pdf = purchase_order.for_delivery(store, settings, d["id"])
    assert name.startswith("GR-") and pdf.startswith(b"%PDF")
    with pytest.raises(services.ServiceError, match="more than 50"):
        track_record.record_delivery(store, settings, "f01", 1000, day, deductions={"unripe": 40, "dirt": 20})


def test_api_delivery_with_grading_and_receipt(client, store, settings):
    r = client.post("/api/deliveries", json={"farmer_id": "b004", "kg": 1200, "date": settings.plan_start.isoformat(),
                                             "unripe_pct": 3, "dirt_pct": 2})
    assert r.status_code == 200 and r.json()["net_kg"] == 1140
    pdf = client.get(f"/api/deliveries/{r.json()['id']}/receipt.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv = "phone,date,kg,unripe_pct\n" + store.get("farmers", "b004")["phone"] + f",{settings.plan_start},1000,10"
    assert client.post("/api/deliveries/upload", json={"csv": csv}).json()["added"] == 1
    assert any(d.get("net_kg") == 900 for d in store.list("deliveries"))


def test_official_price_moves_the_range_when_followed(client, store, settings):
    lim = store.get("limits", "palm")
    assert client.put("/api/limits/palm/follow-official", json={"enabled": True, "province": "Riau"}).status_code == 200
    r = client.post("/api/official-prices", json={"crop": "palm", "province": "Riau", "valid_from": "2026-10-01",
                                                  "price_per_kg": 3410, "source": "Disbun Riau"})
    assert r.status_code == 200
    new = store.get("limits", "palm")
    assert new["reference_price"] == 3410
    assert new["floor_price"] > lim["floor_price"] and new["ceiling_price"] > lim["ceiling_price"]
    assert "Riau" in new["reference_source"]
    client.put("/api/limits/palm/follow-official", json={"enabled": False})
    client.post("/api/official-prices", json={"crop": "palm", "province": "Riau", "valid_from": "2026-10-02",
                                              "price_per_kg": 3000})
    assert store.get("limits", "palm")["reference_price"] == 3410  # not followed any more
    bad = client.post("/api/official-prices", json={"province": "", "valid_from": "2026-10-02", "price_per_kg": 1})
    assert bad.status_code == 400


def test_traceability_plot_fields_flags_and_csv(client, store, settings):
    body = {"name": "Pak Plot", "phone": "+62 812 4444 0001", "crop": "palm", "language": "English",
            "plot_lat": "0.5123", "plot_lng": "101.4", "plot_ha": "2.5", "certification": "RSPO"}
    fid = client.post("/api/farmers", json=body).json()["id"]
    f = store.get("farmers", fid)
    assert (f["plot_lat"], f["plot_lng"], f["plot_ha"], f["certification"]) == (0.5123, 101.4, 2.5, "RSPO")
    client.put(f"/api/farmers/{fid}", json={**body, "plot_lat": "", "plot_lng": "", "certification": ""})
    f = store.get("farmers", fid)
    assert f["plot_lat"] is None and f["certification"] is None and f["plot_ha"] == 2.5
    bad = client.post("/api/farmers", json={**body, "phone": "+62 812 4444 0002", "plot_lat": "200", "plot_lng": "1"})
    assert bad.status_code == 400
    summary = client.get("/api/traceability?campaign=current").json()
    assert summary["farmers"] > summary["mapped"] > 0
    assert any(x["farmer_id"] == "b013" for x in summary["over_plot_yield"])  # 0.1 ha cannot grow what it delivered
    csv = client.get("/api/traceability.csv").text.splitlines()
    assert csv[0].startswith("delivery_id,date,farmer_id") and len(csv) > 10
