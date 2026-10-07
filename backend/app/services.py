"""Domain operations shared by the HTTP API, the agent tools and the forecast job."""

from __future__ import annotations

import csv
import hashlib
import datetime as dt
import io

from . import forecast as fc
from .config import Settings
from .rules_engine import Limits, LimitsError, normalize_crop, premium_pct
from .store import Store

CALL_STATUSES = ("queued", "on_call", "done", "dropped", "declined")


class ServiceError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------- limits ----------

def get_limits(store: Store, crop: str) -> Limits:
    doc = store.get("limits", normalize_crop(crop))
    if not doc:
        known = ", ".join(sorted(d["id"] for d in store.list("limits"))) or "none"
        raise ServiceError(f"No price limits set for {crop}. Crops with limits: {known}.")
    return Limits.from_doc(doc)


def set_limits(store: Store, crop: str, floor: float, ceiling: float, reference: float,
               first_premium_pct: float = 4.0, step_pct: float = 2.0) -> dict:
    crop = normalize_crop(crop)
    existing = store.get("limits", crop) or {}
    try:
        limits = Limits(crop=crop, floor=floor, ceiling=ceiling, reference=reference,
                        currency=existing.get("currency", "IDR"), unit=existing.get("unit", "kg"),
                        first_premium_pct=first_premium_pct, step_pct=step_pct,
                        increment=float(existing.get("price_increment", 10.0))).validate()
    except LimitsError as e:
        raise ServiceError(str(e)) from e
    store.set("limits", crop, {**limits.to_doc(), "updated_at": now_iso(),
                               "reference_source": existing.get("reference_source", "")})
    return limits.to_doc()


# ---------- forecast ----------

def recompute_forecast(store: Store, settings: Settings) -> list[dict]:
    harvests = store.list("harvests")
    offers = store.list("offers")
    farmers = store.list("farmers")
    rows = fc.compute_forecast(harvests, offers, settings.plan_start, settings.weeks,
                               settings.target_kg_per_week, settings.gap_tolerance)
    for row in rows:
        row["shortlist"] = (fc.shortlist(row["week"], farmers, harvests, offers,
                                         settings.plan_start, settings.weeks)
                            if row["is_gap"] else [])
        row["reasons"] = (fc.gap_reasons(row["week"], harvests, settings.plan_start, settings.weeks)
                          if row["is_gap"] else None)
        row["note"] = gap_note_text(row) if row["is_gap"] else None
        row["updated_at"] = now_iso()
        store.set("forecast", row["id"], row)
    return rows


def gap_note_text(row: dict) -> str:
    """Why a week is short, from the call answers. The API may ask Gemini to polish it."""
    r = row.get("reasons") or {}
    parts = []
    if r.get("moved_out"):
        why = f" after {', '.join(r['moved_reasons'])}" if r.get("moved_reasons") else ""
        parts.append(f"{r['moved_out']} farmers moved delivery to week {row['week'] + 1}{why}")
    if r.get("unsure_in_week"):
        parts.append(f"{r['unsure_in_week']} answers were unsure, so they count for half")
    if not parts:
        return (f"Only {r.get('farmers_in_week', 0)} farmers expect to deliver in week {row['week']}, "
                f"{row['gap_kg'] / 1000:.0f} t below the target.")
    text = ", and ".join(parts)
    return text[0].upper() + text[1:] + "."


def first_gap_week(store: Store) -> dict | None:
    rows = sorted(store.list("forecast"), key=lambda r: r.get("week", 0))
    return next((r for r in rows if r.get("is_gap")), None)


def forecast_csv(store: Store) -> str:
    rows = sorted(store.list("forecast"), key=lambda r: r.get("week", 0))
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["week", "week_start", "expected_kg", "pending_kg", "target_kg", "gap_kg", "is_gap"])
    for r in rows:
        writer.writerow([r["label"], r["week_start"], r["expected_kg"], r["pending_kg"],
                         r["target_kg"], r["gap_kg"], "yes" if r["is_gap"] else "no"])
    return out.getvalue()


