"""Synthetic demo data for a palm cooperative in Riau. Nothing here describes a real
farmer, cooperative or supplier.

The baseline reproduces the wireframe: expected supply of 92, 85, 61, 98 and 90 t over
five weeks against a 100 t target, so week 3 shows a 39 t gap. Six week-3 answers are
unsure and count for half; 31 week-4 harvests moved there from week 3 after late rain.
Fifteen farmers on record can pull delivery forward (22.8 t). Pak Rahmat, Bu Wati and
Pak Joko are waiting for their harvest call; once they answer they join the shortlist
(18 farmers, about 27 t), and a rival supplier quote covers the remaining 12 t.
"""

from __future__ import annotations

import datetime as dt
import random

from .forecast import UNSURE_WEIGHT, week_start
from .rules_engine import Limits

BASELINE_TONNES = (92, 85, 61, 98, 90)
UNSURE_IN_GAP_WEEK = 6
MOVED_AFTER_RAIN = 31

# (name, village, usual kg/week, can pull forward)
DEMO_FARMERS = [
    ("Pak Rahmat", "Sungai Lala", 800, True), ("Bu Wati", "Sungai Lala", 700, True),
    ("Pak Joko", "Bukit Raya", 600, True), ("Bu Endang", "Bukit Raya", 900, False),
    ("Pak Hasan", "Tanjung Sari", 750, False), ("Bu Ratna", "Tanjung Sari", 650, False),
    ("Pak Slamet", "Air Molek", 850, False), ("Bu Sari", "Air Molek", 700, False),
    ("Pak Agus", "Pematang Reba", 900, False), ("Bu Nur", "Pematang Reba", 600, False),
    ("Pak Budi", "Lirik", 800, False), ("Bu Yanti", "Lirik", 750, False),
]
# Pull-forward farmers already on record: 9 x 1.6 t in week 4 and 6 x 1.4 t in week 5 (22.8 t).
PULL_FORWARD = [(4, 1600)] * 9 + [(5, 1400)] * 6
FIRST_NAMES = ["Pak Ahmad", "Bu Siti", "Pak Darmawan", "Bu Lestari", "Pak Hendra", "Bu Rina",
               "Pak Sutrisno", "Bu Dewi", "Pak Yusuf", "Bu Kartini", "Pak Wahyu", "Bu Ani",
               "Pak Bambang", "Bu Fitri", "Pak Iwan", "Bu Murni", "Pak Rudi", "Bu Tuti",
               "Pak Eko", "Bu Yuli"]
VILLAGES = ["Sungai Lala", "Bukit Raya", "Tanjung Sari", "Air Molek", "Pematang Reba", "Lirik"]


def default_limits(crop: str = "palm") -> Limits:
    # Illustrative IDR per kg of fresh fruit bunches. Tune with C-03.
    return Limits(crop=crop, floor=2900.0, ceiling=3350.0, reference=3100.0, currency="IDR",
                  first_premium_pct=4.0, step_pct=2.0, increment=10.0)


def _phone(n: int) -> str:
    return f"+62 81{n % 10} 0000 {n:04d}"


