"""Domain operations shared by the HTTP API, the agent tools and the forecast job."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import math
import hmac
import datetime as dt
import io
import logging
import threading

from . import agent_profile
from . import forecast as fc
from .config import Settings, normalize_phone, today_local
from .rules_engine import CROP_LABELS, MAX_OFFER_KG, Limits, LimitsError, normalize_crop, premium_pct
from .store import Store

log = logging.getLogger(__name__)

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


# ---------- campaigns ----------
# A campaign has a crop, a weekly target, weeks to plan and its own farmers (farmer.campaign_id; a farmer is in at
# most one campaign). A crop can have several campaigns (for example one per area).
# The first campaign of each crop keeps the ids it always had: "current" for the default crop (DEMO_CROP, palm),
# the crop name for the others ("rubber"); later ones get "<crop>-<random>". Forecast rows are "W1".. for "current"
# and "<campaign id>-W1".. for the others (see campaign_id, forecast_row_id).
# Farmers saved before campaigns had their own lists have no campaign_id at all: they belong to their crop's first
# campaign. campaign_id None means "in the farmer database, in no campaign".

MAX_WEEKS = 12
MAX_TARGET_KG = 10_000_000


def default_crop(settings: Settings) -> str:
    return normalize_crop(settings.demo_crop)


def campaign_id(settings: Settings, crop: str) -> str:
    return "current" if normalize_crop(crop) == default_crop(settings) else normalize_crop(crop)


def crop_of_campaign_id(settings: Settings, cid: str) -> str:
    return default_crop(settings) if cid == "current" else normalize_crop(cid)


def forecast_row_id(settings: Settings, cid: str, label: str) -> str:
    return label if cid == "current" else f"{cid}-{label}"


def campaign_crop(settings: Settings, camp: dict) -> str:
    return normalize_crop(camp.get("crop") or settings.demo_crop)


def first_campaign_of_crop(settings: Settings, crop: str, camps: list[dict]) -> str | None:
    """Where farmers and records from before campaign lists go: the crop's original campaign, else its oldest one."""
    crop = normalize_crop(crop)
    legacy = campaign_id(settings, crop)
    mine = [c for c in camps if campaign_crop(settings, c) == crop]
    if any(c["id"] == legacy for c in mine):
        return legacy
    mine.sort(key=lambda c: c.get("created_at") or "")
    return mine[0]["id"] if mine else None


def farmer_campaign(settings: Settings, farmer: dict, camps: list[dict]) -> str | None:
    if "campaign_id" in farmer:
        return farmer["campaign_id"] or None
    return first_campaign_of_crop(settings, farmer_crop(settings, farmer), camps)


def doc_campaign(settings: Settings, doc: dict, farmers: dict[str, dict], camps: list[dict]) -> str | None:
    """The campaign of a harvest, offer, call, promise or delivery: its own campaign_id, else its farmer's."""
    if doc.get("campaign_id"):
        return doc["campaign_id"]
    f = farmers.get(doc.get("farmer_id"))
    if f is not None:
        return farmer_campaign(settings, f, camps)
    return first_campaign_of_crop(settings, farmer_crop(settings, doc), camps)


def resolve_campaign(store: Store, settings: Settings, ref: str | None = None) -> dict | None:
    """A campaign by id, or a crop's first campaign by crop name (older callers), or the default campaign."""
    camps = list_campaigns(store, settings)
    if ref:
        hit = next((c for c in camps if c["id"] == ref), None)
        if hit:
            return hit
        try:
            crop = normalize_crop(ref)
        except Exception:  # noqa: BLE001 - not a crop name either
            return None
        cid = first_campaign_of_crop(settings, crop, camps)
        return next((c for c in camps if c["id"] == cid), None)
    return next((c for c in camps if c["id"] == "current"), None) or (camps[0] if camps else None)


def need_campaign(store: Store, settings: Settings, ref: str | None) -> dict:
    camp = resolve_campaign(store, settings, ref)
    if not camp:
        raise ServiceError("Campaign not found. Create one first.", status=404)
    return camp


def campaign_members(store: Store, settings: Settings, cid: str, farmers: list[dict] | None = None,
                     camps: list[dict] | None = None) -> list[dict]:
    camps = camps if camps is not None else list_campaigns(store, settings)
    farmers = farmers if farmers is not None else store.list("farmers")
    return [f for f in farmers if farmer_campaign(settings, f, camps) == cid]


def campaign_records(store: Store, settings: Settings, cid: str, collection: str) -> list[dict]:
    camps = list_campaigns(store, settings)
    farmers = {f["id"]: f for f in store.list("farmers")}
    return [d for d in store.list(collection) if doc_campaign(settings, d, farmers, camps) == cid]


def farmer_crop(settings: Settings, doc: dict) -> str:
    return normalize_crop(doc.get("crop") or settings.demo_crop)


def ensure_default_campaign(store: Store, settings: Settings) -> None:
    """Older data has one campaign ("current") with no crop, target or weeks: fill them in, once. With no campaign
    at all (a fresh store), make that one. A deleted "current" is not brought back while other campaigns exist."""
    doc = store.get("campaigns", "current")
    if doc is None:
        if not store.list("campaigns"):
            store.set("campaigns", "current", {"status": "idle", "kind": None, "crop": default_crop(settings),
                                               "target_kg_per_week": settings.target_kg_per_week,
                                               "weeks": settings.weeks})
        return
    fill = {k: v for k, v in (("crop", default_crop(settings)),
                              ("target_kg_per_week", settings.target_kg_per_week),
                              ("weeks", settings.weeks)) if doc.get(k) in (None, "")}
    if fill:
        store.set("campaigns", "current", fill, merge=True)


STALE_QUEUED_HOURS = 12  # a browser call nobody answered in this long is dropped


def _parse_time(iso: str | None) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None
    return t if t is None or t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def purge_expired_transcripts(store: Store, settings: Settings) -> int:
    """Delete the written transcript of every call whose retention period (the number of days the farmer was told) is over."""
    now = dt.datetime.now(dt.timezone.utc)
    gone = 0
    for c in store.list("calls"):
        expires = _parse_time(c.get("transcript_expires_at"))
        if c.get("transcript") and expires and expires < now:
            store.set("calls", c["id"], {"transcript": None, "transcript_expired_at": now_iso()}, merge=True)
            gone += 1
    return gone


def delete_transcript(store: Store, call_id: str, actor=None) -> dict:
    """Delete one call's written transcript now (a farmer withdrew consent or asked for it to be erased)."""
    call = store.get("calls", call_id)
    if not call or not call.get("transcript"):
        raise ServiceError("There is no transcript of this call.", status=404)
    store.set("calls", call_id, {"transcript": None, "transcript_expires_at": None,
                                 "transcript_deleted": {"by": getattr(actor, "name", None) or getattr(actor, "id", None),
                                                        "at": now_iso()}}, merge=True)
    return {"ok": True}