def forecast_summary_text(store: Store, settings: Settings) -> str:
    """Plain template summary. The API may ask Gemini to rewrite it."""
    rows = sorted(store.list("forecast"), key=lambda r: r.get("week", 0))
    if not rows:
        return "No forecast yet. Start a call campaign to collect harvest answers."
    gaps = [r for r in rows if r["is_gap"]]
    pending = sum(o["kg"] for o in store.list("offers") if o.get("status") == "pending")
    parts = [f"Expected supply over {len(rows)} weeks totals "
             f"{sum(r['expected_kg'] for r in rows) / 1000:.0f} t against a target of "
             f"{settings.target_kg_per_week / 1000:.0f} t per week."]
    for g in gaps:
        parts.append(f"{g['label']} (from {g['week_start']}) is short by {g['gap_kg'] / 1000:.0f} t; "
                     f"{len(g['shortlist'])} farmers could pull harvest forward.")
    if not gaps:
        parts.append("No week is below the gap threshold.")
    if pending:
        parts.append(f"{pending / 1000:.1f} t of offers wait for approval.")
    return " ".join(parts)


# ---------- harvests ----------

def record_harvest(store: Store, settings: Settings, farmer_id: str, crop: str, kg: float,
                   ready_date: str, call_id: str | None, confidence: str = "firm") -> dict:
    try:
        date = dt.date.fromisoformat(ready_date[:10])
    except (TypeError, ValueError) as e:
        raise ServiceError("ready_date must be a date in YYYY-MM-DD form.") from e
    if not 0 < kg <= 200_000:
        raise ServiceError("kg must be between 1 and 200000.")
    crop = normalize_crop(crop)
    confidence = "unsure" if confidence == "unsure" else "firm"
    harvest_id = f"h-{farmer_id}-{crop}"
    store.set("harvests", harvest_id, {
        "farmer_id": farmer_id, "crop": crop, "kg": round(kg), "ready_date": date.isoformat(),
        "confidence": confidence, "source": "call", "call_id": call_id, "updated_at": now_iso(),
    })
    if call_id:
        store.set("calls", call_id, {"harvest_confidence": confidence}, merge=True)
    recompute_forecast(store, settings)
    week = fc.week_index(date, settings.plan_start, settings.weeks)
    return {"harvest_id": harvest_id, "week": week,
            "week_label": fc.week_label(week) if week else "outside the forecast horizon"}


# ---------- offers ----------

def create_offer(store: Store, settings: Settings, *, farmer: dict, crop: str, kg: float,
                 price: float, deliver_week: int | None, call_id: str | None,
                 status: str = "pending", requested_price: float | None = None,
                 source: str = "call", negotiation: dict | None = None) -> dict:
    crop = normalize_crop(crop)
    limits = get_limits(store, crop)
    if status == "pending" and not limits.within(price):
        raise ServiceError("Price is outside the floor and ceiling.")
    harvest = store.get("harvests", f"h-{farmer['id']}-{crop}")
    from_week = None
    harvest_id = None
    if harvest and farmer.get("type") != "supplier":
        hw = fc.week_index(harvest["ready_date"], settings.plan_start, settings.weeks)
        if hw and deliver_week and hw > deliver_week:
            from_week, harvest_id = hw, harvest["id"]
            kg = min(kg, float(harvest["kg"]))
    doc = {
        "farmer_id": farmer["id"], "farmer_name": farmer.get("name", farmer["id"]),
        "village": farmer.get("village", ""),
        "kind": farmer.get("type", "farmer"), "crop": crop, "kg": round(kg),
        "price_per_kg": round(price, 2), "reference_price": limits.reference,
        "premium_pct": premium_pct(limits, price), "currency": limits.currency,
        "deliver_week": deliver_week, "from_week": from_week, "harvest_id": harvest_id,
        "status": status, "requested_price": requested_price, "call_id": call_id,
        "source": source, "confirmed_by_voice": False, "created_at": now_iso(),
        # How the price was reached, for the approval screen: first offer, counter, ladder step.
        "negotiation": negotiation or {},
    }
    offer_id = store.add("offers", doc)
    recompute_forecast(store, settings)
    return {**doc, "id": offer_id}


