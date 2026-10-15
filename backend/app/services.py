"""Domain operations shared by the HTTP API, the agent tools and the forecast job."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import hmac
import datetime as dt
import io
import threading

from . import agent_profile
from . import forecast as fc
from .config import Settings, normalize_phone
from .rules_engine import CROP_LABELS, Limits, LimitsError, normalize_crop, premium_pct
from .store import Store

CALL_STATUSES = ("queued", "on_call", "done", "dropped", "declined")


class ServiceError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


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


# ---------- campaigns (one per crop) ----------
# The default crop (DEMO_CROP, palm) keeps the ids it always had: campaign "current" and forecast rows "W1".."W5".
# Every other crop uses its own id: campaign "rubber" and forecast rows "rubber-W1".. (see campaign_id, forecast_row_id).

MAX_WEEKS = 12
MAX_TARGET_KG = 10_000_000


def default_crop(settings: Settings) -> str:
    return normalize_crop(settings.demo_crop)


def campaign_id(settings: Settings, crop: str) -> str:
    return "current" if normalize_crop(crop) == default_crop(settings) else normalize_crop(crop)


def crop_of_campaign_id(settings: Settings, cid: str) -> str:
    return default_crop(settings) if cid == "current" else normalize_crop(cid)


def forecast_row_id(settings: Settings, crop: str, label: str) -> str:
    return label if normalize_crop(crop) == default_crop(settings) else f"{normalize_crop(crop)}-{label}"


def farmer_crop(settings: Settings, doc: dict) -> str:
    return normalize_crop(doc.get("crop") or settings.demo_crop)


def ensure_default_campaign(store: Store, settings: Settings) -> None:
    """Older data has one campaign ("current") with no crop, target or weeks: fill them in, once."""
    doc = store.get("campaigns", "current") or {}
    fill = {k: v for k, v in (("crop", default_crop(settings)),
                              ("target_kg_per_week", settings.target_kg_per_week),
                              ("weeks", settings.weeks)) if doc.get(k) in (None, "")}
    if fill or not doc:
        store.set("campaigns", "current", {"status": "idle", "kind": None, **fill}, merge=True)


def refresh_campaign_status(store: Store, settings: Settings) -> None:
    """A campaign that is "running" with no call of its crop still waiting or on the phone has finished:
    mark it "done" (Start calling is offered again). Confirmation calls belong to approvals, not to the campaign."""
    running = [c for c in store.list("campaigns") if c.get("status") == "running"]
    if not running:
        return
    farmers = {f["id"]: farmer_crop(settings, f) for f in store.list("farmers")}
    open_crops = {farmers.get(c["farmer_id"]) for c in store.list("calls")
                  if c.get("kind") in ("collect", "gap_fill") and c.get("status") in ("queued", "on_call")}
    for camp in running:
        if normalize_crop(camp.get("crop") or settings.demo_crop) not in open_crops:
            store.set("campaigns", camp["id"], {"status": "done", "finished_at": now_iso()}, merge=True)


def list_campaigns(store: Store, settings: Settings) -> list[dict]:
    ensure_default_campaign(store, settings)
    return store.list("campaigns")


def get_campaign(store: Store, settings: Settings, crop: str | None = None) -> dict | None:
    crop = normalize_crop(crop) if crop else default_crop(settings)
    return next((c for c in list_campaigns(store, settings) if normalize_crop(c.get("crop") or "") == crop), None)


def weeks_for(store: Store, settings: Settings, crop: str | None = None) -> int:
    return int((get_campaign(store, settings, crop) or {}).get("weeks") or settings.weeks)


def settings_for_crop(store: Store, settings: Settings, crop: str | None) -> Settings:
    """The settings a call about this crop runs with: that campaign's weeks, weekly target and voice."""
    c = get_campaign(store, settings, crop) or {}
    voice = (c.get("persona") or {}).get("voice") or settings.voice_name
    return dataclasses.replace(settings, weeks=int(c.get("weeks") or settings.weeks),
                               target_kg_per_week=int(c.get("target_kg_per_week") or settings.target_kg_per_week),
                               voice_name=voice if voice in agent_profile.VOICES or voice == settings.voice_name
                               else settings.voice_name)


def set_agent_profile(store: Store, settings: Settings, crop: str | None, persona: dict | None,
                      questions: list | None) -> dict:
    """Save one campaign's persona and extra questions (validated; see agent_profile)."""
    crop = normalize_crop(crop) if crop else default_crop(settings)
    camp = get_campaign(store, settings, crop)
    if not camp:
        raise ServiceError(f"{CROP_LABELS.get(crop, crop)} has no campaign yet. Create one first.")
    try:
        profile = {"persona": agent_profile.normalize_persona(persona),
                   "questions": agent_profile.normalize_questions(questions)}
    except agent_profile.AgentProfileError as e:
        raise ServiceError(str(e)) from e
    store.set("campaigns", camp["id"], {**profile, "agent_updated_at": now_iso()}, merge=True)
    return {**profile, "crop": crop}