def reap_stale_calls(store: Store, settings: Settings) -> int:
    """Close browser calls that a restart or a lost connection left "on_call" or "queued" for good: they would keep
    a campaign "running" for ever and block the farmer from being called again. Phone calls are handled by Twilio's status callback."""
    now = dt.datetime.now(dt.timezone.utc)
    gone = 0
    for c in store.list("calls"):
        if c.get("channel", "browser") != "browser" or c.get("status") not in ("on_call", "queued"):
            continue
        if c["status"] == "on_call":
            since, limit = _parse_time(c.get("started_at")), dt.timedelta(seconds=settings.max_call_seconds + 180)
        else:
            since, limit = _parse_time(c.get("created_at")), dt.timedelta(hours=STALE_QUEUED_HOURS)
        if since is None or now - since <= limit:
            continue
        store.set("calls", c["id"], {"status": "dropped", "outcome": "dropped", "ended_at": now_iso(),
                                     "summary": c.get("summary") or "The call ended without a result (the connection was lost or nobody answered).",
                                     "reaped": True}, merge=True)
        gone += 1
    return gone


def refresh_campaign_status(store: Store, settings: Settings) -> None:
    """A campaign that is "running" with no call of its crop still waiting or on the phone has finished:
    mark it "done" (Start calling is offered again). Confirmation calls belong to approvals, not to the campaign."""
    reap_stale_calls(store, settings)
    camps = store.list("campaigns")
    running = [c for c in camps if c.get("status") == "running"]
    if not running:
        return
    farmers = {f["id"]: f for f in store.list("farmers")}
    open_camps = {doc_campaign(settings, c, farmers, camps) for c in store.list("calls")
                  if c.get("kind") in ("collect", "gap_fill") and c.get("status") in ("queued", "on_call")}
    for camp in running:
        if camp["id"] not in open_camps:
            store.set("campaigns", camp["id"], {"status": "done", "finished_at": now_iso()}, merge=True)


def list_campaigns(store: Store, settings: Settings) -> list[dict]:
    ensure_default_campaign(store, settings)
    return store.list("campaigns")