def decide_offer(store: Store, settings: Settings, offer_id: str, approve: bool) -> dict:
    offer = store.get("offers", offer_id)
    if not offer:
        raise ServiceError("Offer not found.")
    if offer["status"] not in ("pending", "escalated"):
        raise ServiceError(f"Offer is already {offer['status']}.")
    if approve:
        limits = get_limits(store, offer["crop"])
        if not limits.within(offer["price_per_kg"]):
            raise ServiceError("Price is outside the current floor and ceiling. "
                               "Raise the limits first, or reject the offer.")
    status = "approved" if approve else "rejected"
    store.set("offers", offer_id, {"status": status, "decided_at": now_iso(),
                                   "decided_by": settings.planner_name}, merge=True)
    recompute_forecast(store, settings)
    if approve:
        farmer = store.get("farmers", offer["farmer_id"])
        if farmer:
            queue_call(store, farmer, kind="confirm", offer_id=offer_id)
    return {**offer, "status": status}


def undo_offer(store: Store, settings: Settings, offer_id: str) -> dict:
    """Return a decided offer to waiting, while its confirmation call has not happened yet."""
    offer = store.get("offers", offer_id)
    if not offer:
        raise ServiceError("Offer not found.")
    if offer["status"] not in ("approved", "rejected"):
        raise ServiceError("Only approved or rejected offers can be undone.")
    if offer.get("confirmed_by_voice"):
        raise ServiceError("The farmer already heard the confirmation. Call them before changing it.")
    calls = [c for c in store.list("calls") if c.get("offer_id") == offer_id and c["kind"] == "confirm"]
    if any(c["status"] == "on_call" for c in calls):
        raise ServiceError("The confirmation call is in progress.")
    for c in calls:
        if c["status"] == "queued":
            store.delete("calls", c["id"])
    back = "escalated" if (offer.get("negotiation") or {}).get("escalated") else "pending"
    store.set("offers", offer_id, {"status": back, "decided_at": None, "decided_by": None}, merge=True)
    recompute_forecast(store, settings)
    return {**offer, "status": back}


def offer_from_rival_quote(store: Store, settings: Settings, quote_id: str) -> dict:
    quote = store.get("rival_quotes", quote_id)
    if not quote:
        raise ServiceError("Rival quote not found.")
    if any(o.get("source") == f"rival_quote:{quote_id}" and o["status"] in ("pending", "approved")
           for o in store.list("offers")):
        raise ServiceError("This quote already has an open offer.")
    supplier = store.get("farmers", quote["supplier_id"])
    if not supplier:
        raise ServiceError("Supplier not found.")
    return create_offer(store, settings, farmer=supplier, crop=quote["crop"], kg=quote["kg"],
                        price=quote["price_per_kg"], deliver_week=quote.get("deliver_week"),
                        call_id=None, source=f"rival_quote:{quote_id}",
                        negotiation={"rival_quote": True})


# ---------- calls and campaigns ----------

def queue_call(store: Store, farmer: dict, kind: str, gap_week: int | None = None,
               offer_id: str | None = None, attempt: int = 1) -> str:
    return store.add("calls", {
        "farmer_id": farmer["id"], "farmer_name": farmer.get("name", farmer["id"]),
        "kind": kind, "status": "queued", "attempt": attempt, "gap_week": gap_week,
        "offer_id": offer_id, "created_at": now_iso(), "started_at": None, "ended_at": None,
        "summary": None, "outcome": None, "transcript": None, "consent": None,
    })


