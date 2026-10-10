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

from . import auth, seed_data, services
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


class LoginIn(BaseModel):
    role: str


class CallNowIn(BaseModel):
    kind: str | None = None


class DialIn(BaseModel):
    kind: str | None = None


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or make_store(settings.store_backend, settings.gcp_project)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.seed_on_start:
            seed_data.load_seed(store, settings)
            log.info("Seeded demo data; plan starts %s", settings.plan_start)
        yield

    app = FastAPI(title="Harvest-Call Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                       allow_headers=["*"])

    planner = auth.planner_dependency(settings)

    @app.exception_handler(services.ServiceError)
    async def service_error(_: Request, exc: services.ServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ----- health and config -----

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "store": settings.store_backend, "model": settings.live_model}

    @app.get("/config.js", include_in_schema=False)
    def config_js():
        cfg = {"apiBase": "", "millName": settings.mill_name, "plannerName": settings.planner_name,
               "firebase": json.loads(settings.firebase_web_config) if settings.firebase_web_config else None}
        return Response(f"window.HARVEST_CONFIG = {json.dumps(cfg)};", media_type="application/javascript")

    # ----- demo sign-in: pick a role, no password -----

    @app.post("/api/auth/login")
    def login(body: LoginIn):
        if body.role not in auth.ROLES:
            raise HTTPException(400, f"Role must be one of: {', '.join(auth.ROLES)}.")
        token, exp = auth.mint_token(settings, body.role)
        return {"token": token, "role": body.role, "name": auth.display_name(settings, body.role), "exp": exp}

    @app.get("/api/auth/me")
    def me(authorization: str | None = Header(default=None)):
        claims = auth.read_token(settings, authorization)
        return {"role": claims["role"], "name": claims.get("name"), "exp": claims["exp"]}

    # ----- read model -----

    def snapshot() -> dict:
        data = {c: store.list(c) for c in COLLECTIONS}
        data["settings"] = {"mill_name": settings.mill_name, "planner_name": settings.planner_name,
                            "language": settings.demo_language, "max_call_seconds": settings.max_call_seconds,
                            "max_call_attempts": settings.max_call_attempts,
                            "plan_start": settings.plan_start.isoformat(),
                            "weeks": settings.weeks, "target_kg_per_week": settings.target_kg_per_week,
                            "gap_tolerance": settings.gap_tolerance}
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
    def forecast_csv():
        return PlainTextResponse(services.forecast_csv(store), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=forecast.csv"})

    @app.get("/api/forecast/summary")
    async def forecast_summary():
        """Plain summary plus the gap note; Gemini rewrites the note when a key is configured."""
        text = services.forecast_summary_text(store, settings)
        gap = services.first_gap_week(store)
        note, by = (None, None)
        if gap and gap.get("note"):
            polished = await asyncio.to_thread(
                _polish, settings, gap["note"],
                f"Rewrite this note for a mill planner explaining why week {gap['week']} is short of supply, "
                "in one plain sentence. Keep every number exactly as given.")
            note, by = (polished, "gemini") if polished else (gap["note"], "template")
        return {"summary": text, "gap_week": gap["week"] if gap else None, "gap_note": note, "gap_note_by": by}

    # ----- planner actions (client writes to Firestore are blocked; everything goes through here) -----

    @app.put("/api/limits/{crop}", dependencies=[Depends(planner)])
    def put_limits(crop: str, body: LimitsIn):
        doc = services.set_limits(store, crop, body.floor_price, body.ceiling_price, body.reference_price,
                                  body.first_premium_pct, body.step_pct)
        services.recompute_forecast(store, settings)
        return doc

    @app.post("/api/farmers", dependencies=[Depends(planner)])
    def add_farmer(body: FarmerIn):
        row = body.model_dump()
        row["can_pull_forward"] = "yes" if row["can_pull_forward"] else ""
        return {"id": services.add_farmer(store, row)}

    @app.post("/api/farmers/upload", dependencies=[Depends(planner)])
    def upload(body: CsvIn):
        return services.upload_farmers(store, settings, body.csv)

    @app.post("/api/campaign/start", dependencies=[Depends(planner)])
    def campaign_start(body: CampaignIn):
        return services.start_campaign(store, settings, body.kind)

    @app.post("/api/campaign/stop", dependencies=[Depends(planner)])
    def campaign_stop():
        return services.stop_campaign(store)

    @app.post("/api/farmers/{farmer_id}/call", dependencies=[Depends(planner)])
    def farmer_call(farmer_id: str, body: CallNowIn | None = None):
        return {"call_id": services.call_now(store, farmer_id, body.kind if body else None)}

    @app.post("/api/farmers/{farmer_id}/dial", dependencies=[Depends(planner)])
    def farmer_dial(farmer_id: str, body: DialIn | None = None):
        """VA-8: place a real outbound call over Twilio instead of waiting for a browser answer."""
        return {"call_id": services.dial_now(store, settings, farmer_id, body.kind if body else None)}

    @app.post("/api/offers/{offer_id}/approve", dependencies=[Depends(planner)])
    def approve(offer_id: str):
        return services.decide_offer(store, settings, offer_id, approve=True)

    @app.post("/api/offers/{offer_id}/reject", dependencies=[Depends(planner)])
    def reject(offer_id: str):
        return services.decide_offer(store, settings, offer_id, approve=False)

    @app.post("/api/offers/{offer_id}/undo", dependencies=[Depends(planner)])
    def undo(offer_id: str):
        return services.undo_offer(store, settings, offer_id)

    @app.post("/api/rival-quotes/{quote_id}/offer", dependencies=[Depends(planner)])
    def rival_offer(quote_id: str):
        return services.offer_from_rival_quote(store, settings, quote_id)

    @app.post("/api/forecast/recompute", dependencies=[Depends(planner)])
    def recompute():
        return services.recompute_forecast(store, settings)

    @app.post("/api/demo/reset", dependencies=[Depends(planner)])
    def reset():
        seed_data.load_seed(store, settings)
        return {"ok": True}

    # ----- voice -----

    @app.websocket("/ws/call/{call_id}")
    async def call_ws(ws: WebSocket, call_id: str):
        await run_call(BrowserChannel(ws), store, settings, call_id, expected_channel="browser")

    # ----- Twilio (VA-8): the real phone leg -----

    @app.post("/twilio/voice", include_in_schema=False)
    async def twilio_voice(request: Request, call_id: str):
        if not services.twilio_ready(settings):
            raise HTTPException(404, "Twilio is not configured.")
        form = await request.form()
        base = settings.public_base_url.rstrip("/")
        full_url = f"{base}/twilio/voice?call_id={call_id}"
        # Validate against the configured public URL, never the request Cloud Run
        # hands the app - Cloud Run terminates TLS and rewrites the host, so a
        # signature checked against request.url always fails behind it.
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(settings.twilio_auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(full_url, dict(form), signature):
            raise HTTPException(403, "Invalid Twilio signature.")

        call = store.get("calls", call_id)
        if not call or call.get("status") != "queued" or call.get("channel") != "twilio":
            twiml = ("<?xml version='1.0' encoding='UTF-8'?><Response>"
                     "<Say>Sorry, this call could not be connected.</Say><Hangup/></Response>")
            return Response(content=twiml, media_type="text/xml")

        stream_url = f"{base}/twilio/stream/{call_id}".replace("https://", "wss://").replace("http://", "ws://")
        twiml = ('<?xml version="1.0" encoding="UTF-8"?>'
                 f'<Response><Connect><Stream url="{stream_url}" /></Connect></Response>')
        return Response(content=twiml, media_type="text/xml")

    @app.websocket("/twilio/stream/{call_id}")
    async def twilio_stream(ws: WebSocket, call_id: str):
        await run_call(TwilioChannel(ws), store, settings, call_id, expected_channel="twilio")

    if settings.static_dir:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="web")
    return app


_polish_cache: dict[str, str] = {}


def _polish(settings: Settings, text: str, instruction: str) -> str | None:
    """Ask Gemini to rewrite a template note. None when Gemini is not available."""
    if text in _polish_cache:
        return _polish_cache[text]
    try:
        from google import genai

        client = genai.Client()
        resp = client.models.generate_content(model=settings.text_model, contents=f"{instruction}\n\n{text}")
        out = (resp.text or "").strip() or None
    except Exception:  # noqa: BLE001 - no key or network: the template is fine
        return None
    if out:
        _polish_cache[text] = out
    return out


app = create_app()
