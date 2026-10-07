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
    return {
        "farmers": farmers,
        "harvests": harvests,
        "limits": {crop: limits_doc},
        "rival_quotes": rival_quotes,
        "campaigns": {"current": {"status": "idle", "kind": None, "target_kg_per_week": target_kg}},
    }


def load_seed(store, settings) -> None:
    from . import services

    data = build_seed(settings.plan_start, settings.demo_language, settings.demo_crop,
                      settings.target_kg_per_week)
    for coll in ("farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes",
                 "campaigns"):
        store.clear(coll)
    for coll, docs in data.items():
        for doc_id, doc in docs.items():
            store.set(coll, doc_id, doc)
    services.recompute_forecast(store, settings)


if __name__ == "__main__":
    from .config import get_settings
    from .store import make_store

    s = get_settings()
    load_seed(make_store(s.store_backend, s.gcp_project), s)
    print(f"Seeded {s.store_backend} store, plan starts {s.plan_start}.")
