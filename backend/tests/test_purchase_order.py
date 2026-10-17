"""Purchase orders (PDF) from approved deals and from harvest calls."""

import pytest
from fastapi.testclient import TestClient

from app import main, purchase_order, services
from app.main import create_app


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)
    with TestClient(create_app(settings, store)) as c:
        yield c


def approved_offer(store, settings):
    o = services.create_offer(store, settings, farmer=store.get("farmers", "f01"), crop="palm", kg=1500, price=3240,
                              deliver_week=2, call_id=None)
    services.decide_offer(store, settings, o["id"], approve=True)
    return o


def test_purchase_order_for_an_approved_offer(store, settings):
    o = approved_offer(store, settings)
    name, pdf = purchase_order.for_offer(store, settings, o["id"])
    assert name.startswith("PO-") and name.endswith(".pdf") and pdf.startswith(b"%PDF")
    assert purchase_order.for_offer(store, settings, o["id"])[0] == name  # the same number every time


def test_no_purchase_order_before_approval(store, settings):
    o = services.create_offer(store, settings, farmer=store.get("farmers", "f02"), crop="palm", kg=900, price=3240,
                              deliver_week=2, call_id=None)
    with pytest.raises(services.ServiceError, match="approved"):
        purchase_order.for_offer(store, settings, o["id"])


def test_a_harvest_call_gives_a_draft_at_the_reference_price(store, settings):
    cid = services.queue_call(store, store.get("farmers", "f03"), "collect")
    services.record_harvest(store, settings, "f03", "palm", 1200, "2026-10-28", cid)
    name, pdf = purchase_order.for_call(store, settings, cid)
    assert name.startswith("PO-DRAFT-") and pdf.startswith(b"%PDF")
    empty = services.queue_call(store, store.get("farmers", "f04"), "collect")
    with pytest.raises(services.ServiceError, match="nothing to order"):
        purchase_order.for_call(store, settings, empty)


def test_api_downloads(client, store, settings):
    o = approved_offer(store, settings)
    r = client.get(f"/api/offers/{o['id']}/purchase-order.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"] and r.content.startswith(b"%PDF")
    assert client.get("/api/offers/nope/purchase-order.pdf").status_code == 404
    assert client.get("/api/calls/nope/purchase-order.pdf").status_code == 404


def test_names_outside_latin1_do_not_break_the_pdf(store, settings):
    fid = services.add_farmer(store, {"name": "สมชาย", "phone": "+66 81 000 0001", "crop": "palm", "language": "Thai"})
    o = services.create_offer(store, settings, farmer=store.get("farmers", fid), crop="palm", kg=500, price=3240,
                              deliver_week=2, call_id=None)
    services.decide_offer(store, settings, o["id"], approve=True)
    assert purchase_order.for_offer(store, settings, o["id"])[1].startswith(b"%PDF")
