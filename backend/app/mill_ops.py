"""Mill operations around the weekly forecast.

- Capacity: a campaign's mill capacity per day and the working days, so days and weeks over capacity show up
  (palm fruit spoils within a day or two, so the mill must be filled every day, not only every week).
- Trucks: how many truck loads each day's supply needs.
- Supply by period: expected supply, deliveries (net, after grading), target and capacity, by day, week, month or year.
- Surplus: farmers whose harvest falls in a week over capacity, and moving one to a later date.
- Official reference price: the provincial plantation office's published farmgate price; a price range can follow it.
- Traceability: the farmer's plot (location, area, certification) behind every delivery, and deliveries that are
  too large for the plot.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
from collections import defaultdict

from . import forecast as fc
from . import mills, services
from .config import Settings, today_local
from .rules_engine import CROP_LABELS, normalize_crop
from .store import Store

DEFAULT_WORKING_DAYS = 6  # Monday to Saturday
DEFAULT_TRUCK_KG = 8_000
MAX_DAYS = 400
# Smallholder palm rarely yields more than about 30 t of fruit per hectare per year: more than that from one plot
# usually means fruit bought from somewhere else (a traceability problem).
MAX_T_PER_HA_YEAR = 30.0
# Capacity is a hard limit (a full mill cannot press more), so only a small margin: over 5% is a surplus.
SURPLUS_TOLERANCE = 0.05


class MillOpsError(services.ServiceError):
    pass


def _day(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


# ---------- capacity and trucks ----------

def working_days(camp: dict) -> int:
    return int(camp.get("working_days") or DEFAULT_WORKING_DAYS)


def is_working_day(camp: dict, day: dt.date) -> bool:
    return day.weekday() < working_days(camp)


def daily_capacity(camp: dict) -> int | None:
    v = camp.get("daily_capacity_kg")
    return int(v) if v else None


def weekly_capacity(camp: dict) -> int | None:
    cap = daily_capacity(camp)
    return cap * working_days(camp) if cap else None


def truck_kg(camp: dict) -> int:
    return int(camp.get("truck_kg") or DEFAULT_TRUCK_KG)


def check_capacity_fields(daily_capacity_kg, working_days_, truck_kg_) -> dict:
    out = {}
    if daily_capacity_kg is not None:
        if daily_capacity_kg and not 0 < float(daily_capacity_kg) <= 5_000_000:
            raise MillOpsError("The mill's capacity per day must be between 1 kg and 5,000 t.")
        out["daily_capacity_kg"] = round(float(daily_capacity_kg)) if daily_capacity_kg else None
    if working_days_ is not None:
        if not 1 <= int(working_days_) <= 7:
            raise MillOpsError("Working days per week must be 1 to 7.")
        out["working_days"] = int(working_days_)
    if truck_kg_ is not None:
        if not 500 <= float(truck_kg_) <= 60_000:
            raise MillOpsError("A truck load must be between 0.5 and 60 t.")
        out["truck_kg"] = round(float(truck_kg_))
    return out


def mark_surplus(camp: dict, rows: list[dict], tolerance: float = SURPLUS_TOLERANCE) -> list[dict]:
    """Weeks whose expected supply is over the mill's capacity (by more than SURPLUS_TOLERANCE) are a surplus."""
    cap = weekly_capacity(camp)
    for r in rows:
        r["capacity_kg"] = cap
        over = (r["expected_kg"] - cap) if cap else 0
        r["surplus_kg"] = round(max(over, 0))
        r["is_surplus"] = bool(cap and r["expected_kg"] > cap * (1 + tolerance))
    return rows


# ---------- expected supply by day ----------

def _spread(kg: float, week_start: dt.date, camp: dict) -> list[tuple[dt.date, float]]:
    days = [week_start + dt.timedelta(days=i) for i in range(7) if is_working_day(camp, week_start + dt.timedelta(days=i))]
    return [(d, kg / len(days)) for d in days] if days else []