def edit_harvest(store: Store, settings: Settings, farmer_id: str, kg: float, ready_date: str, confidence: str,
                 actor=None, every_days: float | None = None) -> dict:
    """A planner corrects (or adds) a farmer's harvest by hand. The first values from the call are kept in
    "original", and the harvest is marked edited, so a hand-made number is never mistaken for the farmer's own."""
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise ServiceError("Farmer not found.")
    crop = farmer_crop(settings, farmer)
    harvest_id = f"h-{farmer_id}-{crop}"
    before = store.get("harvests", harvest_id)
    result = record_harvest(store, settings, farmer_id, crop, float(kg), ready_date,
                            (before or {}).get("call_id"), confidence, every_days if every_days else None)
    if not every_days and before and before.get("every_days"):
        store.set("harvests", harvest_id, {"every_days": None}, merge=True)  # cleared by hand
        recompute_forecast(store, settings)
    original = (before or {}).get("original") or (
        {k: before.get(k) for k in ("kg", "ready_date", "confidence", "source", "every_days")} if before else None)
    store.set("harvests", harvest_id, {"source": "planner" if not before else before.get("source", "call"),
                                       "original": original, "edited_by": actor.name if actor else "Planner",
                                       "edited_at": now_iso()}, merge=True)
    return {**result, "harvest": store.get("harvests", harvest_id)}


def delete_harvest(store: Store, settings: Settings, farmer_id: str) -> dict:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise ServiceError("Farmer not found.")
    harvest_id = f"h-{farmer_id}-{farmer_crop(settings, farmer)}"
    if not store.get("harvests", harvest_id):
        raise ServiceError("This farmer has no harvest on record.")
    store.delete("harvests", harvest_id)
    recompute_forecast(store, settings)
    return {"deleted": harvest_id}


def edit_answer(store: Store, call_id: str, question_id: str, answer: str, actor=None) -> dict:
    """Correct an answer to one of the planner's questions; the agent's version is kept in "original"."""
    call = store.get("calls", call_id)
    if not call:
        raise ServiceError("Call not found.")
    answers = dict(call.get("answers") or {})
    entry = answers.get(question_id)
    if not entry:
        raise ServiceError("This call has no answer to that question.")
    try:
        value = agent_profile.parse_answer({"type": entry.get("type", "text")}, answer)
    except agent_profile.AgentProfileError as e:
        raise ServiceError(str(e)) from e
    answers[question_id] = {**entry, "answer": value, "original": entry.get("original", entry.get("answer")),
                            "edited_by": actor.name if actor else "Planner", "edited_at": now_iso()}
    store.set("calls", call_id, {"answers": answers}, merge=True)
    return answers[question_id]


def set_weekly_schedule(store: Store, settings: Settings, crop: str | None, enabled: bool, channel: str = "browser") -> dict:
    """Mark a campaign to start by itself every Monday morning (run by the weekly job)."""
    crop = normalize_crop(crop) if crop else default_crop(settings)
    camp = get_campaign(store, settings, crop)
    if not camp:
        raise ServiceError(f"{CROP_LABELS.get(crop, crop)} has no campaign yet. Create one first.")
    if channel not in ("browser", "twilio"):
        raise ServiceError("Channel must be browser or twilio.")
    weekly = {"enabled": bool(enabled), "channel": channel, "updated_at": now_iso()}
    store.set("campaigns", camp["id"], {"weekly": weekly}, merge=True)
    return {**weekly, "crop": crop}


def roll_weeks(store: Store, settings: Settings, today: dt.date | None = None) -> Settings:
    """Settings whose week 1 is next week. Same object when nothing changed (or PLAN_START pins the weeks)."""
    from .config import next_monday

    if not settings.plan_start_auto:
        return settings
    start = next_monday(today)
    if start == settings.plan_start:
        return settings
    rolled = dataclasses.replace(settings, plan_start=start)
    recompute_forecast(store, rolled)
    return rolled


def weekly_job(store: Store, settings: Settings) -> dict:
    """Monday morning: snapshot what farmers promised for the week that starts now (so deliveries can be checked
    against it later), then start every campaign marked "call every Monday" that is not already calling."""
    from . import track_record

    from . import messaging

    week = settings.plan_start - dt.timedelta(days=7)  # the week that starts today; week 1 is next week
    snap = track_record.snapshot_promises(store, settings, week)
    messaging.check_gap_alerts(store, settings)
    waiting = [o for o in store.list("offers") if o.get("status") in ("pending", "escalated")]
    if waiting:
        messaging.alert_planner(store, settings, f"{settings.mill_name}: {len(waiting)} offers wait for your approval.",
                                "offers_digest")
    started, skipped = [], []
    for camp in list_campaigns(store, settings):
        weekly = camp.get("weekly") or {}
        crop = normalize_crop(camp.get("crop") or settings.demo_crop)
        if not weekly.get("enabled"):
            continue
        if camp.get("status") == "running":
            skipped.append({"crop": crop, "why": "already calling"})
            continue
        try:
            r = start_campaign(store, settings, "collect", crop, weekly.get("channel", "browser"))
            started.append({"crop": crop, "queued": r["queued"], "channel": r["channel"]})
        except ServiceError as e:
            skipped.append({"crop": crop, "why": str(e)})
    store.set("campaigns", campaign_id(settings, default_crop(settings)), {"last_weekly_job": now_iso()}, merge=True)
    return {"plan_start": settings.plan_start.isoformat(), "promises": snap, "started": started, "skipped": skipped}


def confirm_read_back(store: Store, settings: Settings, call_id: str, user: str | None = None) -> dict:
    """Save a harvest the agent read back but did not save (the call dropped, or it forgot the second
    record_harvest). A planner does this from the call recap, after checking the transcript."""
    call = store.get("calls", call_id)
    if not call:
        raise ServiceError("Call not found.")
    rb = call.get("harvest_read_back")
    if not rb:
        raise ServiceError("This call has no unsaved harvest.")
    result = record_harvest(store, settings, call["farmer_id"], rb["crop"], float(rb["kg"]), rb["ready_date"],
                            call_id, rb.get("confidence", "firm"))
    store.set("harvests", result["harvest_id"], {"source": "planner", "confirmed_by": user,
                                                 "edited_by": user or "Planner", "edited_at": now_iso()}, merge=True)
    store.set("calls", call_id, {"harvest_read_back": None}, merge=True)
    return result