def build_seed(plan_start: dt.date, language: str, crop: str = "palm",
               target_kg: int = 100_000, rng_seed: int = 7) -> dict[str, dict[str, dict]]:
    rng = random.Random(rng_seed)
    farmers: dict[str, dict] = {}
    harvests: dict[str, dict] = {}
    n_phone = 1000

    def add_farmer(fid: str, name: str, village: str, usual: int, **extra) -> None:
        nonlocal n_phone
        farmers[fid] = {"name": name, "phone": _phone(n_phone), "language": language, "crop": crop,
                        "village": village, "usual_kg_week": usual, "type": "farmer",
                        "can_pull_forward": False, "to_call": False, **extra}
        n_phone += 37

    def add_harvest(fid: str, kg: int, week: int, **extra) -> None:
        ready = week_start(week, plan_start) + dt.timedelta(days=rng.randint(0, 5))
        harvests[f"h-{fid}-{crop}"] = {"farmer_id": fid, "crop": crop, "kg": kg,
                                       "ready_date": ready.isoformat(), "confidence": "firm",
                                       "source": "previous_call", **extra}

    for i, (name, village, usual, pull) in enumerate(DEMO_FARMERS, start=1):
        add_farmer(f"f{i:02d}", name, village, usual, to_call=True, can_pull_forward=pull)

    count = 0
    used_names = {name for name, *_ in DEMO_FARMERS}

    def unique_name() -> str:
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice('ABDEFHIKLMNPRSTWY')}."
            if name not in used_names:
                used_names.add(name)
                return name

    def new_baseline_farmer(kg: int, **extra) -> str:
        nonlocal count
        count += 1
        fid = f"b{count:03d}"
        add_farmer(fid, unique_name(), rng.choice(VILLAGES),
                   int(round(kg / 2 / 50) * 50), **extra)
        return fid

    remaining = {w: t * 1000 for w, t in enumerate(BASELINE_TONNES, start=1)}
    for week, kg in PULL_FORWARD:
        fid = new_baseline_farmer(kg, can_pull_forward=True)
        add_harvest(fid, kg, week)
        remaining[week] -= kg

    for _ in range(UNSURE_IN_GAP_WEEK):
        kg = 1200
        fid = new_baseline_farmer(kg)
        add_harvest(fid, kg, 3, confidence="unsure")
        remaining[3] -= kg * UNSURE_WEIGHT

    moved = 0
    for week in range(1, len(BASELINE_TONNES) + 1):
        left = remaining[week]
        while left > 0:
            kg = min(left, rng.randrange(800, 2401, 50))
            if left - kg < 600:
                kg = left
            extra = {}
            if week == 4 and moved < MOVED_AFTER_RAIN:
                extra = {"moved_from_week": 3, "note": "late rain"}
                moved += 1
            fid = new_baseline_farmer(int(kg))
            add_harvest(fid, int(kg), week, **extra)
            left -= kg

    supplier_id = "s01"
    farmers[supplier_id] = {"name": "Rival supplier", "phone": _phone(9001), "language": language,
                            "crop": crop, "village": "Pekanbaru", "usual_kg_week": 0, "type": "supplier",
                            "can_pull_forward": True, "to_call": False}
    rival_quotes = {"rq01": {"supplier_id": supplier_id, "supplier_name": "Rival supplier",
                             "crop": crop, "kg": 12_000, "price_per_kg": 3280.0, "deliver_week": 3,
                             "note": "Logged by the planner after a phone quote."}}

    limits_doc = {**default_limits(crop).to_doc(),
                  "reference_source": "Illustrative. Replace with the published provincial FFB price and its date."}
    promises, deliveries = _history(plan_start, crop, [fid for fid in farmers if fid.startswith("b")][:40], rng)
    # Mill operations, from their own random stream so the numbers above stay as they were.
    ops = random.Random(rng_seed + 101)
    late = []  # a late week with more fruit than the mill can press: the surplus to spread out
    for i in range(14):
        fid = f"x{i + 1:02d}"
        add_farmer(fid, unique_name(), ops.choice(VILLAGES), 1800)
        ready = week_start(5, plan_start) + dt.timedelta(days=ops.randint(0, 4))
        harvests[f"h-{fid}-{crop}"] = {"farmer_id": fid, "crop": crop, "kg": ops.randrange(1600, 2401, 50),
                                       "ready_date": ready.isoformat(), "confidence": "firm", "source": "previous_call"}
        late.append(fid)
    for n, (fid, f) in enumerate(sorted(farmers.items())):
        if f["type"] == "supplier" or n % 7 == 6:  # about one in seven plots not mapped yet
            continue
        f.update(plot_lat=round(ops.uniform(0.25, 1.15), 5), plot_lng=round(ops.uniform(101.0, 102.1), 5),
                 plot_ha=round(ops.uniform(1.2, 4.0), 1))
        if n % 3 == 0:
            f["certification"] = "ISPO"
        elif n % 11 == 0:
            f["certification"] = "RSPO"
    if "b013" in farmers:  # delivers far more than a plot this size can grow: fruit bought from elsewhere?
        farmers["b013"]["plot_ha"] = 0.1
    reference = float(limits_doc["reference_price"])
    for d in deliveries.values():
        unripe, dirt = round(ops.uniform(0, 6), 1), round(ops.uniform(0, 3), 1)
        pct = round(unripe + dirt, 1)
        net = round(d["kg"] * (1 - pct / 100))
        d.update(deductions={k: v for k, v in (("unripe", unripe), ("dirt", dirt)) if v}, deduction_pct=pct, net_kg=net,
                 price_per_kg=reference, currency=limits_doc.get("currency", "IDR"), amount=round(net * reference),
                 price_basis="reference price", offer_id=None, po_number=None)
    official = {f"op-{crop}-riau-{(plan_start - dt.timedelta(days=12)).isoformat()}": {
        "crop": crop, "province": "Riau", "valid_from": (plan_start - dt.timedelta(days=12)).isoformat(),
        "price_per_kg": reference, "source": "Illustrative: replace with the published Disbun price", "url": None,
        "added_by": "Seed"}}
    return {
        "farmers": farmers,
        "harvests": harvests,
        "promises": promises,
        "deliveries": deliveries,
        "limits": {crop: limits_doc},
        "rival_quotes": rival_quotes,
        "campaigns": {"current": {"status": "idle", "kind": None, "crop": crop, "target_kg_per_week": target_kg,
                                  "daily_capacity_kg": 17_000, "working_days": 6, "truck_kg": 8_000}},
        "official_prices": official,
    }


