"""HTTP and WebSocket entry point (Cloud Run service)."""

from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (access, agent_profile, auth, calendar_view, messaging, mill_ops, purchase_order, seed_data, services,
               track_record)
from .call_audio import make_audio_store
from .config import Settings, get_settings
from .live_session import BrowserChannel, run_call
from .store import COLLECTIONS, Store, make_store
from .twilio_channel import TwilioChannel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("harvest")


class LimitsIn(BaseModel):
    floor_price: float = Field(gt=0)
    ceiling_price: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    first_premium_pct: float = 4.0  # matches rules_engine.Limits' default
    step_pct: float = 2.0


class FarmerIn(BaseModel):
    name: str = ""
    phone: str = ""
    crop: str = ""
    language: str = ""
    village: str = ""
    usual_kg_week: float | None = None
    can_pull_forward: bool = False
    campaign_id: str | None = None  # on add: a campaign to put the farmer in; "" for none (the database only)
    allow_calls: bool = False  # on add: also put the number on the real-call allowlist
    plot_lat: str = ""  # traceability: where the farmer's plot is, its area and certification (all optional)
    plot_lng: str = ""
    plot_ha: str = ""
    certification: str = ""


class CsvIn(BaseModel):
    csv: str
    campaign_id: str | None = None  # farmers upload: the campaign they join ("" for none)


class CampaignIn(BaseModel):
    kind: str = "collect"
    crop: str = ""  # empty: the default crop
    channel: str = "browser"  # "twilio": real phone calls, dialled one at a time


class NewCampaignIn(BaseModel):
    crop: str
    target_kg_per_week: float
    weeks: int | None = None  # older screens; the dashboard sends start_date and end_date
    name: str | None = None
    farmer_ids: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    daily_capacity_kg: float | None = None
    working_days: int | None = None
    truck_kg: float | None = None


class CampaignEditIn(BaseModel):
    name: str | None = None
    target_kg_per_week: float | None = None
    weeks: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    daily_capacity_kg: float | None = None
    working_days: int | None = None
    truck_kg: float | None = None


class CampaignFarmersIn(BaseModel):
    add: list[str] = []
    remove: list[str] = []


class ToCallIn(BaseModel):
    to_call: bool


class AllowNumberIn(BaseModel):
    phone: str
    label: str = ""
    farmer_id: str | None = None


class RivalOfferIn(BaseModel):
    campaign_id: str | None = None


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""


class UserIn(BaseModel):
    name: str = ""
    role: str = ""
    active: bool = True
    username: str = ""
    password: str = ""  # required for a new user; blank keeps the current one on an edit


class CallNowIn(BaseModel):
    kind: str | None = None


class AgentProfileIn(BaseModel):
    persona: dict = {}
    questions: list[dict] = []


class HarvestIn(BaseModel):
    kg: float
    ready_date: str
    confidence: str = "firm"
    every_days: float | None = None  # days between harvest rounds; later rounds are projected from it


class AnswerIn(BaseModel):
    answer: str


class ScheduleIn(BaseModel):
    enabled: bool = False
    channel: str = "browser"
    days: list[int] | None = None  # 0 = Monday ... 6 = Sunday
    time: str | None = None  # "06:00", on the hour, Asia/Jakarta


class DeliveryIn(BaseModel):
    farmer_id: str
    kg: float  # gross weight at the weighbridge
    date: str
    unripe_pct: float | None = None  # grading deductions, percent of the gross weight
    dirt_pct: float | None = None
    other_pct: float | None = None


class RescheduleIn(BaseModel):
    to_date: str
    reason: str = ""


class OfficialPriceIn(BaseModel):
    crop: str = "palm"
    province: str
    valid_from: str
    price_per_kg: float
    source: str = ""
    url: str = ""


class FollowOfficialIn(BaseModel):
    enabled: bool
    province: str | None = None


