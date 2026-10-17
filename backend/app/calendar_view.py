"""What happens on which day, for the calendar page.

Events between two dates, for one campaign or all of them:
  week      a planning week of a campaign (amber when short of the target)
  campaign_start, campaign_end  the first and last day of a campaign
  call      a call made (or waiting in the queue: "planned")
  call_plan the weekly calls a campaign makes by itself on Mondays at 06:00
  harvest   a farmer's next harvest, and the later rounds projected from how often they harvest
  deal      an offer's delivery week (approved, or waiting for approval)
  delivery  a delivery recorded at the weighbridge
"""

from __future__ import annotations

import datetime as dt

from . import forecast as fc
from . import services
from .config import Settings
from .store import Store

MAX_DAYS = 120


class CalendarError(services.ServiceError):
    pass


def _day(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def events(store: Store, settings: Settings, start: dt.date, end: dt.date, campaign: str | None = None,
           today: dt.date | None = None) -> dict:
    if end < start:
        raise CalendarError("The end date is before the start date.")
    if (end - start).days > MAX_DAYS:
        raise CalendarError(f"Ask for at most {MAX_DAYS} days at a time.")
    today = today or dt.date.today()
    camps = services.list_campaigns(store, settings)
    if campaign:
        camp = services.need_campaign(store, settings, campaign)
        campaign = camp["id"]
    farmers = {f["id"]: f for f in store.list("farmers")}
    names = {c["id"]: c.get("name") or services.CROP_LABELS.get(services.campaign_crop(settings, c), c["id"])
             for c in camps}

    def mine(doc: dict) -> str | None:
        cid = services.doc_campaign(settings, doc, farmers, camps)
        return cid if not campaign or cid == campaign else False

    def name_of(doc: dict) -> str:
        return doc.get("farmer_name") or farmers.get(doc.get("farmer_id"), {}).get("name") or doc.get("farmer_id", "")

    out: list[dict] = []
    for r in store.list("forecast"):
        ws = _day(r.get("week_start"))
        cid = r.get("campaign_id")
        if not ws or (campaign and not services._row_matches(r, campaign)):
            continue
        if ws <= end and ws + dt.timedelta(days=6) >= start:
            out.append({"type": "week", "date": ws.isoformat(), "end": (ws + dt.timedelta(days=6)).isoformat(),
                        "label": r.get("label"), "campaign_id": cid, "is_gap": bool(r.get("is_gap")),
                        "gap_kg": r.get("gap_kg", 0), "expected_kg": r.get("expected_kg", 0),
                        "target_kg": r.get("target_kg", 0)})

    for camp in camps:
        if campaign and camp["id"] != campaign:
            continue
        first, last = services.campaign_dates(settings, camp)
        for d, kind in ((first, "campaign_start"), (last, "campaign_end")):
            if start <= d <= end:
                out.append({"type": kind, "date": d.isoformat(), "campaign_id": camp["id"]})

    for c in store.list("calls"):
        cid = mine(c)
        if cid is False:
            continue
        d = _day(c.get("started_at") or c.get("created_at"))
        if d and start <= d <= end:
            out.append({"type": "call", "date": d.isoformat(), "time": str(c.get("started_at") or "")[11:16] or None,
                        "id": c["id"], "kind": c.get("kind"), "status": c.get("status"), "outcome": c.get("outcome"),
                        "channel": c.get("channel"), "farmer_id": c.get("farmer_id"), "farmer_name": name_of(c),
                        "campaign_id": cid, "planned": c.get("status") == "queued"})

    for camp in camps:
        if campaign and camp["id"] != campaign or not (camp.get("weekly") or {}).get("enabled"):
            continue
        d = max(start, today)
        d += dt.timedelta(days=(7 - d.weekday()) % 7)
        while d <= end:
            out.append({"type": "call_plan", "date": d.isoformat(), "time": "06:00", "campaign_id": camp["id"],
                        "channel": (camp.get("weekly") or {}).get("channel", "browser")})
            d += dt.timedelta(days=7)

    for h in store.list("harvests"):
        cid = mine(h)
        if cid is False or cid is None:
            continue
        for d, projected in fc.harvest_rounds(h, end):
            if start <= d <= end:
                out.append({"type": "harvest", "date": d.isoformat(), "farmer_id": h.get("farmer_id"),
                            "farmer_name": name_of(h), "kg": h.get("kg", 0), "projected": projected,
                            "confidence": h.get("confidence"), "campaign_id": cid})

    for o in store.list("offers"):
        if o.get("status") not in ("approved", "pending", "escalated"):
            continue
        cid = mine(o)
        if cid is False:
            continue
        d = _day(o.get("deliver_week_start"))
        if not d and o.get("deliver_week"):
            d = fc.week_start(int(o["deliver_week"]), settings.plan_start)
        if d and start <= d <= end:
            out.append({"type": "deal", "date": d.isoformat(), "id": o["id"], "status": o["status"],
                        "farmer_id": o.get("farmer_id"), "farmer_name": name_of(o), "kg": o.get("kg", 0),
                        "price_per_kg": o.get("price_per_kg"), "currency": o.get("currency", "IDR"),
                        "confirmed_by_voice": bool(o.get("confirmed_by_voice")), "campaign_id": cid})

    for dl in store.list("deliveries"):
        cid = mine(dl)
        if cid is False:
            continue
        d = _day(dl.get("date"))
        if d and start <= d <= end:
            out.append({"type": "delivery", "date": d.isoformat(), "id": dl["id"], "farmer_id": dl.get("farmer_id"),
                        "farmer_name": name_of(dl), "kg": dl.get("kg", 0), "campaign_id": cid})

    order = {"week": 0, "campaign_start": 1, "campaign_end": 1, "call_plan": 2, "call": 3, "harvest": 4, "deal": 5,
             "delivery": 6}
    out.sort(key=lambda e: (e["date"], order[e["type"]], e.get("time") or "", e.get("farmer_name") or ""))
    return {"start": start.isoformat(), "end": end.isoformat(), "campaign_id": campaign, "campaigns": names,
            "events": out}