def answers_csv(store: Store, settings: Settings) -> str:
    """Every saved answer to the planners' extra questions, one row per answer."""
    farmers = {f["id"]: f for f in store.list("farmers")}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["call_id", "date", "farmer", "village", "crop", "question", "answer"])
    for c in sorted(store.list("calls"), key=lambda c: c.get("started_at") or c.get("created_at") or ""):
        for a in (c.get("answers") or {}).values():
            f = farmers.get(c["farmer_id"], {})
            w.writerow([c["id"], (c.get("started_at") or "")[:10], c.get("farmer_name", ""), f.get("village", ""),
                        farmer_crop(settings, f) if f else "", a.get("question", ""), a.get("answer", "")])
    return out.getvalue()


def create_campaign(store: Store, settings: Settings, crop: str, target_kg_per_week: float, weeks: int) -> dict:
    if not settings.multi_crop:
        raise ServiceError("Running more than one crop at a time is turned off (MULTI_CROP).")
    key = normalize_crop(crop)
    if key not in CROP_LABELS:
        raise ServiceError(f"Unknown crop {crop!r}. Use one of: {', '.join(CROP_LABELS)}.")
    if get_campaign(store, settings, key):
        raise ServiceError(f"{CROP_LABELS[key]} already has a campaign.", status=409)
    if not 0 < target_kg_per_week <= MAX_TARGET_KG:
        raise ServiceError(f"The weekly target must be between 1 and {MAX_TARGET_KG:,} kg.")
    if not 1 <= weeks <= MAX_WEEKS:
        raise ServiceError(f"Weeks to plan must be between 1 and {MAX_WEEKS}.")
    cid = campaign_id(settings, key)
    doc = {"crop": key, "kind": None, "status": "idle", "target_kg_per_week": round(target_kg_per_week),
           "weeks": int(weeks), "created_at": now_iso()}
    store.set("campaigns", cid, doc)
    recompute_forecast(store, settings)
    return {"id": cid, **doc}


# ---------- forecast ----------

def recompute_forecast(store: Store, settings: Settings) -> list[dict]:
    """One set of weekly rows per campaign, each from that crop's harvests and offers only."""
    refresh_campaign_status(store, settings)  # also heals a campaign left "running" after its last call
    all_harvests = store.list("harvests")
    all_offers = store.list("offers")
    farmers = store.list("farmers")
    rows: list[dict] = []
    keep: set[str] = set()
    for camp in list_campaigns(store, settings):
        crop = normalize_crop(camp.get("crop") or settings.demo_crop)
        weeks = int(camp.get("weeks") or settings.weeks)
        target = int(camp.get("target_kg_per_week") or settings.target_kg_per_week)
        harvests = [h for h in all_harvests if farmer_crop(settings, h) == crop]
        offers = [o for o in all_offers if farmer_crop(settings, o) == crop]
        crop_farmers = [f for f in farmers if farmer_crop(settings, f) == crop]
        for row in fc.compute_forecast(harvests, offers, settings.plan_start, weeks, target, settings.gap_tolerance):
            row["crop"] = crop
            row["shortlist"] = (fc.shortlist(row["week"], crop_farmers, harvests, offers,
                                             settings.plan_start, weeks) if row["is_gap"] else [])
            row["reasons"] = (fc.gap_reasons(row["week"], harvests, settings.plan_start, weeks)
                              if row["is_gap"] else None)
            row["note"] = gap_note_text(row) if row["is_gap"] else None
            row["updated_at"] = now_iso()
            row["id"] = forecast_row_id(settings, crop, row["label"])
            store.set("forecast", row["id"], row)
            keep.add(row["id"])
            rows.append(row)
    for old in store.list("forecast"):  # weeks cut from a shorter plan, or rows of a removed campaign
        if old["id"] not in keep:
            store.delete("forecast", old["id"])
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


def first_gap_week(store: Store, crop: str | None = None) -> dict | None:
    """The earliest short week; for one crop when given (rows from before crops existed count as the default crop)."""
    rows = sorted(store.list("forecast"), key=lambda r: r.get("week", 0))
    if crop:
        rows = [r for r in rows if normalize_crop(r.get("crop") or crop) == normalize_crop(crop)]
    return next((r for r in rows if r.get("is_gap")), None)


def _forecast_rows(store: Store, crop: str | None) -> list[dict]:
    rows = sorted(store.list("forecast"), key=lambda r: (r.get("crop") or "", r.get("week", 0)))
    return [r for r in rows if not crop or normalize_crop(r.get("crop") or crop) == normalize_crop(crop)]


def forecast_csv(store: Store, crop: str | None = None) -> str:
    rows = _forecast_rows(store, crop)
    out = io.StringIO()
    writer = csv.writer(out)
    with_crop = len({r.get("crop") for r in rows}) > 1  # a crop column only when the rows mix crops
    writer.writerow(["week", "week_start", "expected_kg", "pending_kg", "target_kg", "gap_kg", "is_gap"]
                    + (["crop"] if with_crop else []))
    for r in rows:
        writer.writerow([r["label"], r["week_start"], r["expected_kg"], r["pending_kg"],
                         r["target_kg"], r["gap_kg"], "yes" if r["is_gap"] else "no"]
                        + ([r.get("crop", "")] if with_crop else []))
    return out.getvalue()


