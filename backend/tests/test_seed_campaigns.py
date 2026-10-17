"""The demo data for the app has three campaigns: palm (the main one), Palm, Kampar and Rubber."""

from app import mill_ops, seed_data, services, track_record
from app.store import MemoryStore


def test_three_campaigns_with_their_own_farmers_forecast_and_history(settings):
    store = MemoryStore()
    seed_data.load_seed(store, settings)
    camps = {c["id"]: c for c in services.list_campaigns(store, settings)}
    assert set(camps) == {"current", "palm-kampar", "rubber"}
    for cid in ("palm-kampar", "rubber"):
        members = services.campaign_members(store, settings, cid)
        assert len(members) >= 20 and all(f["campaign_id"] == cid for f in members)
        rows = [r for r in store.list("forecast") if r.get("campaign_id") == cid]
        assert rows and any(r["expected_kg"] > 0 for r in rows)
        assert track_record.summary(store, settings, cid)["weeks"]
        assert [o for o in services.campaign_records(store, settings, cid, "offers") if o["status"] == "pending"]
        assert mill_ops.daily_capacity(camps[cid])
    kampar = sorted((r for r in store.list("forecast") if r.get("campaign_id") == "palm-kampar"), key=lambda r: r["week"])
    assert any(r["is_gap"] for r in kampar)
    assert store.get("limits", "rubber")["reference_price"] == 12500
    main = sorted((r for r in store.list("forecast") if r.get("campaign_id") == "current"), key=lambda r: r["week"])
    assert [r["expected_kg"] for r in main][:4] == [t * 1000 for t in seed_data.BASELINE_TONNES[:4]]  # unchanged
