"""The mills (collection "mills") and how far each farmer's plot is from the nearest one.

A mill is a name and a location (lat, lng). For each farmer with a mapped plot:
  by road   Google's Routes API (route matrix, driving, no traffic) gives the road distance and driving time from the
            plot to every mill; the nearest mill is the one with the shortest drive, and the truck time is the
            driving time x TRUCK_FACTOR (a loaded truck is slower than a car). Saved on the farmer as `mill_route`
            with a signature of the plot and the mills, so it is fetched again only when one of them moves.
            Cloud Run calls the API with its own service account (no key); MILL_ROUTES=false turns it off.
  estimate  until then (or without the API): the nearest mill by straight line, road_km = straight line x
            ROAD_FACTOR (rural roads wind) and the truck time at TRUCK_KMH.
Fresh fruit bunches lose oil quality when they wait (free fatty acids rise), so the time to the mill matters: a plot
more than FAR_MINUTES away is flagged. The same sums run in the dashboard (frontend/src/mills.js); keep them in step.
Used by: the farmer's card and the plot map (dashboard), the purchase order ("Deliver to"), the confirmation call
(the agent says where to bring the fruit), the traceability CSV and the BigQuery farmers table.
"""

from __future__ import annotations

import logging
import math

from .store import Store

log = logging.getLogger(__name__)

ROAD_FACTOR = 1.3
TRUCK_KMH = 30
TRUCK_FACTOR = 1.3  # a loaded truck on village roads against Google's car driving time
FAR_MINUTES = 120
MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MAX_ELEMENTS = 600  # the route matrix takes at most 625 origin x destination pairs a request


class MillError(ValueError):
    pass


def km_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def signature(farmer: dict, mills: list[dict]) -> str:
    """The plot and the mills a saved road route was fetched for (the dashboard builds the same string, mills.js)."""
    ms = sorted((m for m in mills if m.get("lat") is not None and m.get("lng") is not None), key=lambda m: m["id"])
    return f"{float(farmer['plot_lat']):.5f},{float(farmer['plot_lng']):.5f}|" + ";".join(
        f"{m['id']}:{float(m['lat']):.5f},{float(m['lng']):.5f}" for m in ms)


def nearest(mills: list[dict], farmer: dict) -> dict | None:
    """The nearest mill to the farmer's plot, with the road distance and the truck time: from Google's road route when
    one is saved for this plot and these mills, else estimated. None without a plot or mills."""
    if farmer.get("plot_lat") is None or farmer.get("plot_lng") is None:
        return None
    lat, lng = float(farmer["plot_lat"]), float(farmer["plot_lng"])
    route = farmer.get("mill_route") or {}
    mill = next((m for m in mills if m["id"] == route.get("mill_id")), None)
    if mill and route.get("minutes") is not None and route.get("sig") == signature(farmer, mills):
        return {"mill_id": mill["id"], "mill_name": mill.get("name", mill["id"]),
                "km": round(km_between(lat, lng, float(mill["lat"]), float(mill["lng"])), 1),
                "road_km": route["road_km"], "minutes": route["minutes"], "far": route["minutes"] > FAR_MINUTES,
                "source": "road"}
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
            "minutes": minutes, "far": minutes > FAR_MINUTES, "source": "estimate"}


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


# ---------- road routes from Google (Routes API, route matrix) ----------

def _google_post(settings):
    """POST to the Routes API as this service (Cloud Run's service account, or local Application Default Credentials)."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)
    quota = settings.gcp_project or project

    def post(body: dict) -> list[dict]:
        r = session.post(MATRIX_URL, json=body, timeout=60, headers={
            "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,condition",
            **({"X-Goog-User-Project": quota} if quota else {})})
        if r.status_code >= 400:
            raise MillError(f"Routes API {r.status_code}: {r.text[:300]}")
        return r.json()
    return post


def _point(lat, lng) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": float(lat), "longitude": float(lng)}}}}


def refresh_routes(store: Store, settings, post=None) -> dict:
    """Fetch the road route from every mapped plot whose saved route is out of date (new plot, a mill added or moved)
    to every mill, and save the shortest drive on the farmer. Returns how many were updated and how many had no road."""
    mills = [m for m in store.list("mills") if m.get("lat") is not None and m.get("lng") is not None]
    if not mills:
        return {"updated": 0, "stale": 0, "note": "No mills yet."}
    stale = [f for f in store.list("farmers") if f.get("plot_lat") is not None and f.get("plot_lng") is not None
             and (f.get("mill_route") or {}).get("sig") != signature(f, mills)]
    if not stale:
        return {"updated": 0, "stale": 0}
    post = post or _google_post(settings)
    per = max(1, MAX_ELEMENTS // len(mills))
    updated = no_road = 0
    for start in range(0, len(stale), per):
        chunk = stale[start:start + per]
        rows = post({"origins": [_point(f["plot_lat"], f["plot_lng"]) for f in chunk],
                     "destinations": [_point(m["lat"], m["lng"]) for m in mills],
                     "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"})
        best: dict[int, tuple[float, float, int]] = {}
        for e in rows or []:
            if e.get("condition") != "ROUTE_EXISTS" or "duration" not in e:
                continue
            secs = float(str(e["duration"]).rstrip("s") or 0)
            o, d = e.get("originIndex", 0), e.get("destinationIndex", 0)
            if o not in best or secs < best[o][0]:
                best[o] = (secs, float(e.get("distanceMeters") or 0), d)
        for i, f in enumerate(chunk):
            sig = signature(f, mills)
            if i in best:
                secs, meters, d = best[i]
                route = {"mill_id": mills[d]["id"], "road_km": round(meters / 1000, 1),
                         "drive_minutes": round(secs / 60), "minutes": round(secs / 60 * TRUCK_FACTOR), "sig": sig}
            else:  # no road found: keep the estimate, and do not ask again until something moves
                route = {"mill_id": None, "minutes": None, "sig": sig}
                no_road += 1
            store.set("farmers", f["id"], {"mill_route": route}, merge=True)
            updated += 1
    return {"updated": updated, "no_road": no_road, "stale": len(stale)}


def refresh_in_background(store: Store, settings) -> None:
    """After a mill is added, moved or removed: fetch the new road routes without making the planner wait."""
    if not getattr(settings, "mill_routes", False):
        return
    import threading

    def run():
        try:
            log.info("mill routes: %s", refresh_routes(store, settings))
        except Exception:  # noqa: BLE001 - the estimate stays until the next try
            log.warning("mill routes: the Routes API call failed", exc_info=True)
    threading.Thread(target=run, daemon=True).start()