def forecast_summary_text(store: Store, settings: Settings, crop: str | None = None) -> str:
    """Plain template summary. The API may ask Gemini to rewrite it."""
    rows = _forecast_rows(store, crop)
    if not rows:
        return "No forecast yet. Start a call campaign to collect harvest answers."
    gaps = [r for r in rows if r["is_gap"]]
    pending = sum(o["kg"] for o in store.list("offers") if o.get("status") == "pending"
                  and (not crop or normalize_crop(o.get("crop") or crop) == normalize_crop(crop)))
    parts = [f"Expected supply over {len(rows)} weeks totals "
             f"{sum(r['expected_kg'] for r in rows) / 1000:.0f} t against a target of "
             f"{rows[0]['target_kg'] / 1000:.0f} t per week."]
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
                   ready_date: str, call_id: str | None, confidence: str = "firm",
                   every_days: float | None = None) -> dict:
    try:
        date = dt.date.fromisoformat(ready_date[:10])
    except (TypeError, ValueError) as e:
        raise ServiceError("ready_date must be a date in YYYY-MM-DD form.") from e
    if not 0 < kg <= 200_000:
        raise ServiceError("kg must be between 1 and 200000.")
    crop = normalize_crop(crop)
    confidence = "unsure" if confidence == "unsure" else "firm"
    harvest_id = f"h-{farmer_id}-{crop}"
    if every_days in (None, ""):
        # A farmer's harvest cycle rarely changes: keep the one on record when this answer did not give one.
        every_days = (store.get("harvests", harvest_id) or {}).get("every_days")
    elif not fc.MIN_EVERY_DAYS <= float(every_days) <= fc.MAX_EVERY_DAYS:
        raise ServiceError(f"A harvest cycle must be {fc.MIN_EVERY_DAYS} to {fc.MAX_EVERY_DAYS} days.")
    store.set("harvests", harvest_id, {
        "farmer_id": farmer_id, "crop": crop, "kg": round(kg), "ready_date": date.isoformat(),
        "confidence": confidence, "source": "call", "call_id": call_id, "updated_at": now_iso(),
        "every_days": int(every_days) if every_days else None,
    })
    if call_id:
        store.set("calls", call_id, {"harvest_confidence": confidence}, merge=True)
    recompute_forecast(store, settings)
    if call_id:
        from . import messaging

        messaging.check_gap_alerts(store, settings)
    week = fc.week_index(date, settings.plan_start, weeks_for(store, settings, crop))
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
        hw = fc.week_index(harvest["ready_date"], settings.plan_start, weeks_for(store, settings, crop))
        if hw and deliver_week and hw > deliver_week:
            from_week, harvest_id = hw, harvest["id"]
            kg = min(kg, float(harvest["kg"]))
    plan_start = settings_for_crop(store, settings, crop).plan_start
    doc = {
        "farmer_id": farmer["id"], "farmer_name": farmer.get("name", farmer["id"]),
        "village": farmer.get("village", ""),
        # The calendar weeks, so the offer stays right when the planning weeks roll forward.
        "deliver_week_start": fc.week_start(deliver_week, plan_start).isoformat() if deliver_week else None,
        "from_week_start": fc.week_start(from_week, plan_start).isoformat() if from_week else None,
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
    if status in ("pending", "escalated"):
        from . import messaging

        word = "above the ceiling, needs you" if status == "escalated" else "waiting for approval"
        messaging.alert_planner(store, settings, f"{settings.mill_name}: new offer {word}: {doc['farmer_name']}, "
                                f"{round(doc['kg']):,} kg at {doc['price_per_kg']:,.0f} {doc['currency']}/kg.",
                                "offer_waiting", offer_id=offer_id)
    return {**doc, "id": offer_id}


def decide_offer(store: Store, settings: Settings, offer_id: str, approve: bool, actor=None) -> dict:
    offer = store.get("offers", offer_id)
    if not offer:
        raise ServiceError("Offer not found.")
    if offer["status"] not in ("pending", "escalated"):
        raise ServiceError(f"Offer is already {offer['status']}.")
    changes = {}
    if approve:
        # An escalated offer is approved at the price the farmer asked for, not the ceiling
        # the agent quoted, so the limits must cover that request.
        escalated = offer["status"] == "escalated" and offer.get("requested_price") is not None
        price = offer["requested_price"] if escalated else offer["price_per_kg"]
        limits = get_limits(store, offer["crop"])
        if not limits.within(price):
            raise ServiceError("Price is outside the current floor and ceiling. "
                               "Raise the limits first, or reject the offer.")
        if escalated:
            changes = {"price_per_kg": price, "quoted_price": offer["price_per_kg"]}
    status = "approved" if approve else "rejected"
    store.set("offers", offer_id, {**changes, "status": status, "decided_at": now_iso(),
                                   "decided_by": actor.name if actor else "Planner",
                                   "decided_by_id": actor.id if actor else None}, merge=True)
    recompute_forecast(store, settings)
    if approve:
        farmer = store.get("farmers", offer["farmer_id"])
        if farmer:
            queue_call(store, farmer, kind="confirm", offer_id=offer_id)
    return {**offer, **changes, "status": status}


def approval_impact(store: Store, settings: Settings, crop: str | None = None) -> dict:
    """For each waiting offer of a crop: the weeks as they would be if the planner approved it (alone), what it
    costs, and whether it opens a new gap somewhere else. Also the same for approving all of them together."""
    crop = normalize_crop(crop) if crop else default_crop(settings)
    camp = get_campaign(store, settings, crop) or {}
    weeks = int(camp.get("weeks") or settings.weeks)
    target = int(camp.get("target_kg_per_week") or settings.target_kg_per_week)
    harvests = [h for h in store.list("harvests") if farmer_crop(settings, h) == crop]
    offers = [o for o in store.list("offers") if farmer_crop(settings, o) == crop]

    def rows(approve_ids: set[str]) -> list[dict]:
        trial = [{**o, "status": "approved"} if o["id"] in approve_ids else o for o in offers]
        return fc.compute_forecast(harvests, trial, settings.plan_start, weeks, target, settings.gap_tolerance)

    def compare(after: list[dict]) -> dict:
        changes = [{"label": a["label"], "before_kg": b["expected_kg"], "after_kg": a["expected_kg"],
                    "was_gap": b["is_gap"], "is_gap": a["is_gap"]}
                   for b, a in zip(now, after) if a["expected_kg"] != b["expected_kg"]]
        return {"weeks": changes,
                "closes_gaps": [c["label"] for c in changes if c["was_gap"] and not c["is_gap"]],
                "new_gaps": [c["label"] for c in changes if not c["was_gap"] and c["is_gap"]]}

    now = rows(set())
    rival = min((q["price_per_kg"] for q in store.list("rival_quotes") if normalize_crop(q.get("crop") or crop) == crop),
                default=None)
    waiting = [o for o in offers if o.get("status") in ("pending", "escalated")]
    per_offer = {}
    for o in waiting:
        price = o["requested_price"] if o.get("status") == "escalated" and o.get("requested_price") else o["price_per_kg"]
        ref = o.get("reference_price") or price
        per_offer[o["id"]] = {
            **compare(rows({o["id"]})),
            "cost": round(price * o["kg"]),
            "premium": round((price - ref) * o["kg"]),
            "price_per_kg": price,
            "vs_rival_per_kg": round(price - rival, 2) if rival is not None and o.get("kind") != "supplier" else None,
            "currency": o.get("currency", "IDR"),
        }
    together = compare(rows({o["id"] for o in waiting if o.get("status") == "pending"}))
    approved = [o for o in offers if o.get("status") == "approved"]
    return {"crop": crop, "offers": per_offer, "all_pending": together,
            "approved_cost": round(sum(o["price_per_kg"] * o["kg"] for o in approved)),
            "approved_premium": round(sum((o["price_per_kg"] - (o.get("reference_price") or o["price_per_kg"])) * o["kg"]
                                          for o in approved))}


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
    changes = {"status": back, "decided_at": None, "decided_by": None, "decided_by_id": None}
    if back == "escalated" and offer.get("quoted_price") is not None:
        changes.update(price_per_kg=offer["quoted_price"], quoted_price=None)
    store.set("offers", offer_id, changes, merge=True)
    recompute_forecast(store, settings)
    return {**offer, **changes}


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
               offer_id: str | None = None, attempt: int = 1, channel: str = "browser") -> str:
    # "channel" names what carries the call's audio: "browser" (the only one built) today,
    # "twilio" once a real-phone adapter exists. See live_session.Channel for the seam.
    return store.add("calls", {
        "farmer_id": farmer["id"], "farmer_name": farmer.get("name", farmer["id"]),
        "kind": kind, "status": "queued", "attempt": attempt, "gap_week": gap_week,
        "offer_id": offer_id, "channel": channel, "created_at": now_iso(), "started_at": None,
        "ended_at": None, "summary": None, "outcome": None, "transcript": None, "consent": None,
    })


