"""HTTP and WebSocket entry point (Cloud Run service)."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import access, agent_profile, auth, seed_data, services
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


class CsvIn(BaseModel):
    csv: str


class CampaignIn(BaseModel):
    kind: str = "collect"
    crop: str = ""  # empty: the default crop
    channel: str = "browser"  # "twilio": real phone calls, dialled one at a time


class NewCampaignIn(BaseModel):
    crop: str
    target_kg_per_week: float
    weeks: int


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


class AnswerIn(BaseModel):
    answer: str


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
                            "phone_calls_note": services.phone_calls_note(settings),
                            "agent_options": agent_profile.options()}
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
    def forecast_csv(crop: str = ""):
        return PlainTextResponse(services.forecast_csv(store, crop or None), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=forecast.csv"})

    @app.get("/api/forecast/summary")
    async def forecast_summary(crop: str = ""):
        """Plain summary plus the gap note; Gemini rewrites the note when a key is configured."""
        text = services.forecast_summary_text(store, settings, crop or None)
        gap = services.first_gap_week(store, crop or services.default_crop(settings))
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

    @app.post("/api/farmers", dependencies=[Depends(need("farmers.manage"))])
    def add_farmer(body: FarmerIn):
        row = body.model_dump()
        row["can_pull_forward"] = "yes" if row["can_pull_forward"] else ""
        return {"id": services.add_farmer(store, row)}

    @app.put("/api/farmers/{farmer_id}", dependencies=[Depends(need("farmers.manage"))])
    def edit_farmer(farmer_id: str, body: FarmerIn):
        row = body.model_dump()
        row["can_pull_forward"] = "yes" if row["can_pull_forward"] else ""
        return services.update_farmer(store, farmer_id, row)

    @app.delete("/api/farmers/{farmer_id}", dependencies=[Depends(need("farmers.manage"))])
    def remove_farmer(farmer_id: str):
        return services.delete_farmer(store, farmer_id)

    @app.post("/api/farmers/upload", dependencies=[Depends(need("farmers.manage"))])
    def upload(body: CsvIn):
        return services.upload_farmers(store, settings, body.csv)

    # The first two stay for older screens: they act on the crop in the body, or the default crop.
    @app.post("/api/campaign/start", dependencies=[Depends(need("campaign.run"))])
    def campaign_start(body: CampaignIn):
        return services.start_campaign(store, settings, body.kind, body.crop or None, body.channel)

    @app.post("/api/campaign/stop", dependencies=[Depends(need("campaign.run"))])
    def campaign_stop(body: CampaignIn | None = None):
        return services.stop_campaign(store, settings, body.crop if body and body.crop else None)

    @app.post("/api/campaigns", dependencies=[Depends(need("campaign.run"))])
    def campaign_create(body: NewCampaignIn):
        return services.create_campaign(store, settings, body.crop, body.target_kg_per_week, body.weeks)

    @app.post("/api/campaigns/{campaign_id}/start", dependencies=[Depends(need("campaign.run"))])
    def campaign_start_one(campaign_id: str, body: CampaignIn | None = None):
        crop = services.crop_of_campaign_id(settings, campaign_id)
        return services.start_campaign(store, settings, body.kind if body else "collect", crop,
                                       body.channel if body else "browser")

    @app.put("/api/campaigns/{campaign_id}/agent", dependencies=[Depends(need("campaign.run"))])
    def campaign_agent(campaign_id: str, body: AgentProfileIn):
        """The campaign's persona (name, voice, speaking style) and the planner's own questions."""
        crop = services.crop_of_campaign_id(settings, campaign_id)
        return services.set_agent_profile(store, settings, crop, body.persona, body.questions)

    @app.post("/api/calls/{call_id}/confirm-harvest")
    def confirm_harvest(call_id: str, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Save the harvest read back on a call that ended before the agent saved it."""
        return services.confirm_read_back(store, settings, call_id, actor.name)

    @app.put("/api/farmers/{farmer_id}/harvest")
    def put_harvest(farmer_id: str, body: HarvestIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Correct or add a farmer's harvest by hand (marked as edited; the call's values are kept)."""
        return services.edit_harvest(store, settings, farmer_id, body.kg, body.ready_date, body.confidence, actor)

    @app.delete("/api/farmers/{farmer_id}/harvest", dependencies=[Depends(need("farmers.manage"))])
    def remove_harvest(farmer_id: str):
        return services.delete_harvest(store, settings, farmer_id)

    @app.put("/api/calls/{call_id}/answers/{question_id}")
    def put_answer(call_id: str, question_id: str, body: AnswerIn, actor: auth.Actor = Depends(need("farmers.manage"))):
        """Correct the answer to one of the planner's questions (the agent's version is kept)."""
        return services.edit_answer(store, call_id, question_id, body.answer, actor)

    @app.get("/api/answers.csv")
    def answers_csv():
        return PlainTextResponse(services.answers_csv(store, settings), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=answers.csv"})

    @app.post("/api/campaigns/{campaign_id}/stop", dependencies=[Depends(need("campaign.run"))])
    def campaign_stop_one(campaign_id: str):
        return services.stop_campaign(store, settings, services.crop_of_campaign_id(settings, campaign_id))

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
    def rival_offer(quote_id: str):
        return services.offer_from_rival_quote(store, settings, quote_id)

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
