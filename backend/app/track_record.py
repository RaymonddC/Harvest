"""Closing the loop: what each farmer promised for a week, what they delivered, and what that says.

Every Monday the weekly job saves a snapshot of what each farmer promised for the week that starts (their
harvest rounds in it, plus approved deals moving supply in or out). Deliveries from the weighbridge are then
recorded against it, by hand or from a CSV. From the two:

- forecast accuracy per week (promised total against delivered total, for weeks with deliveries recorded),
- each farmer's reliability: of what they promised, the share they delivered (needs at least 2 recorded
  weeks), and
- a "likely" figure for the coming weeks: each farmer's expected supply scaled by their reliability.

The forecast itself keeps showing what farmers said, so gap detection does not move with a few deliveries;
the likely figure sits next to it.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections import defaultdict

from . import forecast as fc
from .config import Settings, normalize_phone
from .rules_engine import normalize_crop
from .services import ServiceError
from .store import Store

MIN_WEEKS_FOR_RELIABILITY = 2


class TrackRecordError(ServiceError):
    pass


def monday(d: dt.date | str) -> dt.date:
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    return d - dt.timedelta(days=d.weekday())


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _crop_of(settings: Settings, farmer: dict) -> str:
    return normalize_crop(farmer.get("crop") or settings.demo_crop)


def promised_in_week(store: Store, settings: Settings, week: dt.date) -> dict[tuple[str, str], float]:
    """What each (farmer, crop) is expected to deliver in the calendar week starting `week` (raw kg, as said)."""
    week = monday(week)
    end = week + dt.timedelta(days=6)
    out: dict[tuple[str, str], float] = defaultdict(float)
    for h in store.list("harvests"):
        for date, _projected in fc.harvest_rounds(h, end):
            if week <= date <= end:
                out[(h["farmer_id"], normalize_crop(h.get("crop") or settings.demo_crop))] += float(h.get("kg", 0))
    for o in store.list("offers"):
        if o.get("status") != "approved":
            continue
        key = (o["farmer_id"], normalize_crop(o.get("crop") or settings.demo_crop))
        if o.get("deliver_week_start") and monday(o["deliver_week_start"]) == week:
            out[key] += float(o.get("kg", 0))
        if o.get("from_week_start") and monday(o["from_week_start"]) == week:
            out[key] -= float(o.get("kg", 0))
    return {k: v for k, v in out.items() if v > 0}


def _promise_id(farmer_id: str, crop: str, week: dt.date) -> str:
    return f"p-{farmer_id}-{crop}-{week.isoformat()}"


def snapshot_promises(store: Store, settings: Settings, week: dt.date, farmer_id: str | None = None) -> int:
    """Save the promises for one week. An existing snapshot is never overwritten: it is what was promised then."""
    week = monday(week)
    saved = 0
    for (fid, crop), kg in promised_in_week(store, settings, week).items():
        if farmer_id and fid != farmer_id:
            continue
        pid = _promise_id(fid, crop, week)
        if store.get("promises", pid):
            continue
        store.set("promises", pid, {"farmer_id": fid, "crop": crop, "week_start": week.isoformat(), "kg": round(kg),
                                    "saved_at": _now()})
        saved += 1
    return saved


def record_delivery(store: Store, settings: Settings, farmer_id: str, kg: float, date: str,
                    recorded_by: str | None = None, source: str = "manual") -> dict:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise TrackRecordError("Farmer not found.")
    try:
        day = dt.date.fromisoformat(str(date)[:10])
    except ValueError as e:
        raise TrackRecordError("The delivery date must be YYYY-MM-DD.") from e
    if day > dt.date.today() + dt.timedelta(days=1):
        raise TrackRecordError("A delivery cannot be in the future.")
    if not 0 < float(kg) <= 200_000:
        raise TrackRecordError("Delivered kg must be between 1 and 200000.")
    crop = _crop_of(settings, farmer)
    week = monday(day)
    # No Monday snapshot for this week (the job was not running, or the week is older): save one now, from the
    # records as they are, so the delivery has something to be compared with.
    snapshot_promises(store, settings, week, farmer_id)
    doc = {"farmer_id": farmer_id, "farmer_name": farmer.get("name", farmer_id), "crop": crop, "kg": round(float(kg)),
           "date": day.isoformat(), "week_start": week.isoformat(), "source": source,
           "recorded_by": recorded_by or "Planner", "recorded_at": _now()}
    did = store.add("deliveries", doc)
    return {**doc, "id": did}


def upload_deliveries(store: Store, settings: Settings, text: str, recorded_by: str | None = None) -> dict:
    """CSV from the weighbridge: date, kg, and the farmer by phone (best), id or exact name."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not {"date", "kg"} <= cols or not cols & {"phone", "farmer_id", "name"}:
        raise TrackRecordError("The CSV needs the columns date and kg, and phone, farmer_id or name for the farmer.")
    farmers = store.list("farmers")
    by_phone = {normalize_phone(f.get("phone", "")): f for f in farmers if f.get("phone")}
    by_id = {f["id"]: f for f in farmers}
    by_name = {f.get("name", "").strip().lower(): f for f in farmers}
    added, problems = 0, []
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        f = (by_phone.get(normalize_phone(row["phone"])) if row.get("phone") else None) \
            or by_id.get(row.get("farmer_id", "")) or by_name.get(row.get("name", "").lower())
        if not f:
            problems.append(f"line {n}: no farmer matches")
            continue
        try:
            record_delivery(store, settings, f["id"], float(row["kg"].replace(",", "")), row["date"], recorded_by, "csv")
            added += 1
        except (TrackRecordError, ValueError) as e:
            problems.append(f"line {n}: {e}")
    return {"added": added, "problems": problems[:20]}


