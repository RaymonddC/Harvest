"""The mills (collection "mills") and how far each farmer's plot is from the nearest one.

A mill is a name and a location (lat, lng). For a farmer with a mapped plot the nearest mill is the one with the
shortest straight line; the road distance and the truck time are estimates from it:
  road_km   straight line x ROAD_FACTOR (rural roads wind; 1.3 is a common rule of thumb)
  minutes   road_km at TRUCK_KMH (a loaded truck on plantation and village roads)
Fresh fruit bunches lose oil quality when they wait (free fatty acids rise), so the time to the mill matters: a plot
more than FAR_MINUTES away is flagged. The same sums run in the dashboard (frontend/src/mills.js); keep them in step.
Used by: the farmer's card and the plot map (dashboard), the purchase order ("Deliver to"), the confirmation call
(the agent says where to bring the fruit), the traceability CSV and the BigQuery farmers table.
"""

from __future__ import annotations

import math

from .store import Store

ROAD_FACTOR = 1.3
TRUCK_KMH = 30
FAR_MINUTES = 120


class MillError(ValueError):
    pass


def km_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest(mills: list[dict], farmer: dict) -> dict | None:
    """The nearest mill to the farmer's plot, with the distance and the estimated truck time; None without a plot or mills."""
    if farmer.get("plot_lat") is None or farmer.get("plot_lng") is None:
        return None
    lat, lng = float(farmer["plot_lat"]), float(farmer["plot_lng"])
    best = None
    for m in mills:
        if m.get("lat") is None or m.get("lng") is None:
            continue
        km = km_between(lat, lng, float(m["lat"]), float(m["lng"]))
        if best is None or km < best[0]:
            best = (km, m)
    if best is None:
        return None
    km, m = best
    road = km * ROAD_FACTOR
    minutes = round(road / TRUCK_KMH * 60)
    return {"mill_id": m["id"], "mill_name": m.get("name", m["id"]), "km": round(km, 1), "road_km": round(road, 1),
            "minutes": minutes, "far": minutes > FAR_MINUTES}


def nearest_for(store: Store, farmer: dict | None) -> dict | None:
    return nearest(store.list("mills"), farmer or {})


def travel_text(n: dict | None) -> str:
    """'Mill name, about 14 km by road, about 30 min' (for documents and the agent)."""
    if not n:
        return ""
    m = n["minutes"]
    t = f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"
    return f"{n['mill_name']}, about {n['road_km']:g} km by road, about {t} by truck"


def _check(name: str, lat, lng) -> dict:
    name = " ".join((name or "").split())[:80]
    if not name:
        raise MillError("Give the mill a name.")
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError) as e:
        raise MillError("Latitude and longitude must be numbers.") from e
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise MillError("Latitude is -90 to 90 and longitude -180 to 180.")
    return {"name": name, "lat": round(lat, 6), "lng": round(lng, 6)}


def add(store: Store, name: str, lat, lng) -> dict:
    doc = _check(name, lat, lng)
    mid = store.add("mills", doc)
    return {**doc, "id": mid}


def update(store: Store, mill_id: str, name: str, lat, lng) -> dict:
    if not store.get("mills", mill_id):
        raise MillError("Mill not found.")
    store.set("mills", mill_id, _check(name, lat, lng), merge=True)
    return {**store.get("mills", mill_id), "id": mill_id}


def delete(store: Store, mill_id: str) -> dict:
    if not store.get("mills", mill_id):
        raise MillError("Mill not found.")
    store.delete("mills", mill_id)
    return {"deleted": mill_id}


def catchment(store: Store, farmer_ids: set[str] | None = None) -> list[dict]:
    """Per mill: how many farmers are nearest to it, their usual tonnes a week, the average and longest truck time,
    and how many are far. Farmers without a plot are left out."""
    mills = store.list("mills")
    out = {m["id"]: {"mill_id": m["id"], "name": m.get("name"), "farmers": 0, "usual_kg_week": 0.0,
                     "minutes_sum": 0, "max_minutes": 0, "far": 0} for m in mills}
    for f in store.list("farmers"):
        if farmer_ids is not None and f["id"] not in farmer_ids:
            continue
        n = nearest(mills, f)
        if not n:
            continue
        c = out[n["mill_id"]]
        c["farmers"] += 1
        c["usual_kg_week"] += float(f.get("usual_kg_week") or 0)
        c["minutes_sum"] += n["minutes"]
        c["max_minutes"] = max(c["max_minutes"], n["minutes"])
        c["far"] += int(n["far"])
    rows = []
    for c in out.values():
        c["avg_minutes"] = round(c.pop("minutes_sum") / c["farmers"]) if c["farmers"] else None
        rows.append(c)
    return rows