def get_campaign(store: Store, settings: Settings, crop: str | None = None) -> dict | None:
    """A campaign by id, or a crop's first campaign (see resolve_campaign)."""
    if not crop:
        return resolve_campaign(store, settings, None)
    return resolve_campaign(store, settings, crop)


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def campaign_weeks(settings: Settings, camp: dict) -> int:
    """How many weeks the forecast shows for a campaign: from week 1 (next week) to its end date, at most MAX_WEEKS.
    A campaign without dates (older data) keeps its number of weeks."""
    end = _date(camp.get("end_date"))
    if end:
        return max(1, min(MAX_WEEKS, ((end - settings.plan_start).days // 7) + 1))
    return int(camp.get("weeks") or settings.weeks)


def campaign_dates(settings: Settings, camp: dict) -> tuple[dt.date, dt.date]:
    """The campaign's first and last day (from the weeks for older campaigns without dates)."""
    start = _date(camp.get("start_date")) or settings.plan_start
    end = _date(camp.get("end_date")) or settings.plan_start + dt.timedelta(days=7 * campaign_weeks(settings, camp) - 1)
    return start, end


def _before_start(settings: Settings, camp: dict, rows: list[dict]) -> list[dict]:
    """Weeks that end before the campaign starts are shown but never count as short."""
    start = _date(camp.get("start_date"))
    for r in rows:
        ws = _date(r.get("week_start"))
        r["before_start"] = bool(start and ws and ws + dt.timedelta(days=6) < start)
        if r["before_start"]:
            r["is_gap"], r["gap_kg"] = False, 0
    return rows


def weeks_for(store: Store, settings: Settings, crop: str | None = None) -> int:
    return campaign_weeks(settings, get_campaign(store, settings, crop) or {})


def campaign_of_farmer(store: Store, settings: Settings, farmer: dict) -> dict | None:
    """The farmer's campaign; for one in no campaign, their crop's first campaign (its weeks and voice still apply)."""
    camps = list_campaigns(store, settings)
    cid = farmer_campaign(settings, farmer, camps) or first_campaign_of_crop(settings, farmer_crop(settings, farmer), camps)
    return next((c for c in camps if c["id"] == cid), None)


def settings_for_farmer(store: Store, settings: Settings, farmer: dict) -> Settings:
    return settings_for_campaign(settings, campaign_of_farmer(store, settings, farmer) or {})


def settings_for_crop(store: Store, settings: Settings, crop: str | None) -> Settings:
    """The settings a call about this crop (or campaign id) runs with: that campaign's weeks, weekly target and voice."""
    return settings_for_campaign(settings, get_campaign(store, settings, crop) or {})


def settings_for_campaign(settings: Settings, c: dict) -> Settings:
    voice = (c.get("persona") or {}).get("voice") or settings.voice_name
    return dataclasses.replace(settings, weeks=campaign_weeks(settings, c),
                               target_kg_per_week=int(c.get("target_kg_per_week") or settings.target_kg_per_week),
                               voice_name=voice if voice in agent_profile.VOICES or voice == settings.voice_name
                               else settings.voice_name)


def set_agent_profile(store: Store, settings: Settings, crop: str | None, persona: dict | None,
                      questions: list | None) -> dict:
    """Save one campaign's persona and extra questions (validated; see agent_profile)."""
    camp = need_campaign(store, settings, crop)
    crop = campaign_crop(settings, camp)
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


# Automatic calls: each campaign can start itself on chosen weekdays at a chosen hour, in the mill's time zone
# (Asia/Jakarta, UTC+7, no daylight saving). Cloud Scheduler calls the job every hour; see scheduled_calls.
SCHEDULE_TZ = dt.timezone(dt.timedelta(hours=7), "WIB")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _check_schedule(days, time) -> tuple[list[int], str]:
    days = sorted({int(d) for d in (days if days is not None else [0])})
    if not days or any(not 0 <= d <= 6 for d in days):
        raise ServiceError("Pick at least one day (Monday to Sunday).")
    time = (time or "06:00").strip()
    try:
        hour, minute = (int(x) for x in time.split(":"))
    except ValueError:
        raise ServiceError("The time must look like 06:00.") from None
    if not 0 <= hour <= 23 or minute != 0:
        raise ServiceError("Pick a time on the hour (the job runs once an hour).")
    return days, f"{hour:02d}:00"


def schedule_text(weekly: dict) -> str:
    days = weekly.get("days") or [0]
    names = ("every day" if len(days) == 7 else "Monday to Friday" if days == [0, 1, 2, 3, 4]
             else "Monday to Saturday" if days == [0, 1, 2, 3, 4, 5] else ", ".join(DAY_NAMES[d] for d in days))
    return f"{names} at {weekly.get('time') or '06:00'}"


def set_weekly_schedule(store: Store, settings: Settings, crop: str | None, enabled: bool, channel: str = "browser",
                        days: list[int] | None = None, time: str | None = None) -> dict:
    """Let a campaign start its calls by itself on the chosen days at the chosen hour (run by the hourly job)."""
    camp = need_campaign(store, settings, crop)
    crop = campaign_crop(settings, camp)
    if channel not in ("browser", "twilio"):
        raise ServiceError("Channel must be browser or twilio.")
    old = camp.get("weekly") or {}
    days, time = _check_schedule(days if days is not None else old.get("days"), time or old.get("time"))
    weekly = {"enabled": bool(enabled), "channel": channel, "days": days, "time": time, "updated_at": now_iso()}
    store.set("campaigns", camp["id"], {"weekly": weekly}, merge=True)
    return {**weekly, "crop": crop, "campaign_id": camp["id"]}


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


def weekly_bookkeeping(store: Store, settings: Settings) -> dict:
    """Once a week: snapshot what farmers promised for the week that starts now (so deliveries can be checked
    against it later), alert new gaps, and send the waiting-offers digest."""
    from . import messaging, track_record

    week = settings.plan_start - dt.timedelta(days=7)  # the week that starts today; week 1 is next week
    snap = track_record.snapshot_promises(store, settings, week)
    purge_expired_transcripts(store, settings)
    messaging.check_gap_alerts(store, settings)
    waiting = [o for o in store.list("offers") if o.get("status") in ("pending", "escalated")]
    if waiting:
        messaging.alert_planner(store, settings, f"{settings.mill_name}: {len(waiting)} offers wait for your approval.",
                                "offers_digest")
    return {"plan_start": settings.plan_start.isoformat(), "promises": snap}


def _start_scheduled(store: Store, settings: Settings, camp: dict) -> dict:
    weekly = camp.get("weekly") or {}
    crop = campaign_crop(settings, camp)
    if camp.get("status") == "running":
        return {"crop": crop, "campaign_id": camp["id"], "why": "already calling", "skipped": True}
    try:
        r = start_campaign(store, settings, "collect", camp["id"], weekly.get("channel", "browser"))
        return {"crop": crop, "campaign_id": camp["id"], "queued": r["queued"], "channel": r["channel"]}
    except ServiceError as e:
        return {"crop": crop, "campaign_id": camp["id"], "why": str(e), "skipped": True}


def scheduled_calls(store: Store, settings: Settings, now: dt.datetime | None = None) -> dict:
    """The hourly job: the weekly bookkeeping once a week (from Monday 06:00), then start each campaign whose
    automatic calls are due this hour. Each slot runs once, even if the job is called twice in the hour."""
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(SCHEDULE_TZ)
    camps = list_campaigns(store, settings)
    out: dict = {"now": local.isoformat(timespec="minutes"), "started": [], "skipped": []}
    week = (local.date() - dt.timedelta(days=local.weekday())).isoformat()
    marker = next((c for c in camps if c["id"] == "current"), camps[0] if camps else None)
    if marker is not None and (local.weekday() > 0 or local.hour >= 6) and marker.get("bookkeeping_week") != week:
        out["bookkeeping"] = weekly_bookkeeping(store, settings)
        store.set("campaigns", marker["id"], {"bookkeeping_week": week}, merge=True)
    slot = local.strftime("%Y-%m-%dT%H")
    for camp in camps:
        weekly = camp.get("weekly") or {}
        if not weekly.get("enabled") or camp.get("last_scheduled_slot") == slot:
            continue
        if local.weekday() not in (weekly.get("days") or [0]) or local.hour != int((weekly.get("time") or "06:00")[:2]):
            continue
        store.set("campaigns", camp["id"], {"last_scheduled_slot": slot, "last_weekly_job": now_iso()}, merge=True)
        r = _start_scheduled(store, settings, camp)
        out["skipped" if r.pop("skipped", False) else "started"].append(r)
    return out


def weekly_job(store: Store, settings: Settings) -> dict:
    """Run everything now, whatever the day: the weekly bookkeeping, then start every campaign with automatic calls
    switched on (for a manual run; the scheduler calls scheduled_calls every hour)."""
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
        crop = campaign_crop(settings, camp)
        if not weekly.get("enabled"):
            continue
        if camp.get("status") == "running":
            skipped.append({"crop": crop, "campaign_id": camp["id"], "why": "already calling"})
            continue
        try:
            r = start_campaign(store, settings, "collect", camp["id"], weekly.get("channel", "browser"))
            started.append({"crop": crop, "campaign_id": camp["id"], "queued": r["queued"], "channel": r["channel"]})
        except ServiceError as e:
            skipped.append({"crop": crop, "campaign_id": camp["id"], "why": str(e)})
    for camp in list_campaigns(store, settings):
        store.set("campaigns", camp["id"], {"last_weekly_job": now_iso()}, merge=True)
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


MAX_NAME = 60


def _check_campaign_fields(target_kg_per_week: float | None, weeks: int | None, name: str | None) -> None:
    if target_kg_per_week is not None and not 0 < target_kg_per_week <= MAX_TARGET_KG:
        raise ServiceError(f"The weekly target must be between 1 and {MAX_TARGET_KG:,} kg.")
    if weeks is not None and not 1 <= weeks <= MAX_WEEKS:
        raise ServiceError(f"Weeks to plan must be between 1 and {MAX_WEEKS}.")
    if name is not None and len(name.strip()) > MAX_NAME:
        raise ServiceError(f"The name can be at most {MAX_NAME} characters.")


def _check_dates(settings: Settings, start_date: str | None, end_date: str | None) -> dict:
    """Start and end dates of a campaign (YYYY-MM-DD). The end must not be before the start or in the past."""
    start, end = _date(start_date), _date(end_date)
    if (start_date and not start) or (end_date and not end):
        raise ServiceError("Dates must look like 2026-10-19.")
    if bool(start) != bool(end):
        raise ServiceError("Give both a start and an end date.")
    if not start:
        return {}
    if end < start:
        raise ServiceError("The end date is before the start date.")
    if end < settings.plan_start:
        raise ServiceError(f"The campaign must run into week 1 or later (it starts {settings.plan_start:%d %b %Y}): "
                           "pick a later end date.")
    if (end - start).days > 366:
        raise ServiceError("A campaign can run for at most a year.")
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def create_campaign(store: Store, settings: Settings, crop: str, target_kg_per_week: float, weeks: int | None = None,
                    name: str | None = None, farmer_ids: list[str] | None = None, start_date: str | None = None,
                    end_date: str | None = None, daily_capacity_kg: float | None = None,
                    working_days: int | None = None, truck_kg: float | None = None) -> dict:
    """A new campaign for a crop (a crop can have several), from a start date to an end date (or, older callers,
    a number of weeks). farmer_ids: farmers of that crop to move into it."""
    if not settings.multi_crop:
        raise ServiceError("Running more than one campaign is turned off (MULTI_CROP).")
    key = normalize_crop(crop)
    if key not in CROP_LABELS:
        raise ServiceError(f"Unknown crop {crop!r}. Use one of: {', '.join(CROP_LABELS)}.")
    from . import mill_ops

    dates = _check_dates(settings, start_date, end_date)
    ops = mill_ops.check_capacity_fields(daily_capacity_kg, working_days, truck_kg)
    if not dates and weeks is None:
        raise ServiceError("Give the campaign's start and end dates.")
    _check_campaign_fields(target_kg_per_week, None if dates else weeks, name)
    camps = list_campaigns(store, settings)
    cid = campaign_id(settings, key)
    if any(c["id"] == cid for c in camps):
        cid = f"{key}-{hashlib.sha1(now_iso().encode() + str(len(camps)).encode()).hexdigest()[:6]}"
    doc = {"crop": key, "name": (name or "").strip() or None, "kind": None, "status": "idle",
           "persona": dict(agent_profile.NEW_CAMPAIGN_PERSONA),  # English calls by default (Agent page to change)
           "target_kg_per_week": round(target_kg_per_week), "created_at": now_iso(), **dates, **ops}
    doc["weeks"] = campaign_weeks(settings, {**doc, "weeks": weeks})
    store.set("campaigns", cid, doc)
    if farmer_ids:
        set_campaign_farmers(store, settings, cid, add=farmer_ids)
    recompute_forecast(store, settings)
    return {"id": cid, **doc}


def update_campaign(store: Store, settings: Settings, ref: str, name: str | None = None,
                    target_kg_per_week: float | None = None, weeks: int | None = None,
                    start_date: str | None = None, end_date: str | None = None, daily_capacity_kg: float | None = None,
                    working_days: int | None = None, truck_kg: float | None = None, segment: dict | None = None) -> dict:
    """Rename a campaign, or change its weekly target, its dates (or weeks) or the segment of farmers it calls.
    Fields left out stay as they are; segment {} calls everyone again."""
    camp = need_campaign(store, settings, ref)
    from . import crm, mill_ops

    if segment is not None:
        try:
            segment = crm.check_segment(segment) or {}
        except crm.CrmError as e:
            raise ServiceError(str(e)) from None

    dates = _check_dates(settings, start_date, end_date)
    _check_campaign_fields(target_kg_per_week, weeks, name)
    changes: dict = {"updated_at": now_iso(), **mill_ops.check_capacity_fields(daily_capacity_kg, working_days, truck_kg)}
    if name is not None:
        changes["name"] = name.strip() or None
    if target_kg_per_week is not None:
        changes["target_kg_per_week"] = round(target_kg_per_week)
    if weeks is not None:
        changes.update(weeks=int(weeks), start_date=None, end_date=None)
    if dates:
        changes.update(dates)
        changes["weeks"] = campaign_weeks(settings, dates)
    if segment is not None:
        changes["segment"] = segment or None
    store.set("campaigns", camp["id"], changes, merge=True)
    recompute_forecast(store, settings)
    return {**camp, **changes}


def delete_campaign(store: Store, settings: Settings, ref: str) -> dict:
    """Remove a campaign. Its farmers stay in the farmer database (in no campaign); past calls and offers stay."""
    camp = need_campaign(store, settings, ref)
    camps = list_campaigns(store, settings)
    if len(camps) <= 1:
        raise ServiceError("This is the only campaign. Create another before removing it.")
    if camp.get("status") == "running":
        raise ServiceError("This campaign is calling right now. Stop it first.")
    farmers = store.list("farmers")
    freed = 0
    for f in campaign_members(store, settings, camp["id"], farmers, camps):
        store.set("farmers", f["id"], {"campaign_id": None}, merge=True)
        freed += 1
    store.delete("campaigns", camp["id"])
    recompute_forecast(store, settings)
    return {"deleted": camp["id"], "farmers_freed": freed}


def set_campaign_farmers(store: Store, settings: Settings, ref: str, add: list[str] | None = None,
                         remove: list[str] | None = None) -> dict:
    """Move farmers into this campaign (out of any other) or out of it, back to the farmer database only."""
    camp = need_campaign(store, settings, ref)
    crop = campaign_crop(settings, camp)
    camps = list_campaigns(store, settings)
    added, removed, problems = 0, 0, []
    for fid in add or []:
        f = store.get("farmers", fid)
        if not f:
            problems.append(f"{fid}: not found")
            continue
        if farmer_crop(settings, f) != crop:
            problems.append(f"{f.get('name', fid)} grows {CROP_LABELS.get(farmer_crop(settings, f))}, not {CROP_LABELS.get(crop)}")
            continue
        if farmer_campaign(settings, f, camps) != camp["id"] or not f.get("to_call"):
            store.set("farmers", fid, {"campaign_id": camp["id"], "to_call": True}, merge=True)
            added += 1
    for fid in remove or []:
        f = store.get("farmers", fid)
        if f and farmer_campaign(settings, f, camps) == camp["id"]:
            store.set("farmers", fid, {"campaign_id": None}, merge=True)
            removed += 1
    if added or removed:
        recompute_forecast(store, settings)
    return {"campaign_id": camp["id"], "added": added, "removed": removed, "problems": problems}


# ---------- forecast ----------

def recompute_forecast(store: Store, settings: Settings) -> list[dict]:
    """One set of weekly rows per campaign, each from the harvests and offers of that campaign's farmers only."""
    refresh_campaign_status(store, settings)  # also heals a campaign left "running" after its last call
    camps = list_campaigns(store, settings)
    farmer_list = store.list("farmers")
    farmers = {f["id"]: f for f in farmer_list}
    by_camp: dict[str | None, dict[str, list]] = {}
    for coll in ("harvests", "offers"):
        for d in store.list(coll):
            by_camp.setdefault(doc_campaign(settings, d, farmers, camps), {"harvests": [], "offers": []})[coll].append(d)
    rows: list[dict] = []
    keep: set[str] = set()
    for camp in camps:
        crop = campaign_crop(settings, camp)
        weeks = campaign_weeks(settings, camp)
        target = int(camp.get("target_kg_per_week") or settings.target_kg_per_week)
        mine = by_camp.get(camp["id"], {"harvests": [], "offers": []})
        harvests, offers = mine["harvests"], mine["offers"]
        crop_farmers = [f for f in farmer_list if farmer_campaign(settings, f, camps) == camp["id"]]
        from . import mill_ops

        computed = fc.compute_forecast(harvests, offers, settings.plan_start, weeks, target, settings.gap_tolerance)
        computed = mill_ops.mark_surplus(camp, _before_start(settings, camp, computed))
        for row in computed:
            row["crop"] = crop
            row["campaign_id"] = camp["id"]
            row["shortlist"] = (fc.shortlist(row["week"], crop_farmers, harvests, offers,
                                             settings.plan_start, weeks) if row["is_gap"] else [])
            row["reasons"] = (fc.gap_reasons(row["week"], harvests, settings.plan_start, weeks)
                              if row["is_gap"] else None)
            row["note"] = gap_note_text(row) if row["is_gap"] else None
            row["updated_at"] = now_iso()
            row["id"] = forecast_row_id(settings, camp["id"], row["label"])
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


def _row_matches(row: dict, ref: str) -> bool:
    """A forecast row of this campaign id, or (older callers) of this crop's first campaign."""
    if row.get("campaign_id"):
        if row["campaign_id"] == ref:
            return True
        try:
            crop = normalize_crop(ref)
        except Exception:  # noqa: BLE001
            return False
        return row["campaign_id"] in ("current", crop) and normalize_crop(row.get("crop") or crop) == crop
    try:
        return normalize_crop(row.get("crop") or ref) == normalize_crop(ref)
    except Exception:  # noqa: BLE001
        return False


def first_gap_week(store: Store, crop: str | None = None) -> dict | None:
    """The earliest short week; for one campaign (by id, or a crop's first campaign) when given."""
    rows = sorted(store.list("forecast"), key=lambda r: r.get("week", 0))
    if crop:
        rows = [r for r in rows if _row_matches(r, crop)]
    return next((r for r in rows if r.get("is_gap")), None)


FULL_WEEK_LOOKAHEAD = 3  # fruit cannot wait more than three weeks (see mill_ops.reschedule_harvest)


def week_fill(store: Store, settings: Settings, camp_id: str | None, week: int, *,
              own_kg: float = 0.0, own_pending_kg: float = 0.0) -> dict | None:
    """How full one forecast week of a campaign is. A week is full when the supply already counted for it (expected, plus
    offers waiting for approval) has reached the week's target, or the mill's weekly capacity.
    own_kg / own_pending_kg: this farmer's or offer's own part of that week, taken out first so that confirming
    one's own date or approving one's own offer is not judged against itself. None when the week is not in the forecast."""
    row = next((r for r in store.list("forecast") if r.get("week") == week and camp_id and _row_matches(r, camp_id)), None)
    if not row:
        return None
    target = float(row.get("target_kg") or 0)
    base = max(float(row.get("expected_kg", 0)) - own_kg, 0) + max(float(row.get("pending_kg", 0)) - own_pending_kg, 0)
    capacity = float(row.get("capacity_kg") or 0)
    full = bool(target) and base >= target
    room = max(target - base, 0)
    if capacity:
        full = full or base >= capacity
        room = min(room, max(capacity - base, 0))
    return {"week": week, "label": fc.week_label(week), "week_start": row.get("week_start"), "full": full,
            "room_kg": 0 if full else round(room)}


def next_week_with_room(store: Store, settings: Settings, camp_id: str | None, after_week: int) -> dict | None:
    """The nearest later week (within three weeks) that still has room."""
    for week in range(after_week + 1, after_week + FULL_WEEK_LOOKAHEAD + 1):
        fill = week_fill(store, settings, camp_id, week)
        if fill and not fill["full"]:
            return fill
    return None


def gap_week_for_farmer(store: Store, settings: Settings, farmer: dict) -> dict | None:
    camp = campaign_of_farmer(store, settings, farmer)
    return first_gap_week(store, camp["id"] if camp else farmer_crop(settings, farmer))


def _forecast_rows(store: Store, crop: str | None) -> list[dict]:
    rows = sorted(store.list("forecast"), key=lambda r: (r.get("campaign_id") or r.get("crop") or "", r.get("week", 0)))
    return [r for r in rows if not crop or _row_matches(r, crop)]


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
    farmer = store.get("farmers", farmer_id)
    weeks = settings_for_farmer(store, settings, farmer).weeks if farmer else weeks_for(store, settings, crop)
    week = fc.week_index(date, settings.plan_start, weeks)
    return {"harvest_id": harvest_id, "week": week,
            "week_label": fc.week_label(week) if week else "outside the forecast horizon"}


# ---------- offers ----------

def create_offer(store: Store, settings: Settings, *, farmer: dict, crop: str, kg: float,
                 price: float, deliver_week: int | None, call_id: str | None,
                 status: str = "pending", requested_price: float | None = None,
                 source: str = "call", negotiation: dict | None = None, campaign: str | None = None) -> dict:
    crop = normalize_crop(crop)
    if not math.isfinite(kg) or kg <= 0 or kg > MAX_OFFER_KG:
        raise ServiceError(f"Volume must be between 1 and {MAX_OFFER_KG:,} kg.")
    limits = get_limits(store, crop)
    if status == "pending" and not limits.within(price):
        raise ServiceError("Price is outside the floor and ceiling.")
    # The campaign it counts for: the call's (a gap-fill call to a supplier), else the farmer's.
    call = store.get("calls", call_id) if call_id else None
    camp = resolve_campaign(store, settings, campaign) if campaign else None
    if not camp and call and call.get("campaign_id"):
        camp = resolve_campaign(store, settings, call["campaign_id"])
    if not camp:
        camp = campaign_of_farmer(store, settings, farmer) if farmer.get("type") != "supplier" else None
    if not camp:
        camp = resolve_campaign(store, settings, crop)
    camp = camp or {}
    weeks = campaign_weeks(settings, camp)
    harvest = store.get("harvests", f"h-{farmer['id']}-{crop}")
    from_week = None
    harvest_id = None
    if harvest and farmer.get("type") != "supplier":
        hw = fc.week_index(harvest["ready_date"], settings.plan_start, weeks)
        if hw and deliver_week and hw > deliver_week:
            from_week, harvest_id = hw, harvest["id"]
            kg = min(kg, float(harvest["kg"]))
    plan_start = settings.plan_start
    doc = {
        "campaign_id": camp.get("id"),
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


class WeekFull(ServiceError):
    """The offer's delivery week no longer has room. The planner may still approve it on purpose (allow_full)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status=409)


def _refuse_if_week_full(store: Store, settings: Settings, offer: dict) -> None:
    week = fc.week_of_offer(offer, "deliver_week", settings.plan_start, settings.weeks)
    if not week:
        return
    farmers = {f["id"]: f for f in store.list("farmers")}
    camp_id = doc_campaign(settings, offer, farmers, list_campaigns(store, settings))
    own = float(offer.get("kg", 0)) if offer.get("status") == "pending" else 0.0
    fill = week_fill(store, settings, camp_id, week, own_pending_kg=own)
    if fill and fill["full"]:
        later = next_week_with_room(store, settings, camp_id, week)
        hint = f" {later['label']} (from {later['week_start']}) still has room." if later else ""
        raise WeekFull(f"{fill['label']} is already filled by other supply and offers.{hint} Reject this offer, or approve it anyway.")


def decide_offer(store: Store, settings: Settings, offer_id: str, approve: bool, actor=None, allow_full: bool = False) -> dict:
    offer = store.get("offers", offer_id)
    if not offer:
        raise ServiceError("Offer not found.")
    if offer["status"] not in ("pending", "escalated"):
        raise ServiceError(f"Offer is already {offer['status']}.")
    changes = {}
    if approve:
        if not allow_full:
            _refuse_if_week_full(store, settings, offer)
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
    camp = need_campaign(store, settings, crop)
    crop = campaign_crop(settings, camp)
    weeks = campaign_weeks(settings, camp)
    target = int(camp.get("target_kg_per_week") or settings.target_kg_per_week)
    harvests = campaign_records(store, settings, camp["id"], "harvests")
    offers = campaign_records(store, settings, camp["id"], "offers")

    def rows(approve_ids: set[str]) -> list[dict]:
        trial = [{**o, "status": "approved"} if o["id"] in approve_ids else o for o in offers]
        return _before_start(settings, camp, fc.compute_forecast(harvests, trial, settings.plan_start, weeks, target,
                                                                 settings.gap_tolerance))

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
    return {"crop": crop, "campaign_id": camp["id"], "offers": per_offer, "all_pending": together,
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


def offer_from_rival_quote(store: Store, settings: Settings, quote_id: str, campaign: str | None = None) -> dict:
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
                        negotiation={"rival_quote": True}, campaign=campaign)


# ---------- calls and campaigns ----------

def queue_call(store: Store, farmer: dict, kind: str, gap_week: int | None = None,
               offer_id: str | None = None, attempt: int = 1, channel: str = "browser",
               campaign_id: str | None = None, gap_start: str | None = None) -> str:
    # gap_start: the date the short week starts. The week number changes when the planning weeks roll on Monday,
    # so a call queued on Sunday must find its week again by date (see call_gap_week).
    # "channel" names what carries the call's audio: "browser" (the only one built) today,
    # "twilio" once a real-phone adapter exists. See live_session.Channel for the seam.
    return store.add("calls", {
        "farmer_id": farmer["id"], "farmer_name": farmer.get("name", farmer["id"]),
        "kind": kind, "status": "queued", "attempt": attempt, "gap_week": gap_week, "gap_week_start": gap_start,
        "offer_id": offer_id, "channel": channel, "campaign_id": campaign_id,
        "created_at": now_iso(), "started_at": None,
        "ended_at": None, "summary": None, "outcome": None, "transcript": None, "consent": None,
    })


def call_gap_week(call: dict, settings: Settings) -> int | None:
    """The short week a call is about, as a week number in today's planning weeks. A call queued before the weeks
    rolled (Monday) keeps the date of its week, so it still names the right week."""
    start = call.get("gap_week_start")
    if start:
        index = fc.week_index(start, settings.plan_start, settings.weeks)
        if index:
            return index
    return call.get("gap_week")


def _open_call_for(store: Store, farmer_id: str, kind: str) -> bool:
    return any(c["farmer_id"] == farmer_id and c["kind"] == kind and c["status"] in ("queued", "on_call")
               for c in store.list("calls"))


# ---------- who to call (the "to call" stage) ----------
# A harvest call asks a farmer for their next harvest. It is needed when the forecast has nothing current from them:
# no harvest answer, an unsure one, or one whose harvest date has passed; or when the planner marked the farmer to
# always call (to_call). A farmer with a firm, current answer is not called again. The dashboard shows the same reasons
# (frontend crm.js); keep the two in step.
CALL_REASONS = {
    "no_answer": "No harvest answer yet",
    "unsure": "Answer was unsure",
    "date_passed": "Harvest date has passed",
    "flagged": "Marked to call",
}


def call_reason(farmer: dict, harvest: dict | None, today: dt.date | None = None) -> str | None:
    if farmer.get("type") == "supplier" or farmer.get("do_not_call"):
        return None
    today = today or today_local()
    if not harvest:
        return "no_answer"
    ready = _date(harvest.get("ready_date"))
    if ready and ready < today and not harvest.get("every_days"):
        return "date_passed"
    if harvest.get("confidence") == "unsure":
        return "unsure"
    if farmer.get("to_call"):
        return "flagged"
    return None


def call_list(store: Store, settings: Settings, members: list[dict], today: dt.date | None = None) -> dict[str, str]:
    """The campaign's farmers who need a harvest call, with the reason for each."""
    harvests = {h["farmer_id"]: h for h in store.list("harvests")}
    # A harvest dated inside the planning weeks is current, even when the weeks are pinned to the past (PLAN_START).
    cutoff = min(today or today_local(), settings.plan_start)
    out = {}
    for f in members:
        r = call_reason(f, harvests.get(f["id"]), cutoff)
        if r:
            out[f["id"]] = r
    return out


def start_campaign(store: Store, settings: Settings, kind: str = "collect", crop: str | None = None,
                   channel: str = "browser") -> dict:
    """Queue the calls of one campaign (by id, or a crop's first campaign; the default campaign when none is named).

    channel "browser": the calls wait in the call client (the demo). channel "twilio": real phone
    calls, dialled one at a time by dial_next (each finished call starts the next)."""
    if channel not in ("browser", "twilio"):
        raise ServiceError("Channel must be browser or twilio.")
    if channel == "twilio" and not phone_calls_ready(settings):
        raise ServiceError(phone_calls_note(settings))
    camp = need_campaign(store, settings, crop)
    crop = campaign_crop(settings, camp)
    label = camp.get("name") or CROP_LABELS.get(crop, crop)
    camps = list_campaigns(store, settings)
    all_farmers = store.list("farmers")
    members = campaign_members(store, settings, camp["id"], all_farmers, camps)
    # Suppliers sell to any campaign of their crop.
    farmers = members + [f for f in all_farmers if f.get("type") == "supplier" and farmer_crop(settings, f) == crop
                         and f not in members]
    recompute_forecast(store, settings)  # rows written before crops existed pick up their crop now
    gap = first_gap_week(store, camp["id"])
    if kind == "collect":
        reasons = call_list(store, settings, members)
        targets = [f for f in members if f["id"] in reasons]
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
    # Real phone calls go only to farmers with Agent calls on; the rest are the planner's to call by hand. The demo
    # phone rings no real phone, so a demo round can use every farmer on the list.
    by_hand = [f for f in targets if not f.get("agent_calls")] if channel == "twilio" else []
    targets = [f for f in targets if f.get("agent_calls")] if channel == "twilio" else targets
    if camp.get("segment"):  # the campaign is aimed at one segment of its farmers
        from . import crm, track_record

        rel = track_record.reliabilities(store)
        outside = [f for f in targets if not crm.in_segment(crm.segment_of(f, rel.get(f["id"])), camp["segment"])]
        targets = [f for f in targets if f not in outside]
        if not targets and outside:
            raise ServiceError(f"No {label} farmer to call is in this campaign's segment. Change the segment or call everyone.")
    if not targets:
        if by_hand:
            raise ServiceError(f"None of the {len(by_hand)} {label} farmers to call has Agent calls on, so they are yours "
                               "to call. Turn Agent calls on for the farmers the agent should phone.")
        raise ServiceError(f"No {label} farmers are ready to call. Add farmers to this campaign first.")
    queued = 0
    target_ids = {f["id"] for f in targets}
    # Leftovers from another campaign, from before campaigns, or undialled retries; this round's own calls stay.
    replaced = withdraw_calls(store, lambda c: c["farmer_id"] in target_ids and c.get("kind") == kind
                              and (c.get("campaign_id") != camp["id"] or (c.get("attempt") or 1) > 1))
    for farmer in sorted(targets, key=lambda f: f["id"]):
        if not _open_call_for(store, farmer["id"], kind):
            queue_call(store, farmer, kind, gap_week=gap_week, channel=channel, campaign_id=camp["id"],
                       gap_start=gap.get("week_start") if gap else None)
            queued += 1
    store.set("campaigns", camp["id"], {"status": "running", "kind": kind, "started_at": now_iso(),
                                        "gap_week": gap_week, "crop": crop, "channel": channel}, merge=True)
    dialled = dial_next(store, settings) if channel == "twilio" else None
    return {"queued": queued, "kind": kind, "gap_week": gap_week, "crop": crop, "campaign_id": camp["id"],
            "channel": channel, "dialled": dialled, "by_hand": len(by_hand), "replaced": replaced}


def stop_campaign(store: Store, settings: Settings, crop: str | None = None) -> dict:
    """Stop a campaign and withdraw its calls that have not started (a phone already ringing or a call on now is
    left to finish)."""
    camp = need_campaign(store, settings, crop)
    store.set("campaigns", camp["id"], {"status": "stopped", "stopped_at": now_iso()}, merge=True)
    members = {f["id"] for f in campaign_members(store, settings, camp["id"])}
    withdrawn = withdraw_calls(store, lambda c: c.get("campaign_id") == camp["id"]
                               or (not c.get("campaign_id") and c["farmer_id"] in members))
    return {"status": "stopped", "crop": campaign_crop(settings, camp), "campaign_id": camp["id"],
            "calls_withdrawn": withdrawn}


def withdraw_calls(store: Store, which=None) -> int:
    """End calls that are waiting and have not started: never answered in the call client, or a retry nobody dialled.
    They stay in the history as "withdrawn" (no retry), so a farmer no longer shows as being called."""
    n = 0
    for c in store.list("calls"):
        if c["status"] != "queued" or c.get("dialed_at") or c.get("kind") == "confirm":
            continue
        if which and not which(c):
            continue
        store.set("calls", c["id"], {"status": "dropped", "outcome": "withdrawn", "summary": "Withdrawn before it started.",
                                     "ended_at": now_iso()}, merge=True)
        n += 1
    return n


def withdraw_farmer_calls(store: Store, settings: Settings, farmer_id: str) -> dict:
    if not store.get("farmers", farmer_id):
        raise ServiceError("Farmer not found.")
    n = withdraw_calls(store, lambda c: c["farmer_id"] == farmer_id)
    refresh_campaign_status(store, settings)
    return {"farmer_id": farmer_id, "calls_withdrawn": n}


STALE_AFTER = dt.timedelta(minutes=20)


def heal_stale_calls(store: Store, settings: Settings, now: dt.datetime | None = None) -> int:
    """A call left "on call" by a server restart (or by a channel that no longer exists) would block its farmer for
    ever. A call still on after its time limit plus STALE_AFTER, or on a channel that is gone, is ended as dropped
    (no retry). A phone that rang without an answer and never got Twilio's final status is ended the same way."""
    now = now or dt.datetime.now(dt.timezone.utc)
    limit = dt.timedelta(seconds=settings.max_call_seconds) + STALE_AFTER
    n = 0
    for c in store.list("calls"):
        gone = c.get("channel") not in (None, "browser", "twilio")
        if c["status"] == "on_call":
            since = c.get("started_at")
        elif c["status"] == "queued" and (c.get("dialed_at") or gone):
            since = c.get("dialed_at") or c.get("created_at")
        else:
            continue
        try:
            old = now - dt.datetime.fromisoformat(since) > limit
        except (TypeError, ValueError):
            old = True
        if gone or old:
            store.set("calls", c["id"], {"status": "dropped", "outcome": c.get("outcome") or "dropped",
                                         "summary": c.get("summary") or "The call ended without a result.",
                                         "ended_at": now_iso()}, merge=True)
            n += 1
    return n


def call_now(store: Store, farmer_id: str, kind: str | None = None, settings: Settings | None = None) -> str:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise ServiceError("Farmer not found.")
    if farmer.get("do_not_call"):
        raise ServiceError("This farmer asked not to be called again.")
    if settings is None:
        gap = first_gap_week(store, normalize_crop(farmer.get("crop") or "palm"))
        camp = None
    else:
        camp = campaign_of_farmer(store, settings, farmer)
        gap = first_gap_week(store, camp["id"]) if camp else None
    kind = kind or "collect"
    return queue_call(store, farmer, kind, gap_week=gap["week"] if gap else None,
                      campaign_id=camp["id"] if camp else None, gap_start=gap.get("week_start") if gap else None)


def twilio_ready(settings: Settings) -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token
               and settings.twilio_from_number and settings.public_base_url)


def phone_calls_ready(settings: Settings) -> bool:
    """True when the dashboard may offer "Call by phone": Twilio configured and the safety gate open."""
    return twilio_ready(settings) and settings.real_calls_enabled


# ---------- who real calls may reach ----------
# A real call (and a real text) only goes to a farmer with Agent calls on (the farmer's agent_calls), or to a number in
# REAL_CALL_ALLOWLIST on the server ("*" lets any number through).

def allowed_numbers(store: Store | None, settings: Settings) -> set[str]:
    nums = {n for n in settings.real_call_allowlist if n != "*"}
    if store is not None:
        nums |= {normalize_phone(f["phone"]) for f in store.list("farmers") if f.get("agent_calls") and f.get("phone")}
    return nums


def number_allowed(store: Store | None, settings: Settings, e164: str) -> bool:
    return "*" in settings.real_call_allowlist or e164 in allowed_numbers(store, settings)


def phone_calls_note(settings: Settings, store: Store | None = None) -> str:
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
    n = len(allowed_numbers(store, settings))
    return (f"Real phone calls are on, only to farmers with Agent calls on ({n} number{'s' if n != 1 else ''})."
            if n else "Real phone calls are on, but no farmer has Agent calls on yet.")


def browser_call_token(settings: Settings, call_id: str) -> str:
    """Per-call secret for the browser's call socket, handed to a signed-in user by POST /api/calls/{id}/token.
    Without it anyone who guessed a queued call id could open the socket and play the farmer."""
    return hmac.new(settings.jwt_secret.encode(), f"ws-call:{call_id}".encode(), hashlib.sha256).hexdigest()[:32]


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


def _dialable_number(store: Store, settings: Settings, farmer: dict) -> str:
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
    if not number_allowed(store, settings, to_number):
        raise ServiceError(f"Agent calls is off for {farmer.get('name', 'this farmer')}, so the agent may not phone "
                           f"{to_number}. Turn Agent calls on for this farmer first.")
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
            _dialable_number(store, settings, {})  # report the configuration problem first
        raise ServiceError("Farmer not found.")
    to_number = _dialable_number(store, settings, farmer)
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
        camp = campaign_of_farmer(store, settings, farmer)
        gap = first_gap_week(store, camp["id"]) if camp else None
        call_id = queue_call(store, farmer, kind or "collect", gap_week=gap["week"] if gap else None,
                             channel="twilio", campaign_id=camp["id"] if camp else None)
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
    """Phone campaigns ring PHONE_CALLS_AT_ONCE farmers at the same time (each call is a Gemini Live session, and the
    Live API allows only a few at once). Dial the oldest waiting first-attempt phone calls of a running phone campaign
    until that many are ringing or in progress. A farmer the safety gate refuses is skipped (the call ends as dropped
    with the reason, no retry) and the next one is tried. Retries of missed calls are left for the planner to dial
    (see dial_now). Returns the first call dialled, if any."""
    first, seen = None, set()
    while True:
        placed = _dial_one(store, settings)
        if not placed or placed in seen:  # never loop on a call that did not leave the waiting list
            return first
        seen.add(placed)
        first = first or placed


def _dial_one(store: Store, settings: Settings) -> str | None:
    with _dial_lock:
        calls = store.list("calls")
        busy = sum(1 for c in calls if c.get("channel") == "twilio" and (
            c["status"] == "on_call" or (c["status"] == "queued" and c.get("dialed_at"))))
        if busy >= settings.phone_calls_at_once:
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
                _place_twilio_call(store, settings, call["id"], _dialable_number(store, settings, farmer))
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
                transcript: list[dict], consent_proof: dict | None = None) -> None:
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
        # Proof of consent (PDP Law, Art. 24): when the farmer answered and which notice was read (recording or transcript, how many days).
        "consent_proof": consent_proof if consent else None,
        # Consent notice: the transcript is kept only when the farmer agreed.
        "transcript": transcript if consent else None, "ended_at": now_iso(),
        # The notice told the farmer how long it is kept (PDP Law, Art. 21); purge_expired_transcripts enforces it.
        "transcript_expires_at": ((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.call_audio_retention_days))
                                  .isoformat(timespec="seconds") if consent and transcript else None),
    }, merge=True)
    if (status == "done" and outcome == "completed" and call.get("kind") == "confirm"
            and call.get("offer_id")):
        store.set("offers", call["offer_id"], {"confirmed_by_voice": True}, merge=True)
        from . import messaging

        offer = store.get("offers", call["offer_id"])
        if offer:
            try:  # a text that cannot be sent must not stop the call from finishing (retry, campaign status)
                messaging.send_deal_confirmation(store, settings, offer)
            except Exception:  # noqa: BLE001
                log.exception("call %s: the deal confirmation text failed", call_id)
    if outcome == "stopped":
        # The farmer explicitly asked not to be called again; honour it for every future campaign.
        store.set("farmers", call["farmer_id"], {"do_not_call": True}, merge=True)
    if status == "dropped" and call.get("attempt", 1) < settings.max_call_attempts:
        farmer = store.get("farmers", call["farmer_id"])
        if farmer:
            store.set("calls", call_id, {"retry_queued": True}, merge=True)
            queue_call(store, farmer, call["kind"], gap_week=call.get("gap_week"),
                       offer_id=call.get("offer_id"), attempt=call.get("attempt", 1) + 1,
                       channel=call.get("channel", "browser"), campaign_id=call.get("campaign_id"),
                       gap_start=call.get("gap_week_start"))
    refresh_campaign_status(store, settings)  # after any retry was queued: the last call ending ends the campaign
    try:
        purge_expired_transcripts(store, settings)
    except Exception:  # noqa: BLE001
        log.exception("could not purge expired transcripts")
    if call.get("channel") == "twilio" and call.get("kind") in ("collect", "gap_fill"):
        _after_phone_call(store, settings)