def _open_call_for(store: Store, farmer_id: str, kind: str) -> bool:
    return any(c["farmer_id"] == farmer_id and c["kind"] == kind and c["status"] in ("queued", "on_call")
               for c in store.list("calls"))


def start_campaign(store: Store, settings: Settings, kind: str = "collect") -> dict:
    farmers = store.list("farmers")
    queued = 0
    gap = first_gap_week(store)
    if kind == "collect":
        targets = [f for f in farmers if f.get("to_call")]
        gap_week = gap["week"] if gap else None
    elif kind == "gap_fill":
        if not gap:
            raise ServiceError("No week has a gap right now.")
        ids = [s["farmer_id"] for s in gap.get("shortlist", [])]
        ids += [f["id"] for f in farmers if f.get("type") == "supplier"]
        targets = [f for f in farmers if f["id"] in ids]
        gap_week = gap["week"]
    else:
        raise ServiceError("Campaign kind must be collect or gap_fill.")
    for farmer in sorted(targets, key=lambda f: f["id"]):
        if not _open_call_for(store, farmer["id"], kind):
            queue_call(store, farmer, kind, gap_week=gap_week)
            queued += 1
    store.set("campaigns", "current", {"status": "running", "kind": kind, "started_at": now_iso(),
                                       "gap_week": gap_week}, merge=True)
    return {"queued": queued, "kind": kind, "gap_week": gap_week}


def stop_campaign(store: Store) -> dict:
    store.set("campaigns", "current", {"status": "stopped", "stopped_at": now_iso()}, merge=True)
    return {"status": "stopped"}


def call_now(store: Store, farmer_id: str, kind: str | None = None) -> str:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise ServiceError("Farmer not found.")
    gap = first_gap_week(store)
    kind = kind or "collect"
    return queue_call(store, farmer, kind, gap_week=gap["week"] if gap else None)


def finish_call(store: Store, settings: Settings, call_id: str, *, ended_cleanly: bool,
                outcome: str | None, summary: str | None, consent: bool | None,
                transcript: list[dict]) -> None:
    call = store.get("calls", call_id)
    if not call:
        return
    if ended_cleanly:
        status = "declined" if outcome in ("declined", "stopped") else "done"
    else:
        status = "dropped"
    store.set("calls", call_id, {
        "status": status, "outcome": outcome or ("dropped" if not ended_cleanly else "completed"),
        "summary": summary, "consent": bool(consent),
        # Consent notice: the transcript is kept only when the farmer agreed.
        "transcript": transcript if consent else None, "ended_at": now_iso(),
    }, merge=True)
    if status == "done" and call.get("kind") == "confirm" and call.get("offer_id"):
        store.set("offers", call["offer_id"], {"confirmed_by_voice": True}, merge=True)
    if status == "dropped" and call.get("attempt", 1) < settings.max_call_attempts:
        farmer = store.get("farmers", call["farmer_id"])
        if farmer:
            store.set("calls", call_id, {"retry_queued": True}, merge=True)
            queue_call(store, farmer, call["kind"], gap_week=call.get("gap_week"),
                       offer_id=call.get("offer_id"), attempt=call.get("attempt", 1) + 1)


def upload_farmers(store: Store, settings: Settings, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    required = {"name", "phone", "crop", "language"}
    if not reader.fieldnames or not required <= {f.strip().lower() for f in reader.fieldnames}:
        raise ServiceError("CSV needs the columns: name, phone, crop, language (village optional).")
    added = 0
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("name") or not row.get("phone"):
            continue
        fid = row.get("id") or "u" + hashlib.sha1(row["phone"].encode()).hexdigest()[:8]
        store.set("farmers", fid, {
            "name": row["name"], "phone": row["phone"], "crop": normalize_crop(row["crop"]),
            "language": row["language"], "village": row.get("village", ""),
            "type": row.get("type", "farmer") or "farmer",
            "can_pull_forward": row.get("can_pull_forward", "").lower() in ("1", "yes", "true"),
            "to_call": True,
        })
        added += 1
    return {"added": added}