def expected_by_day(store: Store, settings: Settings, camp: dict, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Expected kg per day: each harvest on its ready date (and later projected rounds), unsure answers at half;
    approved deals spread over the working days of their delivery week (and taken off the week they came from)."""
    out: dict[dt.date, float] = defaultdict(float)
    for h in services.campaign_records(store, settings, camp["id"], "harvests"):
        weight = fc.UNSURE_WEIGHT if fc.is_unsure(h) else 1.0
        for d, _ in fc.harvest_rounds(h, end):
            if start <= d <= end:
                out[d] += float(h.get("kg", 0)) * weight
    for o in services.campaign_records(store, settings, camp["id"], "offers"):
        if o.get("status") != "approved":
            continue
        kg = float(o.get("kg", 0))
        for key, sign in (("deliver_week", 1), ("from_week", -1)):
            ws = _day(o.get(f"{key}_start")) or (fc.week_start(int(o[key]), settings.plan_start) if o.get(key) else None)
            if ws:
                for d, part in _spread(kg, ws, camp):
                    if start <= d <= end:
                        out[d] += sign * part
    return out


def delivered_by_day(store: Store, settings: Settings, camp: dict, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    out: dict[dt.date, float] = defaultdict(float)
    for d in services.campaign_records(store, settings, camp["id"], "deliveries"):
        day = _day(d.get("date"))
        if day and start <= day <= end:
            out[day] += float(d.get("net_kg", d.get("kg", 0)))
    return out


def _bucket(day: dt.date, period: str) -> dt.date:
    if period == "week":
        return day - dt.timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    if period == "year":
        return day.replace(month=1, day=1)
    return day


def _label(start: dt.date, period: str) -> str:
    return {"day": f"{start:%a} {start.day} {start:%b}", "week": f"Week of {start.day} {start:%b}",
            "month": f"{start:%b %Y}", "year": f"{start:%Y}"}[period]


def supply_series(store: Store, settings: Settings, campaign: str | None, period: str, start: dt.date,
                  end: dt.date, today: dt.date | None = None) -> dict:
    """Expected supply, net deliveries, target and capacity per day, week, month or year."""
    if period not in ("day", "week", "month", "year"):
        raise MillOpsError("Period must be day, week, month or year.")
    if end < start:
        raise MillOpsError("The end date is before the start date.")
    if (end - start).days > MAX_DAYS * (10 if period == "year" else 1):
        raise MillOpsError("That range is too long for this view.")
    today = today or today_local()
    camp = services.need_campaign(store, settings, campaign)
    target_week = int(camp.get("target_kg_per_week") or settings.target_kg_per_week)
    wd = working_days(camp)
    cap_day, tkg = daily_capacity(camp), truck_kg(camp)
    first, last = services.campaign_dates(settings, camp)
    # Beyond the forecast's last week nothing is planned yet (harvest answers reach a few weeks ahead).
    horizon = settings.plan_start + dt.timedelta(days=7 * services.campaign_weeks(settings, camp) - 1)
    expected = expected_by_day(store, settings, camp, start, end)
    delivered = delivered_by_day(store, settings, camp, start, end)
    buckets: dict[dt.date, dict] = {}
    d = start
    while d <= end:
        key = _bucket(d, period)
        b = buckets.setdefault(key, {"start": key.isoformat(), "label": _label(key, period), "expected_kg": 0.0,
                                     "delivered_kg": 0.0, "target_kg": 0.0, "capacity_kg": 0.0 if cap_day else None,
                                     "days": 0, "past": True, "trucks": 0, "over_days": 0})
        work = is_working_day(camp, d)
        in_campaign = first <= d <= last
        e = expected.get(d, 0.0)
        b["expected_kg"] += e
        b["delivered_kg"] += delivered.get(d, 0.0)
        if work and in_campaign:
            b["target_kg"] += target_week / wd
        if work and cap_day:
            b["capacity_kg"] += cap_day
        if d >= today:
            b["past"] = False
        b["trucks"] += math.ceil(e / tkg) if e > 0 else 0
        if cap_day and e > cap_day:
            b["over_days"] += 1
        b["days"] += 1
        b["end"] = d.isoformat()
        d += dt.timedelta(days=1)
    rows = []
    for b in buckets.values():
        for k in ("expected_kg", "delivered_kg", "target_kg"):
            b[k] = round(b[k])
        if b["capacity_kg"] is not None:
            b["capacity_kg"] = round(b["capacity_kg"])
        b["is_gap"] = bool(b["target_kg"] and not b["past"] and b["expected_kg"] < b["target_kg"] * (1 - settings.gap_tolerance))
        b["is_surplus"] = bool(b["capacity_kg"] and b["expected_kg"] > b["capacity_kg"] * (1 + SURPLUS_TOLERANCE))
        b["beyond"] = dt.date.fromisoformat(b["start"]) > horizon
        if b["beyond"]:
            b["is_gap"] = False
        rows.append(b)
    return {"campaign_id": camp["id"], "period": period, "start": start.isoformat(), "end": end.isoformat(),
            "daily_capacity_kg": cap_day, "working_days": wd, "truck_kg": tkg, "rows": rows}


# ---------- surplus: who could deliver later ----------

def surplus_farmers(store: Store, settings: Settings, campaign: str | None, week: int) -> list[dict]:
    """Farmers whose harvest falls in a week over capacity, biggest first: the ones to ask to deliver later.
    Farmers with an approved deal for that week are left out (the mill asked for that fruit)."""
    camp = services.need_campaign(store, settings, campaign)
    weeks = services.campaign_weeks(settings, camp)
    dealt = {o["farmer_id"] for o in services.campaign_records(store, settings, camp["id"], "offers")
             if o.get("status") == "approved" and fc.week_of_offer(o, "deliver_week", settings.plan_start, weeks) == week}
    farmers = {f["id"]: f for f in store.list("farmers")}
    out = []
    for h in services.campaign_records(store, settings, camp["id"], "harvests"):
        if fc.week_index(h["ready_date"], settings.plan_start, weeks) != week or h["farmer_id"] in dealt:
            continue
        f = farmers.get(h["farmer_id"], {})
        out.append({"farmer_id": h["farmer_id"], "name": f.get("name", h["farmer_id"]), "village": f.get("village", ""),
                    "kg": h.get("kg", 0), "ready_date": h["ready_date"], "confidence": h.get("confidence")})
    return sorted(out, key=lambda x: -x["kg"])


def reschedule_harvest(store: Store, settings: Settings, farmer_id: str, to_date: str, reason: str = "",
                       actor=None) -> dict:
    """Move a farmer's harvest to a later date, as agreed with them (for a week over the mill's capacity).
    The farmer gets a text with the new date (recorded in the outbox; sent when texting is on)."""
    from . import messaging

    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise MillOpsError("Farmer not found.", status=404)
    crop = services.farmer_crop(settings, farmer)
    hid = f"h-{farmer_id}-{crop}"
    h = store.get("harvests", hid)
    if not h:
        raise MillOpsError("This farmer has no harvest on record to move.")
    new = _day(to_date)
    old = _day(h.get("ready_date"))
    if not new:
        raise MillOpsError("The new date must look like 2026-11-09.")
    if old and new <= old:
        raise MillOpsError("Pick a later date: moving a harvest earlier is a gap-fill deal, not a reschedule.")
    if old and (new - old).days > 21:
        raise MillOpsError("Fruit cannot wait more than three weeks; pick a date closer to the harvest.")
    store.set("harvests", hid, {"ready_date": new.isoformat(), "rescheduled_from": h.get("ready_date"),
                                "reschedule_reason": (reason or "mill over capacity")[:200],
                                "rescheduled_by": actor.name if actor else "Planner",
                                "rescheduled_at": services.now_iso(), "updated_at": services.now_iso()}, merge=True)
    services.recompute_forecast(store, settings)
    messaging.send(store, settings, farmer.get("phone", ""),
                   f"{settings.mill_name}: please bring your harvest on {new:%A %d %B} instead of {old:%d %B}. "
                   "The mill is full that week. Thank you.", "reschedule", farmer_id=farmer_id)
    return {"farmer_id": farmer_id, "from": h.get("ready_date"), "to": new.isoformat()}


# ---------- official reference price ----------

def add_official_price(store: Store, settings: Settings, crop: str, province: str, valid_from: str,
                       price_per_kg: float, source: str = "", url: str = "", actor=None) -> dict:
    """Record a published farmgate price (for palm fruit in Indonesia: the provincial plantation office's TBS price,
    usually for mature trees). Price ranges that follow it move with it."""
    key = normalize_crop(crop)
    if key not in CROP_LABELS:
        raise MillOpsError(f"Unknown crop {crop!r}.")
    day = _day(valid_from)
    if not day:
        raise MillOpsError("The date must look like 2026-10-14.")
    if not 0 < float(price_per_kg) <= 1_000_000:
        raise MillOpsError("The price per kg does not look right.")
    if not (province or "").strip():
        raise MillOpsError("Name the province (for example Riau).")
    pid = f"op-{key}-{province.strip().lower().replace(' ', '-')}-{day.isoformat()}"
    doc = {"crop": key, "province": province.strip(), "valid_from": day.isoformat(), "price_per_kg": round(float(price_per_kg), 2),
           "source": (source or "").strip()[:120] or None, "url": (url or "").strip()[:300] or None,
           "added_by": actor.name if actor else "Planner", "added_at": services.now_iso()}
    store.set("official_prices", pid, doc)
    apply_official_price(store, settings, key)
    return {"id": pid, **doc}


def latest_official(store: Store, crop: str, province: str | None = None) -> dict | None:
    rows = [p for p in store.list("official_prices") if p.get("crop") == crop
            and (not province or p.get("province", "").lower() == province.lower())
            and (_day(p.get("valid_from")) or dt.date.max) <= today_local()]
    return max(rows, key=lambda p: p["valid_from"], default=None)


def follow_official(store: Store, settings: Settings, crop: str, province: str | None, enabled: bool) -> dict:
    key = normalize_crop(crop)
    if not store.get("limits", key):
        raise MillOpsError("Set a price range for this crop first.")
    store.set("limits", key, {"follows_official": bool(enabled), "official_province": (province or "").strip() or None},
              merge=True)
    return apply_official_price(store, settings, key) or store.get("limits", key)


def apply_official_price(store: Store, settings: Settings, crop: str) -> dict | None:
    """When the crop's price range follows the official price, set its reference to the latest one; the floor and
    ceiling move with it, keeping their distance from the reference in percent."""
    lim = store.get("limits", crop)
    if not lim or not lim.get("follows_official"):
        return None
    op = latest_official(store, crop, lim.get("official_province"))
    if not op or float(op["price_per_kg"]) == float(lim["reference_price"]):
        if op:
            store.set("limits", crop, {"reference_source": _source_text(op), "official_price_id": op.get("id")}, merge=True)
        return None
    ratio = float(op["price_per_kg"]) / float(lim["reference_price"])
    inc = float(lim.get("price_increment", 10.0)) or 10.0
    snap = lambda v: round(round(v / inc) * inc, 2)  # noqa: E731
    doc = services.set_limits(store, crop, snap(float(lim["floor_price"]) * ratio), snap(float(lim["ceiling_price"]) * ratio),
                              float(op["price_per_kg"]), float(lim.get("first_premium_pct", 4.0)), float(lim.get("step_pct", 2.0)))
    store.set("limits", crop, {"follows_official": True, "official_province": lim.get("official_province"),
                               "reference_source": _source_text(op)}, merge=True)
    services.recompute_forecast(store, settings)
    return doc


def _source_text(op: dict) -> str:
    return f"Official price, {op['province']}, from {op['valid_from']}" + (f" ({op['source']})" if op.get("source") else "")


# ---------- traceability ----------

def plot_fields(row: dict) -> dict:
    """Optional plot details on a farmer row: plot_lat, plot_lng, plot_ha, certification."""
    out = {}
    lat, lng = (row.get("plot_lat") or "").strip(), (row.get("plot_lng") or "").strip()
    if lat or lng:
        try:
            la, lo = float(lat), float(lng)
        except ValueError:
            raise services.ServiceError("The plot location needs a latitude and a longitude, as numbers.") from None
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            raise services.ServiceError("The plot location is outside the map.")
        out.update(plot_lat=round(la, 6), plot_lng=round(lo, 6))
    ha = (row.get("plot_ha") or "").strip()
    if ha:
        try:
            v = float(ha)
        except ValueError:
            raise services.ServiceError("The plot area must be a number of hectares.") from None
        if not 0 < v <= 10_000:
            raise services.ServiceError("The plot area must be between 0 and 10,000 ha.")
        out["plot_ha"] = round(v, 2)
    cert = (row.get("certification") or "").strip()
    if cert:
        out["certification"] = cert[:40]
    return out


def plausibility(store: Store, settings: Settings, farmer: dict, today: dt.date | None = None) -> dict | None:
    """Net kg delivered by a farmer over the last 365 days against what their plot can grow."""
    today = today or today_local()
    ha = farmer.get("plot_ha")
    since = today - dt.timedelta(days=365)
    net = sum(float(d.get("net_kg", d.get("kg", 0))) for d in store.list("deliveries")
              if d.get("farmer_id") == farmer["id"] and (_day(d.get("date")) or dt.date.min) >= since)
    if not ha:
        return {"delivered_kg_year": round(net), "max_kg_year": None, "too_much": False}
    cap = float(ha) * MAX_T_PER_HA_YEAR * 1000
    return {"delivered_kg_year": round(net), "max_kg_year": round(cap), "too_much": net > cap}


def traceability_csv(store: Store, settings: Settings, campaign: str | None = None) -> str:
    """One row per delivery with the farmer's plot behind it (for buyers' due diligence: EUDR, RSPO, ISPO)."""
    farmers = {f["id"]: f for f in store.list("farmers")}
    deliveries = (services.campaign_records(store, settings, services.need_campaign(store, settings, campaign)["id"], "deliveries")
                  if campaign else store.list("deliveries"))
    flags = {fid: plausibility(store, settings, f) for fid, f in farmers.items()}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["delivery_id", "date", "farmer_id", "farmer", "village", "crop", "gross_kg", "deduction_pct", "net_kg",
                "plot_lat", "plot_lng", "plot_ha", "certification", "plot_mapped", "over_plot_yield", "nearest_mill", "road_km"])
    mill_list = store.list("mills")
    for d in sorted(deliveries, key=lambda x: x.get("date") or ""):
        f = farmers.get(d.get("farmer_id"), {})
        fl = flags.get(d.get("farmer_id")) or {}
        w.writerow([d["id"], d.get("date"), d.get("farmer_id"), f.get("name", d.get("farmer_name", "")), f.get("village", ""),
                    d.get("crop"), d.get("kg"), d.get("deduction_pct", 0), d.get("net_kg", d.get("kg")),
                    f.get("plot_lat", ""), f.get("plot_lng", ""), f.get("plot_ha", ""), f.get("certification", ""),
                    "yes" if f.get("plot_lat") is not None and f.get("plot_lng") is not None else "no",
                    "yes" if fl.get("too_much") else "no",
                    *((n["mill_name"], n["road_km"]) if (n := mills.nearest(mill_list, f)) else ("", ""))])
    return out.getvalue()


def traceability_summary(store: Store, settings: Settings, campaign: str | None = None) -> dict:
    camp = services.need_campaign(store, settings, campaign)
    members = [f for f in services.campaign_members(store, settings, camp["id"]) if f.get("type") != "supplier"]
    mapped = [f for f in members if f.get("plot_lat") is not None and f.get("plot_lng") is not None]
    certified = [f for f in members if f.get("certification")]
    too_much = [{"farmer_id": f["id"], "name": f.get("name"), **plausibility(store, settings, f)} for f in members
                if (plausibility(store, settings, f) or {}).get("too_much")]
    return {"campaign_id": camp["id"], "farmers": len(members), "mapped": len(mapped), "certified": len(certified),
            "over_plot_yield": too_much}
