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
# Where each village's plots sit: around Pekanbaru, Perawang and Minas, on the road network, so the plots cluster
# like real smallholdings on the map and Google can route each one to a mill (mills.py). Plots are within ~3 km.
VILLAGE_CENTRES = {"Tanjung Sari": (0.615, 101.43), "Bukit Raya": (0.455, 101.47), "Lirik": (0.72, 101.62),
                   "Air Molek": (0.80, 101.34), "Pematang Reba": (0.43, 101.60), "Sungai Lala": (0.49, 101.27),
                   "Pekanbaru": (0.51, 101.44)}
PLOT_JITTER = 0.03


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
        clat, clng = VILLAGE_CENTRES.get(f.get("village"), (0.6, 101.45))
        f.update(plot_lat=round(clat + ops.uniform(-PLOT_JITTER, PLOT_JITTER), 5),
                 plot_lng=round(clng + ops.uniform(-PLOT_JITTER, PLOT_JITTER), 5), plot_ha=round(ops.uniform(1.2, 4.0), 1))
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
        if d["date"] < (plan_start - dt.timedelta(days=14)).isoformat():  # older deliveries are paid; the last ones wait
            d.update(paid=True, paid_at=f"{d['date']}T15:00:00+07:00", paid_by="Finance", payment_ref=f"TRF-{d['date'].replace('-', '')}-{d['farmer_id']}")
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


# Two mills in Riau towns on the road network (so Google can route to them), so each farmer has a nearest one (mills.py).
DEMO_MILLS = {"mill-main": {"name": "Sawit Maju mill, Pekanbaru", "lat": 0.5071, "lng": 101.4478},
              "mill-perawang": {"name": "Sawit Maju mill, Perawang", "lat": 0.6466, "lng": 101.607}}


# ---------- last week's calls and the planner's notes, so the relationship features have something to show ----------

DEMO_CALLS = [  # (hours ago, sentiment, score, summary, concerns, transcript)
    (5, "positive", 0.7, "Expects about 1.8 t ready next Tuesday and is happy with last month's price. Asked to be called again next week.",
     [], [("agent", "Selamat pagi Pak, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat percakapan ini?"),
          ("farmer", "Boleh, silakan."), ("agent", "Kira-kira berapa ton TBS yang siap minggu depan?"),
          ("farmer", "Sekitar satu koma delapan ton, hari Selasa. Harga bulan lalu bagus.")]),
    (9, "negative", -0.6, "Will deliver about 1.2 t but is unhappy: the last payment came two weeks late. Wants to know when it will be paid.",
     ["late payment"], [("agent", "Selamat siang Bu, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat percakapan ini?"),
                        ("farmer", "Boleh. Tapi pembayaran kemarin terlambat dua minggu."),
                        ("agent", "Maaf atas keterlambatannya, saya catat untuk tim kami. Berapa ton yang siap minggu depan?"),
                        ("farmer", "Satu koma dua ton. Tolong pembayarannya dipercepat.")]),
    (20, "neutral", 0.1, "Harvest of about 2.1 t, but the road to the plot is flooded after the rain; may be two days late.",
     ["flooded road", "transport"], [("agent", "Selamat sore Pak, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat?"),
                                     ("farmer", "Boleh."), ("farmer", "Panen sekitar dua ton, tapi jalan ke kebun banjir, mungkin telat dua hari.")]),
    (30, "negative", -0.5, "Says a rival buyer offers Rp 150 more per kg and may sell there unless the price improves.",
     ["low price", "rival buyer"], [("agent", "Selamat pagi Bu, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat?"),
                                    ("farmer", "Boleh. Pengepul sebelah kasih seratus lima puluh lebih mahal per kilo.")]),
    (52, "positive", 0.8, "Firm 2.4 t for next week and offered to bring it early if the mill needs it.",
     [], [("agent", "Selamat pagi Pak, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat?"),
          ("farmer", "Boleh. Dua koma empat ton, bisa diantar lebih awal kalau perlu.")]),
    (75, "positive", 0.5, "About 1.5 t ready on Thursday; no concerns.",
     [], [("agent", "Selamat siang Bu, saya asisten AI dari Koperasi Sawit Maju. Boleh saya catat?"),
          ("farmer", "Boleh. Sekitar satu setengah ton hari Kamis.")]),
]