def _open_call_for(store: Store, farmer_id: str, kind: str) -> bool:
    return any(c["farmer_id"] == farmer_id and c["kind"] == kind and c["status"] in ("queued", "on_call")
               for c in store.list("calls"))


def start_campaign(store: Store, settings: Settings, kind: str = "collect", crop: str | None = None,
                   channel: str = "browser") -> dict:
    """Queue the calls of one crop's campaign (the default crop when none is named).

    channel "browser": the calls wait in the call client (the demo). channel "twilio": real phone
    calls, dialled one at a time by dial_next (each finished call starts the next)."""
    if channel not in ("browser", "twilio"):
        raise ServiceError("Channel must be browser or twilio.")
    if channel == "twilio" and not phone_calls_ready(settings):
        raise ServiceError(phone_calls_note(settings))
    crop = normalize_crop(crop) if crop else default_crop(settings)
    camp = get_campaign(store, settings, crop)
    if not camp:
        raise ServiceError(f"{CROP_LABELS.get(crop, crop)} has no campaign yet. Create one first.")
    label = CROP_LABELS.get(crop, crop)
    farmers = [f for f in store.list("farmers") if farmer_crop(settings, f) == crop]
    recompute_forecast(store, settings)  # rows written before crops existed pick up their crop now
    gap = first_gap_week(store, crop)
    if kind == "collect":
        targets = [f for f in farmers if f.get("to_call")]
        gap_week = gap["week"] if gap else None
    elif kind == "gap_fill":
        if not gap:
            raise ServiceError(f"No {label} week has a gap right now.")
        get_limits(store, crop)  # the agent reads the reference price: stop here, not in the middle of a call
        ids = [s["farmer_id"] for s in gap.get("shortlist", [])]
        ids += [f["id"] for f in farmers if f.get("type") == "supplier"]
        targets = [f for f in farmers if f["id"] in ids]
        gap_week = gap["week"]
    else:
        raise ServiceError("Campaign kind must be collect or gap_fill.")
    targets = [f for f in targets if not f.get("do_not_call")]
    if not targets:
        raise ServiceError(f"No {label} farmers are ready to call. Add or mark farmers on the Setup page.")
    queued = 0
    for farmer in sorted(targets, key=lambda f: f["id"]):
        if not _open_call_for(store, farmer["id"], kind):
            queue_call(store, farmer, kind, gap_week=gap_week, channel=channel)
            queued += 1
    store.set("campaigns", campaign_id(settings, crop), {"status": "running", "kind": kind, "started_at": now_iso(),
                                                         "gap_week": gap_week, "crop": crop,
                                                         "channel": channel}, merge=True)
    dialled = dial_next(store, settings) if channel == "twilio" else None
    return {"queued": queued, "kind": kind, "gap_week": gap_week, "crop": crop, "channel": channel,
            "dialled": dialled}