HISTORY_WEEKS = 4


def _history(plan_start: dt.date, crop: str, farmer_ids: list[str], rng: random.Random):
    """Four finished weeks of promises and weighbridge deliveries for 40 farmers, so forecast accuracy and
    reliability show from the start. Most keep their word; a few deliver about three quarters, some about half."""
    promises, deliveries = {}, {}
    for i, fid in enumerate(farmer_ids):
        keeps = (0.45, 0.6) if i % 10 == 3 else (0.7, 0.85) if i % 10 in (5, 8) else (0.92, 1.0)
        for k in range(2, 2 + HISTORY_WEEKS):  # this week is not over yet: history starts the week before
            week = plan_start - dt.timedelta(days=7 * k)
            promised = rng.randrange(800, 2201, 50)
            promises[f"p-{fid}-{crop}-{week.isoformat()}"] = {"farmer_id": fid, "crop": crop, "week_start": week.isoformat(),
                                                             "kg": promised, "saved_at": "seed"}
            got = round(promised * rng.uniform(*keeps) / 10) * 10
            if got:
                day = week + dt.timedelta(days=rng.randint(0, 5))
                deliveries[f"d-{fid}-{week.isoformat()}"] = {"farmer_id": fid, "farmer_name": fid, "crop": crop, "kg": got,
                                                            "date": day.isoformat(), "week_start": week.isoformat(),
                                                            "source": "seed", "recorded_by": "Weighbridge"}
    return promises, deliveries


# ---------- more campaigns for the demo: a second palm area and a rubber campaign ----------
# Each has its own farmers (campaign_id set), harvests, four weeks of graded weighbridge history, a waiting offer,
# and its own target, dates and mill capacity, so switching campaigns shows a different picture.
KAMPAR_VILLAGES = ["Bangkinang", "Kuok", "Salo", "Air Tiris"]
RUBBER_VILLAGES = ["Lubuk Jambi", "Baserah", "Cerenti", "Kari"]