def demo_history(store, settings) -> None:
    """A few calls from the last days that the farmers agreed to keep, each with Gemini's summary and mood (two unhappy:
    late payment, a rival's price), and the planner's notes: an open complaint, a follow-up due today, feedback.
    Only for the full demo (load_seed with more_campaigns); the tests run without it."""
    now = dt.datetime.now(dt.timezone.utc)
    today = (now + dt.timedelta(hours=7)).date()
    farmers = sorted((f for f in store.list("farmers") if f["id"].startswith("b") and f.get("type") != "supplier"),
                     key=lambda f: f["id"])
    picks = farmers[3:3 + len(DEMO_CALLS)]
    for f, (hours, mood, score, summary, concerns, lines) in zip(picks, DEMO_CALLS):
        end = now - dt.timedelta(hours=hours)
        iso = lambda t: t.isoformat(timespec="seconds")  # noqa: E731
        store.add("calls", {"farmer_id": f["id"], "farmer_name": f.get("name"), "kind": "collect", "status": "done",
                            "outcome": "completed", "attempt": 1, "channel": "twilio", "campaign_id": f.get("campaign_id"),
                            "created_at": iso(end - dt.timedelta(minutes=4)), "started_at": iso(end - dt.timedelta(minutes=3)),
                            "ended_at": iso(end), "consent": True, "summary": summary,
                            "transcript": [{"who": w, "text": t} for w, t in lines],
                            "insights": {"summary": summary, "sentiment": mood, "score": score, "concerns": concerns, "at": iso(end)}})
    if len(picks) >= 4:
        notes = [(picks[1], "complaint", "Last payment arrived two weeks late. Promised to check with finance.", 2, None),
                 (picks[2], "call", "Road to the plot is flooded. Call back to fix a new pickup day.", None, today.isoformat()),
                 (picks[3], "note", "Rival buyer near Minas pays Rp 150/kg more. Discuss a loyalty premium.", None,
                  (today + dt.timedelta(days=1)).isoformat()),
                 (picks[0], "feedback", "Happy with the price and the quick weighing.", 5, None)]
        for f, kind, text, rating, follow in notes:
            store.add("notes", {"farmer_id": f["id"], "farmer_name": f.get("name"), "kind": kind, "text": text,
                                "rating": rating, "follow_up_on": follow, "done": False, "by": "Dewi",
                                "at": (now - dt.timedelta(days=1)).isoformat(timespec="seconds")})


def load_seed(store, settings, more_campaigns: bool = True, english_agent: bool = True) -> None:
    """english_agent: the demo campaigns' agent calls in English (switching to the farmer's language when they answer
    in it). The tests keep the agent on each farmer's own language (Bahasa Indonesia), as they were written for."""
    from . import agent_profile, services

    data = build_seed(settings.plan_start, settings.demo_language, settings.demo_crop,
                      settings.target_kg_per_week)
    if more_campaigns and settings.multi_crop:
        for coll, docs in _more_campaigns(settings.plan_start, settings.demo_language).items():
            data.setdefault(coll, {}).update(docs)
    if english_agent:
        for camp in data.get("campaigns", {}).values():
            camp.setdefault("persona", dict(agent_profile.NEW_CAMPAIGN_PERSONA))
    for coll in ("farmers", "calls", "harvests", "forecast", "offers", "limits", "rival_quotes",
                 "campaigns", "promises", "deliveries", "messages", "official_prices", "notes", "briefs"):
        store.clear(coll)
    for coll, docs in data.items():
        for doc_id, doc in docs.items():
            if coll == "deliveries":
                doc = {**doc, "farmer_name": data["farmers"].get(doc["farmer_id"], {}).get("name", doc["farmer_id"])}
            store.set(coll, doc_id, doc)
    if more_campaigns:
        demo_history(store, settings)
    if not store.list("mills"):  # the mills are the planner's setup: a reset keeps them, a new store gets two
        for mill_id, mill in DEMO_MILLS.items():
            store.set("mills", mill_id, mill)
    services.recompute_forecast(store, settings)


if __name__ == "__main__":
    from .config import get_settings
    from .store import make_store

    s = get_settings()
    load_seed(make_store(s.store_backend, s.gcp_project), s)
    print(f"Seeded {s.store_backend} store, plan starts {s.plan_start}.")