def stop_campaign(store: Store, settings: Settings, crop: str | None = None) -> dict:
    crop = normalize_crop(crop) if crop else default_crop(settings)
    if not get_campaign(store, settings, crop):
        raise ServiceError(f"{CROP_LABELS.get(crop, crop)} has no campaign.")
    store.set("campaigns", campaign_id(settings, crop), {"status": "stopped", "stopped_at": now_iso()}, merge=True)
    return {"status": "stopped", "crop": crop}


def call_now(store: Store, farmer_id: str, kind: str | None = None, settings: Settings | None = None) -> str:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise ServiceError("Farmer not found.")
    if farmer.get("do_not_call"):
        raise ServiceError("This farmer asked not to be called again.")
    gap = first_gap_week(store, normalize_crop(farmer.get("crop") or (settings.demo_crop if settings else "palm")))
    kind = kind or "collect"
    return queue_call(store, farmer, kind, gap_week=gap["week"] if gap else None)


def twilio_ready(settings: Settings) -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token
               and settings.twilio_from_number and settings.public_base_url)


def phone_calls_ready(settings: Settings) -> bool:
    """True when the dashboard may offer "Call by phone": Twilio configured and the safety gate open."""
    return twilio_ready(settings) and settings.real_calls_enabled


def phone_calls_note(settings: Settings) -> str:
    """Why real phone calls are on or off, in words for the dashboard."""
    if not twilio_ready(settings):
        missing = [name for name, value in (("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                                            ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                                            ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
                                            ("PUBLIC_BASE_URL", settings.public_base_url)) if not value]
        return "Real phone calls are off: Twilio is not set up (missing " + ", ".join(missing) + ")."
    if not settings.real_calls_enabled:
        return "Real phone calls are off: REAL_CALLS_ENABLED is not true."
    if "*" in settings.real_call_allowlist:
        return "Real phone calls are on, to any number."
    n = len(settings.real_call_allowlist)
    return (f"Real phone calls are on, only to the {n} number{'s' if n != 1 else ''} on the allowlist."
            if n else "Real phone calls are on, but the allowlist is empty, so every number is refused.")


def stream_token(settings: Settings, call_id: str) -> str:
    """Per-call secret for the Twilio media stream.

    Twilio signs the /twilio/voice webhook but not the WebSocket it then opens, so the
    TwiML hands the stream this token as a custom parameter and TwilioChannel checks it
    in the "start" frame. Keyed on the auth token, which only Twilio and we know.
    """
    key = (settings.twilio_auth_token or "").encode()
    return hmac.new(key, call_id.encode(), hashlib.sha256).hexdigest()[:32]


# Twilio CallStatus values that mean nobody was ever connected to the agent.
TWILIO_NOT_REACHED = {"no-answer": "no_answer", "busy": "busy", "failed": "failed", "canceled": "canceled"}


def twilio_status(store: Store, settings: Settings, call_id: str, call_status: str) -> str | None:
    """Twilio's status callback for a dialled call.

    Without it a call that is never answered stays "queued" for ever: the voice webhook and
    the media stream only happen when someone picks up. A call still queued when Twilio
    reports it over has not reached the agent, so it ends as dropped (and is retried once,
    like a browser call). A call that reached the agent is finished by run_call; ignore it.
    """
    call = store.get("calls", call_id)
    if not call or call.get("channel") != "twilio":
        return None
    store.set("calls", call_id, {"twilio_status": call_status}, merge=True)
    if call.get("status") != "queued":
        return None
    if call_status in TWILIO_NOT_REACHED:
        outcome = TWILIO_NOT_REACHED[call_status]
    elif call_status == "completed":
        outcome = "not_connected"  # answered, but the audio stream never reached the agent
    else:
        return None  # queued, ringing, in-progress: not over yet
    finish_call(store, settings, call_id, ended_cleanly=False, outcome=outcome, summary=None,
                consent=None, transcript=[])
    return outcome


def _dialable_number(settings: Settings, farmer: dict) -> str:
    """The farmer's number in E.164, after the safety gate. Raises ServiceError with the reason."""
    if not twilio_ready(settings):
        raise ServiceError("Twilio is not configured (need TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, "
                           "TWILIO_FROM_NUMBER and PUBLIC_BASE_URL).")
    if not settings.real_calls_enabled:
        raise ServiceError("Real calls are turned off. Set REAL_CALLS_ENABLED=true to place one.")
    if farmer.get("do_not_call"):
        raise ServiceError("This farmer asked not to be called again.")
    phone = (farmer.get("phone") or "").strip()
    if not phone:
        raise ServiceError("This farmer has no phone number on record.")
    # Stored/displayed as "+62 810 0000 1000" (seed_data._phone, and whatever a planner
    # types into the upload CSV) - Twilio's Calls API wants strict E.164, no separators.
    to_number = normalize_phone(phone)
    if "*" not in settings.real_call_allowlist and to_number not in settings.real_call_allowlist:
        raise ServiceError(f"{to_number} is not on the real-call allowlist (REAL_CALL_ALLOWLIST). "
                           "This is a safety gate, not a bug - add the number there, or set it to "
                           "\"*\" to allow any number (production).")
    return to_number


def _place_twilio_call(store: Store, settings: Settings, call_id: str, to_number: str) -> None:
    """Ask Twilio to ring the farmer for an already queued phone call."""
    from twilio.rest import Client  # imported lazily: only needed once Twilio is actually configured

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    base = settings.public_base_url.rstrip("/")
    try:
        placed = client.calls.create(
            to=to_number, from_=settings.twilio_from_number, method="POST",
            url=f"{base}/twilio/voice?call_id={call_id}",
            # So an unanswered, busy or failed call ends instead of staying queued.
            status_callback=f"{base}/twilio/status?call_id={call_id}",
            status_callback_method="POST", status_callback_event=["completed"],
            # Ring for 30 s, not Twilio's 60: long enough for a farmer to reach the phone,
            # short enough that a voicemail greeting rarely picks up first.
            timeout=30)
    except Exception as e:
        raise ServiceError(f"Twilio call failed: {e}") from e
    store.set("calls", call_id, {"twilio_sid": getattr(placed, "sid", None), "dialed_at": now_iso()},
              merge=True)


def dial_now(store: Store, settings: Settings, farmer_id: str, kind: str | None = None) -> str:
    """Place a real outbound call (VA-8). Same preconditions as call_now, plus Twilio config
    and the REAL_CALLS_ENABLED/REAL_CALL_ALLOWLIST safety gate - see config.py."""
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        if not twilio_ready(settings):
            _dialable_number(settings, {})  # report the configuration problem first
        raise ServiceError("Farmer not found.")
    to_number = _dialable_number(settings, farmer)
    if any(c["farmer_id"] == farmer_id and c.get("channel") == "twilio" and c["status"] == "on_call"
           for c in store.list("calls")):
        raise ServiceError("This farmer is on a phone call right now.")
    # A dropped phone call is retried as a queued phone call; nothing dials it on its own
    # (calling a farmer back the moment they missed a call would be rude), so dialling the
    # farmer again picks that retry up instead of starting a new attempt count.
    waiting = sorted((c for c in store.list("calls")
                      if c["farmer_id"] == farmer_id and c.get("channel") == "twilio"
                      and c["status"] == "queued" and (not kind or c["kind"] == kind)),
                     key=lambda c: c.get("created_at") or "")
    if waiting:
        call_id, created = waiting[0]["id"], False
    else:
        gap = first_gap_week(store, farmer_crop(settings, farmer))
        call_id = queue_call(store, farmer, kind or "collect", gap_week=gap["week"] if gap else None,
                             channel="twilio")
        created = True
    try:
        _place_twilio_call(store, settings, call_id, to_number)
    except ServiceError:
        if created:
            store.delete("calls", call_id)
        raise
    return call_id


_dial_lock = threading.Lock()


def dial_next(store: Store, settings: Settings) -> str | None:
    """Phone campaigns ring one farmer at a time: the Live API allows only a few sessions at once,
    and a planner can follow one call. Dial the oldest waiting first-attempt phone call of a running
    phone campaign, unless a phone call is already ringing or in progress. A farmer the safety gate
    refuses is skipped (the call ends as dropped with the reason, no retry) and the next one is tried.
    Retries of missed calls are left for the planner to dial (see dial_now)."""
    with _dial_lock:
        calls = store.list("calls")
        if any(c.get("channel") == "twilio" and (c["status"] == "on_call"
                                                 or (c["status"] == "queued" and c.get("dialed_at")))
               for c in calls):
            return None
        phone_crops = {normalize_crop(c.get("crop") or settings.demo_crop) for c in store.list("campaigns")
                       if c.get("status") == "running" and c.get("channel") == "twilio"}
        if not phone_crops:
            return None
        farmers = {f["id"]: f for f in store.list("farmers")}
        waiting = sorted((c for c in calls
                          if c.get("channel") == "twilio" and c["status"] == "queued" and not c.get("dialed_at")
                          and (c.get("attempt") or 1) == 1 and c.get("kind") in ("collect", "gap_fill")
                          and farmer_crop(settings, farmers.get(c["farmer_id"], {})) in phone_crops),
                         key=lambda c: (c.get("created_at") or "", c["farmer_id"], c["id"]))
        for call in waiting:
            farmer = farmers.get(call["farmer_id"])
            try:
                if not farmer:
                    raise ServiceError("Farmer not found.")
                _place_twilio_call(store, settings, call["id"], _dialable_number(settings, farmer))
                return call["id"]
            except ServiceError as e:
                store.set("calls", call["id"], {"status": "dropped", "outcome": "skipped", "summary": f"Not dialled: {e}",
                                                "ended_at": now_iso()}, merge=True)
        refresh_campaign_status(store, settings)
        return None


def _after_phone_call(store: Store, settings: Settings) -> None:
    """Start the next call of a phone campaign without holding up the caller (a Twilio request
    takes up to a few seconds, and finish_call runs inside the voice gateway's event loop)."""
    threading.Thread(target=dial_next, args=(store, settings), daemon=True).start()


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
    if (status == "done" and outcome == "completed" and call.get("kind") == "confirm"
            and call.get("offer_id")):
        store.set("offers", call["offer_id"], {"confirmed_by_voice": True}, merge=True)
        from . import messaging

        offer = store.get("offers", call["offer_id"])
        if offer:
            messaging.send_deal_confirmation(store, settings, offer)
    if outcome == "stopped":
        # The farmer explicitly asked not to be called again; honour it for every future campaign.
        store.set("farmers", call["farmer_id"], {"do_not_call": True}, merge=True)
    if status == "dropped" and call.get("attempt", 1) < settings.max_call_attempts:
        farmer = store.get("farmers", call["farmer_id"])
        if farmer:
            store.set("calls", call_id, {"retry_queued": True}, merge=True)
            queue_call(store, farmer, call["kind"], gap_week=call.get("gap_week"),
                       offer_id=call.get("offer_id"), attempt=call.get("attempt", 1) + 1,
                       channel=call.get("channel", "browser"))
    refresh_campaign_status(store, settings)  # after any retry was queued: the last call ending ends the campaign
    if call.get("channel") == "twilio" and call.get("kind") in ("collect", "gap_fill"):
        _after_phone_call(store, settings)


# The languages a farmer can be called in. The agent speaks whatever the name says, so a typo here
# would make it speak the wrong thing; the dialog on the Setup page offers exactly this list.
LANGUAGES = ("Bahasa Indonesia", "Bahasa Malaysia", "English", "Javanese", "Sundanese", "Thai", "Vietnamese", "Filipino")
LANGUAGE_ALIASES = {"indonesian": "Bahasa Indonesia", "indonesia": "Bahasa Indonesia",
                    "bahasa": "Bahasa Indonesia", "malay": "Bahasa Malaysia",
                    "malaysian": "Bahasa Malaysia", "bahasa melayu": "Bahasa Malaysia",
                    "jawa": "Javanese", "bahasa jawa": "Javanese", "sunda": "Sundanese",
                    "bahasa sunda": "Sundanese", "thai": "Thai", "vietnamese": "Vietnamese",
                    "tiếng việt": "Vietnamese", "tagalog": "Filipino", "filipino": "Filipino", "pilipino": "Filipino"}


def normalize_language(raw: str) -> str:
    key = " ".join(raw.strip().lower().split())
    for name in LANGUAGES:
        if key == name.lower():
            return name
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    raise ServiceError(f"Unknown language {raw!r}. Use one of: {', '.join(LANGUAGES)}.")


def _farmer_fields(row: dict) -> tuple[str, dict]:
    """Validate one farmer row. Returns (phone digits, the fields to store)."""
    row = {k.strip().lower(): str(v if v is not None else "").strip() for k, v in row.items() if k}
    missing = [c for c in ("name", "phone", "crop", "language") if not row.get(c)]
    if missing:
        raise ServiceError(f"Missing: {', '.join(missing)}.")
    digits = normalize_phone(row["phone"])[1:]
    if not 7 <= len(digits) <= 15:
        raise ServiceError(f"The phone number {row['phone']!r} does not look right.")
    crop = normalize_crop(row["crop"])
    if crop not in CROP_LABELS:
        raise ServiceError(f"Unknown crop {row['crop']!r}. Use one of: {', '.join(CROP_LABELS)}.")
    language = normalize_language(row["language"])
    try:
        usual = max(0, int(float(row.get("usual_kg_week") or 0)))
    except ValueError:
        raise ServiceError("usual_kg_week must be a number.") from None
    return digits, {
        "name": row["name"], "phone": row["phone"], "crop": crop,
        "language": language, "village": row.get("village", ""), "usual_kg_week": usual,
        "can_pull_forward": row.get("can_pull_forward", "").lower() in ("1", "yes", "true"),
    }


def add_farmer(store: Store, row: dict) -> str:
    """Save one farmer. The id comes from the phone number, so the same phone again updates that
    farmer instead of adding a duplicate."""
    digits, fields = _farmer_fields(row)
    fid = str(row.get("id") or "").strip() or "u" + hashlib.sha1(digits.encode()).hexdigest()[:8]
    clean = {k.strip().lower(): v for k, v in row.items() if k}
    store.set("farmers", fid, {**fields, "type": str(clean.get("type") or "farmer").strip() or "farmer",
                               "to_call": True})
    return fid


def update_farmer(store: Store, farmer_id: str, row: dict) -> dict:
    """Edit a farmer's details. Keeps the id and the call flags (to_call, do_not_call)."""
    if not store.get("farmers", farmer_id):
        raise ServiceError("Farmer not found.")
    _, fields = _farmer_fields(row)
    store.set("farmers", farmer_id, fields, merge=True)
    return store.get("farmers", farmer_id)


def delete_farmer(store: Store, farmer_id: str) -> dict:
    """Remove a farmer and withdraw their waiting calls. Past calls, offers and harvests stay,
    so the forecast and the audit trail do not change."""
    if not store.get("farmers", farmer_id):
        raise ServiceError("Farmer not found.")
    for c in store.list("calls"):
        if c["farmer_id"] == farmer_id and c["status"] == "on_call":
            raise ServiceError("This farmer is on a call right now. Try again when it ends.")
    withdrawn = 0
    for c in store.list("calls"):
        if c["farmer_id"] == farmer_id and c["status"] == "queued":
            store.delete("calls", c["id"])
            withdrawn += 1
    store.delete("farmers", farmer_id)
    return {"deleted": farmer_id, "calls_withdrawn": withdrawn}


def upload_farmers(store: Store, settings: Settings, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    required = {"name", "phone", "crop", "language"}
    if not reader.fieldnames or not required <= {f.strip().lower() for f in reader.fieldnames}:
        raise ServiceError("CSV needs the columns: name, phone, crop, language "
                           "(optional: village, usual_kg_week, can_pull_forward).")
    added, skipped = 0, []
    for number, row in enumerate(reader, start=2):  # line 1 is the header
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        try:
            add_farmer(store, row)
            added += 1
        except ServiceError as e:
            skipped.append(f"Line {number}: {e}")
    return {"added": added, "skipped": skipped}