class DialIn(BaseModel):
    kind: str | None = None


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or make_store(settings.store_backend, settings.gcp_project)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        access.ensure_credentials(store, settings.demo_password)  # also gives older users a username
        if settings.seed_on_start:
            seed_data.load_seed(store, settings)
            log.info("Seeded demo data; plan starts %s", settings.plan_start)
        yield

    app = FastAPI(title="Harvest-Call Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])

    @app.middleware("http")
    async def roll_planning_weeks(request: Request, call_next):
        """Week 1 is next week: on the first request of a new week, every handler (they all read the
        `settings` of this closure) moves to the new weeks. Off when PLAN_START pins the dates."""
        nonlocal settings
        rolled = services.roll_weeks(store, settings)
        if rolled is not settings:
            settings = rolled
            app.state.settings = rolled
        return await call_next(request)

    def need(capability: str):
        return auth.require(settings, store, capability)

    users_admin = Depends(need("users.admin"))

    @app.exception_handler(services.ServiceError)
    async def service_error(_: Request, exc: services.ServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(access.AccessError)
    async def access_error(_: Request, exc: access.AccessError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ----- health and config -----

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "store": settings.store_backend, "model": settings.live_model}

    @app.get("/config.js", include_in_schema=False)
    def config_js():
        cfg = {"apiBase": "", "millName": settings.mill_name,
               "firebase": json.loads(settings.firebase_web_config) if settings.firebase_web_config else None}
        return Response(f"window.HARVEST_CONFIG = {json.dumps(cfg)};", media_type="application/javascript")

    # ----- demo sign-in: pick a role, no password -----

    def session_for(user: dict) -> dict:
        token, exp = auth.mint_token(settings, user)
        return {"token": token, "exp": exp, "user_id": user["id"], "username": user.get("username", ""),
                "role": user["role"], "name": user["name"],
                "role_label": (access.get_role(store, user["role"]) or {}).get("label", user["role"]),
                "capabilities": sorted(access.capabilities_of(store, user["role"]))}

    @app.get("/api/auth/demo")
    def demo_accounts():
        """The built-in accounts that still use the demo password, for the sign-in page's demo buttons.
        Empty when DEMO_PASSWORD is empty."""
        if not settings.demo_password:
            return {"password": "", "accounts": []}
        access.ensure_credentials(store, settings.demo_password)
        order = list(access.DEFAULT_ROLES)
        users = sorted((u for u in store.list("users") if u.get("active", True) and u.get("demo_login")),
                       key=lambda u: (order.index(u["role"]) if u["role"] in order else len(order), u["name"].lower()))
        return {"password": settings.demo_password,
                "accounts": [{**access.public_user(store, u),
                              "description": (access.get_role(store, u["role"]) or {}).get("description", "")}
                             for u in users]}

    @app.post("/api/auth/login")
    def login(body: LoginIn):
        access.ensure_credentials(store, settings.demo_password)
        user = access.authenticate(store, body.username, body.password)
        if not user:
            raise HTTPException(401, "Wrong username or password.")
        return session_for(user)

    @app.get("/api/auth/me")
    def me(authorization: str | None = Header(default=None)):
        actor = auth.current_actor(settings, store, authorization)
        claims = auth.read_token(settings, authorization)
        return {"user_id": actor.id, "name": actor.name, "role": actor.role,
                "capabilities": sorted(actor.capabilities), "exp": claims["exp"]}

    # ----- users (the Users page) -----

    @app.get("/api/users")
    def list_users(_: auth.Actor = users_admin):
        access.ensure_credentials(store, settings.demo_password)
        users = sorted(store.list("users"), key=lambda u: (u["role"] != "planner", u["name"].lower()))
        return {"users": [access.public_user(store, u) for u in users],
                "roles": [{"id": r["id"], "label": r.get("label", r["id"]),
                           "description": r.get("description", ""), "capabilities": r.get("capabilities", []),
                           "demo": r["id"] in access.DEMO_ROLES}
                          for r in sorted(store.list("roles"), key=lambda r: (list(access.DEFAULT_ROLES).index(r["id"]) if r["id"] in access.DEFAULT_ROLES else 99, r["id"]))],
                "capabilities": access.CAPABILITIES}

    @app.post("/api/users")
    def create_user(body: UserIn, _: auth.Actor = users_admin):
        return access.public_user(store, access.add_user(store, body.name, body.role, body.username, body.password))

    @app.put("/api/users/{user_id}")
    def edit_user(user_id: str, body: UserIn, _: auth.Actor = users_admin):
        return access.public_user(store, access.update_user(store, user_id, body.name, body.role, body.active,
                                                       body.username, body.password))

    @app.delete("/api/users/{user_id}")
    def remove_user(user_id: str, actor: auth.Actor = users_admin):
        access.delete_user(store, user_id, actor.id)
        return {"deleted": user_id}

    # ----- read model -----

    def snapshot() -> dict:
        services.refresh_campaign_status(store, settings)  # a campaign left "running" by an older version heals here
        data = {c: store.list(c) for c in COLLECTIONS}
        data["settings"] = {"mill_name": settings.mill_name,
                            "language": settings.demo_language, "max_call_seconds": settings.max_call_seconds,
                            "max_call_attempts": settings.max_call_attempts,
                            "plan_start": settings.plan_start.isoformat(),
                            "weeks": settings.weeks, "target_kg_per_week": settings.target_kg_per_week,
                            "gap_tolerance": settings.gap_tolerance, "multi_crop": settings.multi_crop,
                            "phone_calls": services.phone_calls_ready(settings),
                            "phone_calls_note": services.phone_calls_note(settings, store),
                            "web_allowlist_max": settings.web_allowlist_max,
                            "allow_any_number": "*" in settings.real_call_allowlist,
                            "server_allowlist": sorted(n for n in settings.real_call_allowlist if n != "*"),
                            "agent_options": agent_profile.options(),
                            "messaging_note": messaging.channel_note(settings),
                            "weekly_job": bool(settings.job_token)}
        return data

    @app.get("/api/state")
    def state():
        return snapshot()

    @app.get("/api/stream")
    async def stream(request: Request):
        """Server-sent events with the full state, pushed on every change (local mode)."""
        changed = asyncio.Event()
        loop = asyncio.get_running_loop()
        unsubscribe = store.subscribe(lambda *_: loop.call_soon_threadsafe(changed.set))
        poll = None if store.supports_listeners else 3.0

        async def events():
            try:
                while not await request.is_disconnected():
                    yield f"data: {json.dumps(snapshot())}\n\n"
                    try:
                        await asyncio.wait_for(changed.wait(), timeout=poll or 15)
                    except asyncio.TimeoutError:
                        if poll is None:
                            yield ": keep-alive\n\n"
                            continue
                    changed.clear()
                    await asyncio.sleep(0.15)  # coalesce bursts of writes
            finally:
                unsubscribe()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/forecast.csv")
    def forecast_csv(crop: str = "", campaign: str = ""):
        return PlainTextResponse(services.forecast_csv(store, campaign or crop or None), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=forecast.csv"})

    @app.get("/api/forecast/summary")
    async def forecast_summary(crop: str = "", campaign: str = ""):
        """Plain summary plus the gap note; Gemini rewrites the note when a key is configured."""
        ref = campaign or crop or None
        text = services.forecast_summary_text(store, settings, ref)
        gap = services.first_gap_week(store, ref or (services.resolve_campaign(store, settings) or {}).get("id")
                                      or services.default_crop(settings))
        note, by = (None, None)
        if gap and gap.get("note"):
            polished = await asyncio.to_thread(
                _polish, settings, gap["note"],
                f"Rewrite this note for a mill planner explaining why week {gap['week']} is short of supply, "
                "in one plain sentence. Keep every number exactly as given.")
            note, by = (polished, "gemini") if polished else (gap["note"], "template")
        return {"summary": text, "gap_week": gap["week"] if gap else None, "gap_note": note, "gap_note_by": by}

    # ----- planner actions (client writes to Firestore are blocked; everything goes through here) -----

    @app.put("/api/limits/{crop}", dependencies=[Depends(need("limits.edit"))])
    def put_limits(crop: str, body: LimitsIn):
        doc = services.set_limits(store, crop, body.floor_price, body.ceiling_price, body.reference_price,
                                  body.first_premium_pct, body.step_pct)
        services.recompute_forecast(store, settings)
        return doc

    @app.post("/api/farmers")
    def add_farmer(body: FarmerIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        row = body.model_dump()
        row["can_pull_forward"] = "yes" if row["can_pull_forward"] else ""
        cid = row.pop("campaign_id", None)
        allow = row.pop("allow_calls", False)
        if allow and "campaign.run" not in actor.capabilities:
            raise HTTPException(403, "Your role cannot allow real phone calls.")
        fid = services.add_farmer(store, row, cid, settings)
        if allow:
            services.allow_number(store, settings, row["phone"], row["name"], fid, actor)
        services.recompute_forecast(store, settings)
        return {"id": fid}

    @app.put("/api/farmers/{farmer_id}", dependencies=[Depends(need("farmers.manage"))])
    def edit_farmer(farmer_id: str, body: FarmerIn):
        row = body.model_dump()
        row["can_pull_forward"] = "yes" if row["can_pull_forward"] else ""
        row.pop("campaign_id", None)  # moving between campaigns: PUT /api/campaigns/{id}/farmers
        row.pop("allow_calls", None)  # the allowlist: /api/allowed-numbers
        return services.update_farmer(store, farmer_id, row)

    @app.delete("/api/farmers/{farmer_id}", dependencies=[Depends(need("farmers.manage"))])
    def remove_farmer(farmer_id: str):
        return services.delete_farmer(store, farmer_id)

    @app.post("/api/farmers/upload", dependencies=[Depends(need("farmers.manage"))])
    def upload(body: CsvIn):
        r = services.upload_farmers(store, settings, body.csv, body.campaign_id)
        services.recompute_forecast(store, settings)
        return r

    # The first two stay for older screens: they act on the crop in the body, or the default crop.
    @app.get("/api/calls/{call_id}/audio", dependencies=[Depends(need("calls.listen"))])
    def call_audio(call_id: str):
        """The recording of a call (stereo MP3: farmer left, agent right). Planners only; gone after the retention period."""
        call = store.get("calls", call_id)
        meta = (call or {}).get("audio")
        audio_store = make_audio_store(settings)
        if not meta or not audio_store:
            raise HTTPException(404, "There is no recording of this call.")
        expires = meta.get("expires_at")
        if expires and dt.datetime.fromisoformat(expires) < dt.datetime.now(dt.timezone.utc):
            raise HTTPException(410, "This recording was kept for %d days and has been deleted." % settings.call_audio_retention_days)
        data = audio_store.read(call_id)
        if data is None:
            raise HTTPException(404, "The recording file is missing.")
        return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"})

    @app.delete("/api/calls/{call_id}/audio")
    def call_audio_delete(call_id: str, actor=Depends(need("calls.listen"))):
        """Delete the recording of a call now (the transcript stays). Planners only."""
        call = store.get("calls", call_id)
        if not call or not call.get("audio"):
            raise HTTPException(404, "There is no recording of this call.")
        audio_store = make_audio_store(settings)
        if audio_store:
            audio_store.delete(call_id)
        store.set("calls", call_id, {"audio": None, "audio_deleted": {"by": getattr(actor, "name", None) or getattr(actor, "id", None),
                                                                        "at": services.now_iso()}}, merge=True)
        return {"ok": True}

    @app.post("/api/campaign/start", dependencies=[Depends(need("campaign.run"))])
    def campaign_start(body: CampaignIn):
        return services.start_campaign(store, settings, body.kind, body.crop or None, body.channel)

    @app.post("/api/campaign/stop", dependencies=[Depends(need("campaign.run"))])
    def campaign_stop(body: CampaignIn | None = None):
        return services.stop_campaign(store, settings, body.crop if body and body.crop else None)

    @app.post("/api/campaigns", dependencies=[Depends(need("campaign.run"))])
    def campaign_create(body: NewCampaignIn):
        return services.create_campaign(store, settings, body.crop, body.target_kg_per_week, body.weeks,
                                        body.name, body.farmer_ids, body.start_date, body.end_date,
                                        body.daily_capacity_kg, body.working_days, body.truck_kg)

    @app.put("/api/campaigns/{campaign_id}", dependencies=[Depends(need("campaign.run"))])
    def campaign_edit(campaign_id: str, body: CampaignEditIn):
        """Rename a campaign or change its weekly target or weeks to plan."""
        return services.update_campaign(store, settings, campaign_id, body.name, body.target_kg_per_week, body.weeks,
                                        body.start_date, body.end_date, body.daily_capacity_kg, body.working_days,
                                        body.truck_kg)

    @app.delete("/api/campaigns/{campaign_id}", dependencies=[Depends(need("campaign.run"))])
    def campaign_delete(campaign_id: str):
        return services.delete_campaign(store, settings, campaign_id)

    @app.put("/api/campaigns/{campaign_id}/farmers", dependencies=[Depends(need("farmers.manage"))])
    def campaign_farmers(campaign_id: str, body: CampaignFarmersIn):
        """Move farmers from the database into this campaign, or out of it."""
        return services.set_campaign_farmers(store, settings, campaign_id, body.add, body.remove)

    @app.put("/api/farmers/{farmer_id}/to-call", dependencies=[Depends(need("farmers.manage"))])
    def put_to_call(farmer_id: str, body: ToCallIn):
        """Mark a farmer to always get the harvest call (or not): the To call stage on the pipeline board."""
        if not store.get("farmers", farmer_id):
            raise HTTPException(404, "Farmer not found.")
        store.set("farmers", farmer_id, {"to_call": body.to_call}, merge=True)
        return {"farmer_id": farmer_id, "to_call": body.to_call}

    @app.post("/api/allowed-numbers")
    def post_allowed_number(body: AllowNumberIn, actor: auth.Actor = Depends(need("campaign.run"))):
        """Let real phone calls (and texts) reach this number."""
        return services.allow_number(store, settings, body.phone, body.label, body.farmer_id, actor)

    @app.delete("/api/allowed-numbers/{number_id}", dependencies=[Depends(need("campaign.run"))])
    def delete_allowed_number(number_id: str):
        return services.disallow_number(store, number_id)

    def _pdf(made: tuple[str, bytes]) -> Response:
        name, data = made
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/offers/{offer_id}/purchase-order.pdf")
    def offer_purchase_order(offer_id: str):
        """The purchase order of an approved deal, as a PDF."""
        return _pdf(purchase_order.for_offer(store, settings, offer_id))

    @app.get("/api/calls/{call_id}/purchase-order.pdf")
    def call_purchase_order(call_id: str):
        """The purchase order from a finished call: its approved deal, else a draft from the harvest it saved."""
        return _pdf(purchase_order.for_call(store, settings, call_id))

    @app.get("/api/deliveries/{delivery_id}/receipt.pdf")
    def delivery_receipt(delivery_id: str):
        """Goods receipt and payment for one delivery: gross, deductions, net, price and amount (PDF)."""
        return _pdf(purchase_order.for_delivery(store, settings, delivery_id))

    @app.get("/api/supply")
    def supply(period: str = "week", start: str = "", end: str = "", campaign: str = ""):
        """Expected supply, net deliveries, target and mill capacity by day, week, month or year."""
        a, b = mill_ops._day(start), mill_ops._day(end)
        if not a or not b:
            raise HTTPException(400, "Dates must look like 2026-10-19.")
        return mill_ops.supply_series(store, settings, campaign or None, period, a, b)

    @app.get("/api/surplus")
    def surplus(week: int, campaign: str = ""):
        """Farmers whose harvest falls in a week over the mill's capacity: the ones to ask to deliver later."""
        return {"farmers": mill_ops.surplus_farmers(store, settings, campaign or None, week)}

    @app.post("/api/farmers/{farmer_id}/reschedule")
    def reschedule(farmer_id: str, body: RescheduleIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Move a farmer's harvest later (agreed with them) when the mill is over capacity that week."""
        return mill_ops.reschedule_harvest(store, settings, farmer_id, body.to_date, body.reason, actor)

    @app.post("/api/official-prices")
    def post_official_price(body: OfficialPriceIn, actor: auth.Actor = Depends(need("limits.edit"))):
        """Record the published farmgate price (e.g. the provincial plantation office's TBS price)."""
        return mill_ops.add_official_price(store, settings, body.crop, body.province, body.valid_from, body.price_per_kg,
                                           body.source, body.url, actor)

    @app.delete("/api/official-prices/{price_id}", dependencies=[Depends(need("limits.edit"))])
    def delete_official_price(price_id: str):
        if not store.get("official_prices", price_id):
            raise HTTPException(404, "Price not found.")
        store.delete("official_prices", price_id)
        return {"deleted": price_id}

    @app.put("/api/limits/{crop}/follow-official", dependencies=[Depends(need("limits.edit"))])
    def put_follow_official(crop: str, body: FollowOfficialIn):
        """Let the crop's price range follow the latest official price (the floor and ceiling move with it)."""
        return mill_ops.follow_official(store, settings, crop, body.province, body.enabled)

    @app.get("/api/traceability")
    def traceability(campaign: str = ""):
        """How many of the campaign's farmers have a mapped, certified plot, and who delivers more than the plot grows."""
        return mill_ops.traceability_summary(store, settings, campaign or None)

    @app.get("/api/traceability.csv")
    def traceability_csv(campaign: str = ""):
        return PlainTextResponse(mill_ops.traceability_csv(store, settings, campaign or None), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=traceability.csv"})

    @app.get("/api/calendar")
    def calendar(start: str, end: str, campaign: str = ""):
        """Calls, harvests, deals, deliveries and planning weeks by day, for the calendar page."""
        try:
            a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            raise HTTPException(400, "Dates must look like 2026-10-19.") from None
        return calendar_view.events(store, settings, a, b, campaign or None)

    @app.post("/api/campaigns/{campaign_id}/start", dependencies=[Depends(need("campaign.run"))])
    def campaign_start_one(campaign_id: str, body: CampaignIn | None = None):
        return services.start_campaign(store, settings, body.kind if body else "collect", campaign_id,
                                       body.channel if body else "browser")

    @app.put("/api/campaigns/{campaign_id}/agent", dependencies=[Depends(need("campaign.run"))])
    def campaign_agent(campaign_id: str, body: AgentProfileIn):
        """The campaign's persona (name, voice, speaking style) and the planner's own questions."""
        return services.set_agent_profile(store, settings, campaign_id, body.persona, body.questions)

    @app.post("/api/calls/{call_id}/confirm-harvest")
    def confirm_harvest(call_id: str, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Save the harvest read back on a call that ended before the agent saved it."""
        return services.confirm_read_back(store, settings, call_id, actor.name)

    @app.put("/api/farmers/{farmer_id}/harvest")
    def put_harvest(farmer_id: str, body: HarvestIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Correct or add a farmer's harvest by hand (marked as edited; the call's values are kept)."""
        return services.edit_harvest(store, settings, farmer_id, body.kg, body.ready_date, body.confidence, actor,
                                     body.every_days)

    @app.delete("/api/farmers/{farmer_id}/harvest", dependencies=[Depends(need("farmers.manage"))])
    def remove_harvest(farmer_id: str):
        return services.delete_harvest(store, settings, farmer_id)

    @app.put("/api/calls/{call_id}/answers/{question_id}")
    def put_answer(call_id: str, question_id: str, body: AnswerIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Correct the answer to one of the planner's questions (the agent's version is kept)."""
        return services.edit_answer(store, call_id, question_id, body.answer, actor)

    @app.put("/api/campaigns/{campaign_id}/schedule", dependencies=[Depends(need("campaign.run"))])
    def campaign_schedule(campaign_id: str, body: ScheduleIn):
        """Start this campaign by itself every Monday morning (Cloud Scheduler calls /api/jobs/weekly)."""
        return services.set_weekly_schedule(store, settings, campaign_id, body.enabled, body.channel, body.days, body.time)

    def _job_auth(token: str | None) -> None:
        if not settings.job_token:
            raise HTTPException(404, "The scheduled job is not set up (JOB_TOKEN).")
        if not hmac.compare_digest(token or "", settings.job_token):
            raise HTTPException(403, "Wrong job token.")

    @app.post("/api/jobs/weekly", include_in_schema=False)
    def jobs_weekly(x_job_token: str | None = Header(default=None)):
        """Cloud Scheduler, every hour: the weekly bookkeeping once a week, and the campaigns due this hour."""
        _job_auth(x_job_token)
        return services.scheduled_calls(store, settings)

    @app.post("/api/jobs/run-all", include_in_schema=False)
    def jobs_run_all(x_job_token: str | None = Header(default=None)):
        """By hand: the weekly bookkeeping and every campaign with automatic calls, now."""
        _job_auth(x_job_token)
        return services.weekly_job(store, settings)

    @app.post("/api/offers/{offer_id}/send-confirmation", dependencies=[Depends(need("offers.decide"))])
    def send_confirmation(offer_id: str):
        """Send (again) the written copy of an approved deal to the farmer."""
        offer = store.get("offers", offer_id)
        if not offer or offer.get("status") != "approved":
            raise HTTPException(400, "Only an approved offer can be confirmed in writing.")
        return messaging.send_deal_confirmation(store, settings, offer)

    @app.get("/api/approvals/impact")
    def get_approval_impact(crop: str = "", campaign: str = ""):
        """What approving each waiting offer would do to the weeks, and what it costs."""
        return services.approval_impact(store, settings, campaign or crop or None)

    # ----- track record: deliveries against promises -----

    @app.get("/api/track-record")
    def get_track_record(crop: str = "", campaign: str = ""):
        """Forecast accuracy per week, reliability counts and the likely supply for the coming weeks."""
        return track_record.summary(store, settings, campaign or crop or None)

    @app.get("/api/farmers/{farmer_id}/track-record")
    def get_farmer_record(farmer_id: str):
        return track_record.farmer_record(store, farmer_id)

    @app.post("/api/deliveries")
    def post_delivery(body: DeliveryIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        return track_record.record_delivery(store, settings, body.farmer_id, body.kg, body.date, actor.name, "manual",
                                            {"unripe": body.unripe_pct, "dirt": body.dirt_pct, "other": body.other_pct})

    @app.post("/api/deliveries/upload")
    def upload_deliveries(body: CsvIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        return track_record.upload_deliveries(store, settings, body.csv, actor.name)

    @app.delete("/api/deliveries/{delivery_id}", dependencies=[Depends(need("farmers.manage"))])
    def delete_delivery(delivery_id: str):
        d = store.get("deliveries", delivery_id)
        if not d:
            raise HTTPException(404, "Delivery not found.")
        store.delete("deliveries", delivery_id)
        if d.get("offer_id") and store.get("offers", d["offer_id"]):
            o = store.get("offers", d["offer_id"])
            store.set("offers", d["offer_id"], {"delivered_kg": max(round(float(o.get("delivered_kg") or 0) - float(d.get("net_kg", d.get("kg", 0)))), 0)}, merge=True)
        return {"deleted": delivery_id}

    @app.get("/api/answers.csv")
    def answers_csv():
        return PlainTextResponse(services.answers_csv(store, settings), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=answers.csv"})

    @app.post("/api/campaigns/{campaign_id}/stop", dependencies=[Depends(need("campaign.run"))])
    def campaign_stop_one(campaign_id: str):
        return services.stop_campaign(store, settings, campaign_id)

    @app.post("/api/farmers/{farmer_id}/call", dependencies=[Depends(need("campaign.run"))])
    def farmer_call(farmer_id: str, body: CallNowIn | None = None):
        return {"call_id": services.call_now(store, farmer_id, body.kind if body else None, settings)}

    @app.post("/api/farmers/{farmer_id}/dial", dependencies=[Depends(need("campaign.run"))])
    def farmer_dial(farmer_id: str, body: DialIn | None = None):
        """VA-8: place a real outbound call over Twilio instead of waiting for a browser answer."""
        return {"call_id": services.dial_now(store, settings, farmer_id, body.kind if body else None)}

    @app.post("/api/offers/{offer_id}/approve")
    def approve(offer_id: str, actor: auth.Actor = Depends(need("offers.decide"))):
        return services.decide_offer(store, settings, offer_id, approve=True, actor=actor)

    @app.post("/api/offers/{offer_id}/reject")
    def reject(offer_id: str, actor: auth.Actor = Depends(need("offers.decide"))):
        return services.decide_offer(store, settings, offer_id, approve=False, actor=actor)

    @app.post("/api/offers/{offer_id}/undo", dependencies=[Depends(need("offers.decide"))])
    def undo(offer_id: str):
        return services.undo_offer(store, settings, offer_id)

    @app.post("/api/rival-quotes/{quote_id}/offer", dependencies=[Depends(need("offers.decide"))])
    def rival_offer(quote_id: str, body: RivalOfferIn | None = None):
        return services.offer_from_rival_quote(store, settings, quote_id, body.campaign_id if body else None)

    @app.post("/api/forecast/recompute", dependencies=[Depends(need("campaign.run"))])
    def recompute():
        return services.recompute_forecast(store, settings)

    @app.post("/api/demo/reset", dependencies=[Depends(need("demo.reset"))])
    def reset():
        seed_data.load_seed(store, settings)
        return {"ok": True}

    # ----- voice -----

    @app.websocket("/ws/call/{call_id}")
    async def call_ws(ws: WebSocket, call_id: str):
        await run_call(BrowserChannel(ws), store, settings, call_id, expected_channel="browser")

    # ----- Twilio (VA-8): the real phone leg -----

    async def twilio_form(request: Request, path: str) -> dict:
        """The webhook's form, after checking Twilio signed it. Fails closed."""
        if not services.twilio_ready(settings):
            raise HTTPException(404, "Twilio is not configured.")
        form = dict(await request.form())
        # Validate against the configured public URL, never the request Cloud Run
        # hands the app - Cloud Run terminates TLS and rewrites the host, so a
        # signature checked against request.url always fails behind it.
        from twilio.request_validator import RequestValidator

        full_url = f"{settings.public_base_url.rstrip('/')}{path}"
        signature = request.headers.get("X-Twilio-Signature", "")
        if not RequestValidator(settings.twilio_auth_token).validate(full_url, form, signature):
            raise HTTPException(403, "Invalid Twilio signature.")
        return form

    @app.post("/twilio/voice", include_in_schema=False)
    async def twilio_voice(request: Request, call_id: str):
        await twilio_form(request, f"/twilio/voice?call_id={call_id}")
        base = settings.public_base_url.rstrip("/")

        call = store.get("calls", call_id)
        if not call or call.get("status") != "queued" or call.get("channel") != "twilio":
            twiml = ("<?xml version='1.0' encoding='UTF-8'?><Response>"
                     "<Say>Sorry, this call could not be connected.</Say><Hangup/></Response>")
            return Response(content=twiml, media_type="text/xml")

        stream_url = f"{base}/twilio/stream/{call_id}".replace("https://", "wss://").replace("http://", "ws://")
        token = services.stream_token(settings, call_id)
        twiml = ('<?xml version="1.0" encoding="UTF-8"?>'
                 f'<Response><Connect><Stream url="{stream_url}">'
                 f'<Parameter name="token" value="{token}" />'
                 '</Stream></Connect></Response>')
        return Response(content=twiml, media_type="text/xml")

    @app.post("/twilio/status", include_in_schema=False)
    async def twilio_status(request: Request, call_id: str):
        form = await twilio_form(request, f"/twilio/status?call_id={call_id}")
        services.twilio_status(store, settings, call_id, str(form.get("CallStatus", "")))
        return Response(status_code=204)

    @app.websocket("/twilio/stream/{call_id}")
    async def twilio_stream(ws: WebSocket, call_id: str):
        if not services.twilio_ready(settings):
            await ws.close(code=1008)
            return
        channel = TwilioChannel(ws, expected_token=services.stream_token(settings, call_id))
        await run_call(channel, store, settings, call_id, expected_channel="twilio")

    if settings.static_dir:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="web")
    return app


_polish_cache: dict[str, str] = {}


def _polish(settings: Settings, text: str, instruction: str) -> str | None:
    """Ask Gemini to rewrite a template note. None when Gemini is not available."""
    if text in _polish_cache:
        return _polish_cache[text]
    try:
        from .live_session import genai_client

        client = genai_client()
        resp = client.models.generate_content(model=settings.text_model, contents=f"{instruction}\n\n{text}")
        out = (resp.text or "").strip() or None
    except Exception:  # noqa: BLE001 - no key or network: the template is fine
        return None
    if out:
        _polish_cache[text] = out
    return out


app = create_app()