# The languages a farmer can be called in. The agent speaks whatever the name says, so a typo here
# would make it speak the wrong thing; the farmer form offers exactly this list.
LANGUAGES = agent_profile.LANGUAGES  # one list for the farmer form and the agent's languages
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
    from . import mill_ops

    return digits, {
        "name": row["name"], "phone": row["phone"], "crop": crop,
        "language": language, "village": row.get("village", ""), "usual_kg_week": usual,
        "can_pull_forward": row.get("can_pull_forward", "").lower() in ("1", "yes", "true"),
        # agent_calls: the AI agent phones this farmer. Off (the default), the planner calls them by hand; it is also
        # the real-call allowlist (number_allowed).
        "agent_calls": row.get("agent_calls", "").lower() in ("1", "yes", "true"),
        **mill_ops.plot_fields(row),
    }


NO_CAMPAIGN = ""  # campaign_id="" on add or upload: the farmer database only, in no campaign


def add_farmer(store: Store, row: dict, campaign_id: str | None = None, settings: Settings | None = None) -> str:
    """Save one farmer. The id comes from the phone number, so the same phone again updates that
    farmer instead of adding a duplicate. campaign_id: a campaign to put them in, NO_CAMPAIGN for none;
    left out, an existing farmer keeps theirs and a new one joins their crop's first campaign."""
    digits, fields = _farmer_fields(row)
    fid = str(row.get("id") or "").strip() or "u" + hashlib.sha1(digits.encode()).hexdigest()[:8]
    clean = {k.strip().lower(): v for k, v in row.items() if k}
    old = store.get("farmers", fid) or {}
    doc = {**fields, "type": str(clean.get("type") or "farmer").strip() or "farmer", "to_call": True}
    if campaign_id is not None:
        if campaign_id and settings is not None:
            camp = need_campaign(store, settings, campaign_id)
            if campaign_crop(settings, camp) != fields["crop"]:
                raise ServiceError(f"{fields['name']} grows {CROP_LABELS.get(fields['crop'])}; this campaign is "
                                   f"{CROP_LABELS.get(campaign_crop(settings, camp))}.")
            campaign_id = camp["id"]
        doc["campaign_id"] = campaign_id or None
    elif "campaign_id" in old:
        doc["campaign_id"] = old["campaign_id"]
    if old.get("do_not_call"):  # a farmer who asked not to be called stays that way when the same phone is added again
        doc["do_not_call"] = True
        doc["to_call"] = False
    store.set("farmers", fid, doc)
    return fid