def _recorded_weeks(deliveries: list[dict]) -> set[tuple[str, str]]:
    """(crop, week) pairs that have deliveries recorded: a farmer with nothing in such a week delivered nothing."""
    return {(d["crop"], d["week_start"]) for d in deliveries}


def farmer_record(store: Store, farmer_id: str) -> dict:
    promises = [p for p in store.list("promises") if p["farmer_id"] == farmer_id]
    deliveries = store.list("deliveries")
    recorded = _recorded_weeks(deliveries)
    mine = [d for d in deliveries if d["farmer_id"] == farmer_id]
    delivered = defaultdict(float)
    for d in mine:
        delivered[(d["crop"], d["week_start"])] += float(d["kg"])
    weeks = []
    for p in sorted(promises, key=lambda p: p["week_start"]):
        key = (p["crop"], p["week_start"])
        if key not in recorded:
            continue
        weeks.append({"week_start": p["week_start"], "crop": p["crop"], "promised": p["kg"], "delivered": round(delivered[key])})
    rel = None
    if len(weeks) >= MIN_WEEKS_FOR_RELIABILITY:
        promised = sum(w["promised"] for w in weeks)
        rel = round(sum(min(w["delivered"], w["promised"]) for w in weeks) / promised, 3) if promised else None
    return {"farmer_id": farmer_id, "reliability": rel, "weeks": weeks,
            "deliveries": sorted(mine, key=lambda d: d["date"], reverse=True)}


def reliabilities(store: Store) -> dict[str, float]:
    """Every farmer with enough recorded weeks: farmer id -> share of promised kg delivered (0 to 1)."""
    promises = store.list("promises")
    deliveries = store.list("deliveries")
    recorded = _recorded_weeks(deliveries)
    delivered = defaultdict(float)
    for d in deliveries:
        delivered[(d["farmer_id"], d["crop"], d["week_start"])] += float(d["kg"])
    per = defaultdict(lambda: [0, 0.0, 0.0])  # weeks, promised, kept
    for p in promises:
        if (p["crop"], p["week_start"]) not in recorded:
            continue
        got = delivered[(p["farmer_id"], p["crop"], p["week_start"])]
        rec = per[p["farmer_id"]]
        rec[0] += 1
        rec[1] += p["kg"]
        rec[2] += min(got, p["kg"])
    return {fid: round(kept / promised, 3) for fid, (n, promised, kept) in per.items()
            if n >= MIN_WEEKS_FOR_RELIABILITY and promised}


def summary(store: Store, settings: Settings, crop: str | None = None) -> dict:
    crop = normalize_crop(crop) if crop else normalize_crop(settings.demo_crop)
    promises = [p for p in store.list("promises") if p["crop"] == crop]
    deliveries = [d for d in store.list("deliveries") if d["crop"] == crop]
    recorded = sorted({d["week_start"] for d in deliveries})
    weeks = []
    for w in recorded:
        promised = sum(p["kg"] for p in promises if p["week_start"] == w)
        got = sum(d["kg"] for d in deliveries if d["week_start"] == w)
        acc = round(1 - abs(got - promised) / promised, 3) if promised else None
        weeks.append({"week_start": w, "promised": round(promised), "delivered": round(got),
                      "accuracy": max(acc, 0) if acc is not None else None})
    accs = [w["accuracy"] for w in weeks if w["accuracy"] is not None]
    rel = reliabilities(store)
    farmers = {f["id"]: f for f in store.list("farmers") if _crop_of(settings, f) == crop}
    rated = [r for fid, r in rel.items() if fid in farmers]
    return {
        "crop": crop,
        "weeks": weeks[-8:],
        "accuracy": round(sum(accs) / len(accs), 3) if accs else None,
        "farmers_rated": len(rated),
        "reliable": sum(1 for r in rated if r >= 0.9),
        "unreliable": sum(1 for r in rated if r < 0.7),
        "likely": likely_supply(store, settings, crop, rel),
    }


def likely_supply(store: Store, settings: Settings, crop: str, rel: dict[str, float] | None = None) -> dict[str, int]:
    """For each forecast week (W1, W2...): expected supply with each farmer's part scaled by their reliability.
    Farmers without a track record count in full. Approved deals count in full (the planner approved them)."""
    rel = rel if rel is not None else reliabilities(store)
    rows = {r["week"]: r for r in store.list("forecast")
            if normalize_crop(r.get("crop") or settings.demo_crop) == crop and "week" in r}
    if not rows:
        return {}
    weeks = max(rows)
    end = fc.week_start(weeks, settings.plan_start) + dt.timedelta(days=6)
    shortfall = defaultdict(float)
    for h in store.list("harvests"):
        if normalize_crop(h.get("crop") or settings.demo_crop) != crop:
            continue
        r = rel.get(h["farmer_id"])
        if r is None or r >= 1:
            continue
        weight = fc.UNSURE_WEIGHT if fc.is_unsure(h) else 1.0
        for date, _ in fc.harvest_rounds(h, end):
            w = fc.week_index(date, settings.plan_start, weeks)
            if w:
                shortfall[w] += float(h.get("kg", 0)) * weight * (1 - r)
    return {rows[w].get("id", fc.week_label(w)): round(max(rows[w]["expected_kg"] - shortfall[w], 0)) for w in sorted(rows)}