def _more_campaigns(plan_start: dt.date, language: str, rng_seed: int = 7) -> dict[str, dict[str, dict]]:
    rng = random.Random(rng_seed + 202)
    out: dict[str, dict[str, dict]] = {"farmers": {}, "harvests": {}, "promises": {}, "deliveries": {}, "limits": {},
                                       "campaigns": {}, "offers": {}}
    names = iter(f"{a} {b}." for b in "ABDEFHIKLMNPRSTWY" for a in ("Pak Hasan", "Bu Nur", "Pak Joni", "Bu Sri",
                                                                    "Pak Udin", "Bu Wati", "Pak Rudi", "Bu Ina"))
    phone = iter(range(5000, 9000, 31))
    end = plan_start + dt.timedelta(days=7 * 6 - 1)

    def campaign(cid, crop, name, target, cap, truck, ref, floor, ceil, villages, n, kg_range, weekly_shape, every):
        out["campaigns"][cid] = {"crop": crop, "name": name, "status": "idle", "kind": None, "target_kg_per_week": target,
                                 "start_date": (plan_start - dt.timedelta(days=7)).isoformat(), "end_date": end.isoformat(),
                                 "weeks": 6, "daily_capacity_kg": cap, "working_days": 6, "truck_kg": truck,
                                 "created_at": "2026-10-01T08:00:00+00:00"}
        if crop != "palm":
            out["limits"][crop] = {**Limits(crop=crop, floor=floor, ceiling=ceil, reference=ref, currency="IDR",
                                            first_premium_pct=4.0, step_pct=2.0, increment=50.0).to_doc(),
                                   "reference_source": "Illustrative. Replace with the published local price and its date."}
        ids = []
        for i in range(n):
            fid = f"{cid[:1]}{cid[-1]}{i + 1:02d}"
            out["farmers"][fid] = {"name": next(names), "phone": _phone(next(phone)), "language": language, "crop": crop,
                                   "village": rng.choice(villages), "usual_kg_week": rng.randrange(*kg_range, 50),
                                   "type": "farmer", "can_pull_forward": i % 3 == 0, "to_call": i % 2 == 0,
                                   "campaign_id": cid, "plot_lat": round(rng.uniform(0.0, 0.6), 5),
                                   "plot_lng": round(rng.uniform(101.0, 101.8), 5), "plot_ha": round(rng.uniform(1.0, 3.5), 1),
                                   **({"certification": "ISPO"} if i % 4 == 0 else {})}
            ids.append(fid)
        # Harvests spread over the weeks with the campaign's shape (a short week shows as a gap).
        for i, fid in enumerate(ids):
            week = weekly_shape[i % len(weekly_shape)]
            ready = week_start(week, plan_start) + dt.timedelta(days=rng.randint(0, 5))
            out["harvests"][f"h-{fid}-{crop}"] = {"farmer_id": fid, "crop": crop, "kg": rng.randrange(*kg_range, 50),
                                                  "ready_date": ready.isoformat(), "confidence": "unsure" if i % 7 == 3 else "firm",
                                                  "source": "previous_call", "every_days": every}
        promises, deliveries = _history(plan_start, crop, ids[: n // 2], rng)
        for d in deliveries.values():
            unripe, dirt = round(rng.uniform(0, 5), 1), round(rng.uniform(0, 3), 1)
            pct = round(unripe + dirt, 1)
            kg = round(d["kg"] * kg_range[1] / 2200 / 10) * 10 or d["kg"]
            net = round(kg * (1 - pct / 100))
            d.update(kg=kg, deductions={k: v for k, v in (("unripe", unripe), ("dirt", dirt)) if v}, deduction_pct=pct,
                     net_kg=net, price_per_kg=ref, currency="IDR", amount=round(net * ref), price_basis="reference price",
                     offer_id=None, po_number=None, farmer_name=out["farmers"][d["farmer_id"]]["name"])
        for p in promises.values():
            p["kg"] = round(p["kg"] * kg_range[1] / 2200 / 10) * 10 or p["kg"]
        out["promises"].update(promises)
        out["deliveries"].update(deliveries)
        f = out["farmers"][ids[0]]
        price = round(ref * 1.04 / 50) * 50
        out["offers"][f"offer-{cid}-1"] = {
            "campaign_id": cid, "farmer_id": ids[0], "farmer_name": f["name"], "village": f["village"], "kind": "farmer",
            "crop": crop, "kg": kg_range[1], "price_per_kg": price, "reference_price": ref,
            "premium_pct": round((price - ref) / ref * 100, 1), "currency": "IDR", "deliver_week": 2,
            "deliver_week_start": week_start(2, plan_start).isoformat(), "from_week": None, "from_week_start": None,
            "harvest_id": None, "status": "pending", "requested_price": None, "call_id": None, "source": "call",
            "confirmed_by_voice": False, "created_at": "2026-10-16T09:00:00+00:00",
            "negotiation": {"first_offer": price, "counter": None, "rung": 0}}
        return ids

    # Palm, Kampar: a smaller area; farmers harvest every 14 days and few start in week 2, so week 2 is short.
    campaign("palm-kampar", "palm", "Palm, Kampar", 18_000, 4_000, 8_000, 3100.0, 2900.0, 3350.0, KAMPAR_VILLAGES, 24,
             (900, 2200), [1] * 11 + [2] * 5 + [3] * 3 + [4] * 5, 14)
    # Rubber: tappers sell slab rubber about every week; small loads, a factory taking 2.5 t a day.
    campaign("rubber", "rubber", None, 12_000, 2_500, 4_000, 12_500.0, 11_500.0, 13_800.0, RUBBER_VILLAGES, 26,
             (300, 800), [1, 1, 1, 1, 1, 2], 7)
    return out


def load_seed(store, settings, more_campaigns: bool = True) -> None:
    from . import services

    data = build_seed(settings.plan_start, settings.demo_language, settings.demo_crop,
                      settings.target_kg_per_week)
    if more_campaigns and settings.multi_crop:
        for coll, docs in _more_campaigns(settings.plan_start, settings.demo_language).items():
            data.setdefault(coll, {}).update(docs)
    for coll in ("farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes",
                 "campaigns", "promises", "deliveries", "messages", "official_prices"):
        store.clear(coll)
    for coll, docs in data.items():
        for doc_id, doc in docs.items():
            if coll == "deliveries":
                doc = {**doc, "farmer_name": data["farmers"].get(doc["farmer_id"], {}).get("name", doc["farmer_id"])}
            store.set(coll, doc_id, doc)
    services.recompute_forecast(store, settings)


if __name__ == "__main__":
    from .config import get_settings
    from .store import make_store

    s = get_settings()
    load_seed(make_store(s.store_backend, s.gcp_project), s)
    print(f"Seeded {s.store_backend} store, plan starts {s.plan_start}.")