def update_farmer(store: Store, farmer_id: str, row: dict) -> dict:
    """Edit a farmer's details. Keeps the id and the call flags (to_call, do_not_call)."""
    if not store.get("farmers", farmer_id):
        raise ServiceError("Farmer not found.")
    _, fields = _farmer_fields(row)
    for keys in (("plot_lat", "plot_lng"), ("plot_ha",), ("certification",)):  # a field left empty clears it
        if keys[0] in row and keys[0] not in fields:
            fields.update({k: None for k in keys})
    store.set("farmers", farmer_id, fields, merge=True)
    return store.get("farmers", farmer_id)


def delete_farmer(store: Store, farmer_id: str) -> dict:
    """Remove a farmer and withdraw their waiting calls. Past calls, offers and harvests stay,
    so the forecast and the audit trail do not change."""
    if not store.get("farmers", farmer_id):
        raise ServiceError("Farmer not found.")
    for c in store.list("calls"):
        if c["farmer_id"] == farmer_id and c["status"] == "on_call" and c.get("channel", "browser") in ("browser", "twilio"):
            raise ServiceError("This farmer is on a call right now. Try again when it ends.")
    withdrawn = 0
    for c in store.list("calls"):
        if c["farmer_id"] == farmer_id and c["status"] == "queued":
            store.delete("calls", c["id"])
            withdrawn += 1
    store.delete("farmers", farmer_id)
    return {"deleted": farmer_id, "calls_withdrawn": withdrawn}


def upload_farmers(store: Store, settings: Settings, csv_text: str, campaign_id: str | None = None) -> dict:
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
            add_farmer(store, row, campaign_id, settings)
            added += 1
        except ServiceError as e:
            skipped.append(f"Line {number}: {e}")
    return {"added": added, "skipped": skipped}
