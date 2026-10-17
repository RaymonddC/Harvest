"""The agent on WhatsApp: the same harvest conversation as a phone call, written instead of spoken.

A WhatsApp chat is a call on the "whatsapp" channel (collection `calls`), so the Calls page, the farmer's timeline,
the campaign rules and finish_call treat it like any other call. The agent is the same: the same tools
(tools.ToolHandlers, with the read-back, the price limits and save_offer enforced in code) and the same stages,
with the chat's own persona and consent notice (prompt.CHAT_PERSONA, prompt.CHAT_NOTICES).

How a chat runs:
- open_chat (a planner, or a WhatsApp campaign) sends the opening: who is writing (an AI), for which mill, and the
  consent question. The farmer can also write first: an unknown chat starts on their message.
- Each farmer message arrives on the signed Twilio webhook (/twilio/whatsapp) and gets one agent turn (agent_reply):
  Gemini with the tools, the answer sent back as the webhook's reply. Text, voice notes and photos are understood.
- The chat ends when the agent calls end_call, or after CHAT_IDLE_HOURS without a message (close_stale_chats).

Real WhatsApp messages only go out when Twilio and TWILIO_WHATSAPP_FROM are set and the farmer's number is on the
real-call allowlist, as with calls. Otherwise the chat still runs in the dashboard ("demo chat"): the planner types
the farmer's replies there (reply_as_farmer), which is also how the demo works without a phone.

WhatsApp only lets a business start a chat with an approved template. Set TWILIO_WHATSAPP_OPENING_SID to the Content
SID of an approved template whose text is the opening (variables {{1}} the farmer's name, {{2}} the mill); without it
the opening is sent as plain text, which WhatsApp delivers only inside 24 hours of the farmer's last message (or in
the Twilio sandbox).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging

from google.genai import types

from . import agent_profile, services
from .config import Settings, normalize_phone
from .prompt import build_system_instruction, chat_notice_for, chat_opening
from .store import Store
from .tools import TOOL_DECLARATIONS, CallSession, ToolHandlers

log = logging.getLogger(__name__)

CHANNEL = "whatsapp"
CHAT_IDLE_HOURS = 24  # a chat with no message for this long ends as "no reply"
MAX_TOOL_ROUNDS = 8  # tool calls the model may make before it must answer
MAX_MEDIA_BYTES = 5_000_000
SORRY = "Sorry, something went wrong on our side. Please try again in a moment."
MEDIA_KINDS = ("audio/", "image/")

_locks: dict[str, asyncio.Lock] = {}


def _now() -> str:
    return services.now_iso()


def _chat_lock(call_id: str) -> asyncio.Lock:
    # Two messages sent in quick succession are answered one after the other, never in parallel.
    return _locks.setdefault(call_id, asyncio.Lock())


# ---------- when real WhatsApp messages may go out ----------

def whatsapp_ready(settings: Settings) -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from)


def why_not_live(store: Store, settings: Settings, farmer: dict) -> str | None:
    """Why this farmer's chat cannot go over real WhatsApp (it then runs as a demo chat), or None."""
    if not whatsapp_ready(settings):
        return "WhatsApp is not set up (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM)."
    phone = normalize_phone(farmer.get("phone") or "")
    if len(phone) < 8:
        return "This farmer has no phone number on record."
    if not services.number_allowed(store, settings, phone):
        return f"{phone} is not on the allowlist."
    return None


def note(settings: Settings) -> str:
    if not whatsapp_ready(settings):
        return "WhatsApp is not set up: chats run here in the dashboard, and you type the farmer's replies."
    if not settings.public_base_url:
        return "WhatsApp can send, but PUBLIC_BASE_URL is not set, so farmers' replies cannot reach the agent."
    return "WhatsApp chats go to numbers on the allowlist; other farmers' chats run here in the dashboard."


def _send(settings: Settings, to: str, body: str, opening_for: dict | None = None) -> str | None:
    """Send one WhatsApp message over Twilio. Returns the message SID. opening_for: send the approved opening
    template (TWILIO_WHATSAPP_OPENING_SID) with these variables instead of free text, when one is set."""
    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    args = {"from_": f"whatsapp:{settings.twilio_whatsapp_from}", "to": f"whatsapp:{to}"}
    if opening_for and settings.twilio_whatsapp_opening_sid:
        args.update(content_sid=settings.twilio_whatsapp_opening_sid, content_variables=json.dumps(opening_for))
    else:
        args["body"] = body
    msg = client.messages.create(**args)
    return getattr(msg, "sid", None)


def recent_messages(settings: Settings, limit: int = 10) -> list[dict]:
    """The sender's latest WhatsApp messages as Twilio sees them: direction, status and error code (to find out why
    one was not delivered). Phone numbers are masked."""
    if not whatsapp_ready(settings):
        raise services.ServiceError(note(settings))
    from twilio.rest import Client

    client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    me = f"whatsapp:{normalize_phone(settings.twilio_whatsapp_from)}"
    mask = lambda n: (n or "")[:-7] + "•••" + (n or "")[-4:]  # noqa: E731
    out = []
    for m in [*client.messages.list(from_=me, limit=limit), *client.messages.list(to=me, limit=limit)]:
        out.append({"sid": m.sid, "at": m.date_created.isoformat() if m.date_created else None,
                    "direction": m.direction, "status": m.status, "error_code": m.error_code,
                    "error_message": m.error_message, "to": mask(m.to), "from": mask(m.from_),
                    "body": (m.body or "")[:60]})
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)[:limit]


SENDERS_URL = "https://messaging.twilio.com/v2/Channels/Senders"


def connect_webhook(settings: Settings, http=None) -> dict:
    """Point the WhatsApp sender's incoming-message webhook at this service (/twilio/whatsapp), with the service's
    own Twilio credentials, so nobody has to paste the URL into the Twilio console. Reports what it found and did."""
    if not whatsapp_ready(settings):
        raise services.ServiceError(note(settings))
    if not settings.public_base_url:
        raise services.ServiceError("PUBLIC_BASE_URL is not set, so there is no address to give Twilio.")
    import httpx

    http = http or httpx.Client(auth=(settings.twilio_account_sid, settings.twilio_auth_token), timeout=20)
    url = f"{settings.public_base_url.rstrip('/')}/twilio/whatsapp"
    sender_id = f"whatsapp:{normalize_phone(settings.twilio_whatsapp_from)}"
    r = http.get(SENDERS_URL, params={"Channel": "whatsapp", "PageSize": 50})
    if r.status_code >= 400:
        raise services.ServiceError(f"Twilio would not list the WhatsApp senders ({r.status_code}): {r.text[:200]}")
    senders = r.json().get("senders") or []
    sender = next((s for s in senders if s.get("sender_id") == sender_id), None)
    if not sender:
        found = ", ".join(s.get("sender_id", "?") for s in senders) or "none"
        raise services.ServiceError(f"{sender_id} is not a WhatsApp sender on this Twilio account (senders: {found}). "
                                    "Register it in Twilio under Messaging > Senders > WhatsApp senders.")
    body = {"webhook": {"callback_url": url, "callback_method": "POST"}}
    u = http.post(f"{SENDERS_URL}/{sender['sid']}", json=body)
    if u.status_code in (404, 405):
        u = http.put(f"{SENDERS_URL}/{sender['sid']}", json=body)
    if u.status_code >= 400:
        raise services.ServiceError(f"Twilio did not take the webhook ({u.status_code}): {u.text[:200]}")
    return {"sender": sender_id, "status": sender.get("status"), "webhook": url}


# ---------- the chat's state, kept on the call between messages ----------

def session_state(s: CallSession) -> dict:
    """What a CallSession learned during the chat, in a form the store keeps (Firestore takes no nested lists)."""
    return {
        "rung_index": dict(s.rung_index), "quoted_prices": {k: sorted(v) for k, v in s.quoted_prices.items()},
        "first_offer": dict(s.first_offer), "last_counter": dict(s.last_counter),
        "ended": s.ended, "outcome": s.outcome, "summary": s.summary, "consent": s.consent,
        "saved_offer_ids": list(s.saved_offer_ids), "answers": dict(s.answers),
        "read_back": {k: {"kg": kg, "date": d} for k, (kg, d) in s.read_back.items()},
        "end_refused": s.end_refused, "saved_kg": dict(s.saved_kg),
        "price_warned": [f"{c}|{n}" for c, n in s.price_warned],
    }


def restore_session(call: dict, farmer: dict, offer: dict | None, questions: list[dict]) -> CallSession:
    s = CallSession(call_id=call["id"], farmer=farmer, kind=call["kind"], gap_week=call.get("gap_week"),
                    offer=offer, questions=questions)
    st = call.get("chat_state") or {}
    s.rung_index = dict(st.get("rung_index") or {})
    s.quoted_prices = {k: set(v) for k, v in (st.get("quoted_prices") or {}).items()}
    s.first_offer = dict(st.get("first_offer") or {})
    s.last_counter = dict(st.get("last_counter") or {})
    s.ended = bool(st.get("ended"))
    s.outcome, s.summary, s.consent = st.get("outcome"), st.get("summary"), st.get("consent")
    s.saved_offer_ids = list(st.get("saved_offer_ids") or [])
    s.answers = dict(st.get("answers") or call.get("answers") or {})
    s.read_back = {k: (v["kg"], v["date"]) for k, v in (st.get("read_back") or {}).items()}
    s.end_refused = bool(st.get("end_refused"))
    s.saved_kg = dict(st.get("saved_kg") or {})
    s.price_warned = {(c, float(n)) for c, n in (x.split("|", 1) for x in st.get("price_warned") or [])}
    return s


def _load_contents(call: dict) -> list[types.Content]:
    raw = call.get("chat_contents")
    if not raw:
        return []
    return [types.Content.model_validate_json(json.dumps(c)) for c in json.loads(raw)]


def _dump_contents(contents: list[types.Content]) -> str:
    # One JSON string: the model's turns hold nested lists and bytes (thought signatures) the store cannot keep as is.
    return json.dumps([json.loads(c.model_dump_json(exclude_none=True)) for c in contents])


def _context(store: Store, settings: Settings, call: dict) -> tuple[dict, dict | None, dict | None, Settings, list[dict]]:
    farmer = store.get("farmers", call["farmer_id"])
    if not farmer:
        raise services.ServiceError("Farmer not found.")
    offer = store.get("offers", call["offer_id"]) if call.get("offer_id") else None
    campaign = ((services.resolve_campaign(store, settings, call["campaign_id"]) if call.get("campaign_id") else None)
                or services.campaign_of_farmer(store, settings, farmer))
    camp_settings = services.settings_for_campaign(settings, campaign or {})
    questions = list((campaign or {}).get("questions") or []) if call["kind"] == "collect" else []
    return farmer, offer, campaign, camp_settings, questions


# ---------- starting and ending ----------

def open_chat_for(store: Store, farmer_id: str) -> dict | None:
    return next((c for c in store.list("calls") if c["farmer_id"] == farmer_id and c.get("channel") == CHANNEL
                 and c["status"] in ("queued", "on_call")), None)


def open_chat(store: Store, settings: Settings, farmer_id: str, kind: str | None = None,
              campaign_id: str | None = None) -> dict:
    """Start a WhatsApp chat with a farmer: send the opening (or, in demo mode, show it in the dashboard)."""
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise services.ServiceError("Farmer not found.")
    if farmer.get("do_not_call"):
        raise services.ServiceError("This farmer asked not to be contacted again.")
    if open_chat_for(store, farmer_id):
        raise services.ServiceError(f"{farmer.get('name', 'This farmer')} already has a WhatsApp chat open.")
    camp = (services.resolve_campaign(store, settings, campaign_id) if campaign_id else None) \
        or services.campaign_of_farmer(store, settings, farmer)
    gap = services.first_gap_week(store, camp["id"]) if camp else None
    kind = kind or "collect"
    call_id = services.queue_call(store, farmer, kind, gap_week=gap["week"] if gap else None, channel=CHANNEL,
                                  campaign_id=camp["id"] if camp else None)
    camp_settings = services.settings_for_campaign(settings, camp or {})
    persona = agent_profile.profile_of(camp)["persona"]
    language = agent_profile.call_language(persona, farmer.get("language"), camp_settings.demo_language)
    notice = chat_notice_for(language, settings.mill_name, farmer.get("name") or "", agent=persona.get("name", ""))
    text = chat_opening(notice)
    reason = why_not_live(store, settings, farmer)
    sid = None
    if reason is None:
        try:
            sid = _send(settings, normalize_phone(farmer["phone"]), text,
                        opening_for={"1": farmer.get("name") or "", "2": settings.mill_name})
        except Exception as e:  # noqa: BLE001
            store.delete("calls", call_id)
            raise services.ServiceError(f"WhatsApp did not accept the message: {str(e)[:200]}") from None
    now = _now()
    contents = [types.Content(role="user", parts=[types.Part(text="(The chat has started.)")]),
                types.Content(role="model", parts=[types.Part(text=text)])]
    store.set("calls", call_id, {
        "status": "on_call", "started_at": now, "last_message_at": now, "language": language,
        "whatsapp_live": reason is None, "whatsapp_note": reason,
        "chat": [{"who": "agent", "text": text, "at": now, **({"sid": sid} if sid else {})}],
        "chat_opening": text, "chat_contents": _dump_contents(contents), "chat_state": {},
    }, merge=True)
    return {"call_id": call_id, "live": reason is None, "note": reason, "opening": text}


def _start_from_farmer(store: Store, settings: Settings, farmer: dict) -> dict:
    """The farmer wrote first: a harvest chat starts on their message (the agent's first reply opens it)."""
    camp = services.campaign_of_farmer(store, settings, farmer)
    gap = services.first_gap_week(store, camp["id"]) if camp else None
    call_id = services.queue_call(store, farmer, "collect", gap_week=gap["week"] if gap else None, channel=CHANNEL,
                                  campaign_id=camp["id"] if camp else None)
    now = _now()
    store.set("calls", call_id, {"status": "on_call", "started_at": now, "last_message_at": now, "whatsapp_live": True,
                                 "whatsapp_note": None, "chat": [], "chat_opening": None, "chat_contents": None,
                                 "chat_state": {}, "farmer_started": True}, merge=True)
    return store.get("calls", call_id)


def finish_chat(store: Store, settings: Settings, call_id: str, session: CallSession | None = None,
                outcome: str | None = None, summary: str | None = None) -> None:
    """End the chat like a call: status, outcome and summary; the transcript only when the farmer agreed."""
    call = store.get("calls", call_id)
    if not call or call["status"] not in ("queued", "on_call"):
        return
    lines = [{"who": m["who"], "text": m["text"]} for m in call.get("chat") or [] if m.get("text")]
    consent = session.consent if session else (call.get("chat_state") or {}).get("consent")
    services.finish_call(store, settings, call_id, ended_cleanly=bool(session and session.ended),
                         outcome=outcome or (session.outcome if session else None),
                         summary=summary or (session.summary if session else None),
                         consent=consent, transcript=lines)
    # The working copy of the chat goes; what is kept is the transcript above, and only with consent.
    store.set("calls", call_id, {"chat": lines if consent else None, "chat_contents": None, "chat_state": None},
              merge=True)


def close_stale_chats(store: Store, settings: Settings, now: dt.datetime | None = None) -> int:
    """End chats nobody has written in for CHAT_IDLE_HOURS (outcome "no_reply"). Run by the hourly job."""
    now = now or dt.datetime.now(dt.timezone.utc)
    closed = 0
    for call in store.list("calls"):
        if call.get("channel") != CHANNEL or call["status"] not in ("queued", "on_call"):
            continue
        last = call.get("last_message_at") or call.get("started_at") or call.get("created_at")
        try:
            idle = now - dt.datetime.fromisoformat(last)
        except (TypeError, ValueError):
            continue
        if idle >= dt.timedelta(hours=CHAT_IDLE_HOURS):
            finish_chat(store, settings, call["id"], outcome="no_reply",
                        summary=f"No reply on WhatsApp for {CHAT_IDLE_HOURS} hours.")
            closed += 1
    return closed


# ---------- one agent turn ----------

# Text models tried when TEXT_MODEL is not available to the project (Google retires names, and Vertex and AI Studio
# do not offer the same ones); then the newest "flash" model the project lists is used.
FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash-001")
SKIP_IN_NAME = ("image", "tts", "audio", "live", "lite", "embedding", "thinking", "exp")
_model_in_use: str | None = None


def _is_not_found(e: Exception) -> bool:
    return getattr(e, "code", None) == 404 or "NOT_FOUND" in str(e)


async def _listed_flash_models(client) -> list[str]:
    names = []
    try:
        pager = await client.aio.models.list(config={"query_base": True, "page_size": 200})
        async for m in pager:
            name = (m.name or "").rsplit("/", 1)[-1]
            if name.startswith("gemini") and "flash" in name and not any(w in name for w in SKIP_IN_NAME):
                names.append(name)
    except Exception:  # noqa: BLE001
        log.warning("whatsapp: could not list the project's models", exc_info=True)
    return sorted(set(names), reverse=True)  # newest version first ("gemini-3..." before "gemini-2...")


def _generate(settings: Settings):
    from .live_session import genai_client

    client = genai_client()

    async def call(model: str, contents: list[types.Content], instruction: str):
        return await client.aio.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=instruction, tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))

    async def generate(contents: list[types.Content], instruction: str):
        global _model_in_use
        first = _model_in_use or settings.text_model
        try:
            return await call(first, contents, instruction)
        except Exception as e:  # noqa: BLE001
            if not _is_not_found(e):
                raise
            log.warning("whatsapp: text model %s is not available to this project; looking for another", first)
        tried = {first}
        for model in [*FALLBACK_MODELS, *await _listed_flash_models(client)]:
            if model in tried:
                continue
            tried.add(model)
            try:
                resp = await call(model, contents, instruction)
            except Exception as e:  # noqa: BLE001
                if _is_not_found(e):
                    continue
                raise
            _model_in_use = model
            log.warning("whatsapp: using text model %s (set TEXT_MODEL to it to skip this search)", model)
            return resp
        raise services.ServiceError(f"No Gemini text model is available to this project (tried {', '.join(sorted(tried))}).")

    return generate


def _text_of(resp) -> str:
    content = resp.candidates[0].content if resp.candidates else None
    parts = (content.parts if content else None) or []
    return " ".join(p.text.strip() for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()


async def agent_reply(store: Store, settings: Settings, call_id: str, text: str = "",
                      media: list[tuple[bytes, str]] | None = None, generate=None) -> str | None:
    """Give the farmer's message to the agent and return its answer (None when the chat is closed).
    media: (bytes, mime type) of voice notes and photos sent with the message."""
    async with _chat_lock(call_id):
        call = store.get("calls", call_id)
        if not call or call.get("channel") != CHANNEL or call["status"] not in ("queued", "on_call"):
            return None
        farmer, offer, campaign, camp_settings, questions = _context(store, settings, call)
        session = restore_session(call, farmer, offer, questions)
        handlers = ToolHandlers(store, camp_settings, session)
        harvest = store.get("harvests", f"h-{farmer['id']}-{farmer.get('crop', '')}")
        instruction = build_system_instruction(camp_settings, farmer, call["kind"], call.get("gap_week"),
                                               harvest=harvest, offer=offer, campaign=campaign,
                                               chat_opening_sent=call.get("chat_opening"), chat=True)
        contents = _load_contents(call)
        parts = [types.Part(text=text)] if text else []
        parts += [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in media or []]
        if not parts:
            return None
        contents.append(types.Content(role="user", parts=parts))
        reply = ""
        try:
            generate = generate or _generate(settings)
            for _ in range(MAX_TOOL_ROUNDS):
                resp = await generate(contents, instruction)
                content = resp.candidates[0].content if resp.candidates else None
                if content is not None:
                    contents.append(content)
                calls = [p.function_call for p in (content.parts if content else None) or [] if p.function_call]
                if not calls:
                    reply = _text_of(resp)
                    break
                responses = []
                for fn in calls:
                    result = handlers.dispatch(fn.name, dict(fn.args or {}))
                    responses.append(types.Part(function_response=types.FunctionResponse(
                        id=fn.id, name=fn.name, response=result)))
                contents.append(types.Content(role="user", parts=responses))
        except Exception:  # noqa: BLE001 - the farmer gets a short note; the chat stays open for the next message
            log.exception("whatsapp chat %s: the agent turn failed", call_id)
            reply = SORRY
            contents = contents[:-1] if contents and contents[-1].role == "user" else contents
        # Voice notes and photos are not kept: the agent has answered them, and its answer stays in the chat.
        for c in contents:
            if c.role == "user" and any(p.inline_data for p in c.parts or []):
                c.parts = [p if not p.inline_data else types.Part(text=f"({_media_word(p.inline_data.mime_type)})")
                           for p in c.parts]
        now = _now()
        lines = list(call.get("chat") or [])
        if text or media:
            shown = text or ""
            if media:
                shown = " ".join(filter(None, [f"[{_media_word(m)}]" for _, m in media] + [shown]))
            lines.append({"who": "farmer", "text": shown, "at": now})
        if reply:
            lines.append({"who": "agent", "text": reply, "at": now})
        store.set("calls", call_id, {"chat": lines, "chat_contents": _dump_contents(contents),
                                     "chat_state": session_state(session), "last_message_at": now,
                                     "answers": dict(session.answers), "consent": session.consent}, merge=True)
        if session.ended:
            finish_chat(store, settings, call_id, session)
        return reply or None


def _media_word(mime: str | None) -> str:
    return "voice note" if (mime or "").startswith("audio/") else "photo"


# ---------- messages from farmers ----------

def farmer_by_phone(store: Store, phone: str) -> dict | None:
    e164 = normalize_phone(phone)
    return next((f for f in store.list("farmers") if f.get("phone") and normalize_phone(f["phone"]) == e164), None)


def _download_media(settings: Settings, url: str) -> bytes | None:
    import httpx

    try:  # Twilio's media URLs need the account's credentials and redirect to the file
        r = httpx.get(url, auth=(settings.twilio_account_sid, settings.twilio_auth_token), follow_redirects=True,
                      timeout=15)
        r.raise_for_status()
        return r.content if len(r.content) <= MAX_MEDIA_BYTES else None
    except Exception:  # noqa: BLE001
        log.warning("whatsapp: could not download media %s", url, exc_info=True)
        return None


async def handle_incoming(store: Store, settings: Settings, form: dict) -> str | None:
    """One message from Twilio's WhatsApp webhook. Returns the agent's answer (None: no answer is sent).
    Only farmers on file whose number is on the allowlist get an answer; anyone else is ignored."""
    sender = str(form.get("From", "")).removeprefix("whatsapp:")
    farmer = farmer_by_phone(store, sender)
    if not farmer:
        log.info("whatsapp: message from a number that is not a farmer on file; ignored")
        return None
    if why_not_live(store, settings, farmer):
        log.info("whatsapp: message from %s, whose number is not allowed; ignored", farmer["id"])
        return None
    close_stale_chats(store, settings)
    call = open_chat_for(store, farmer["id"])
    sid = str(form.get("MessageSid", ""))
    if call and sid and sid in (call.get("seen_sids") or []):
        return None  # Twilio sent the same message twice
    if not call:
        if farmer.get("do_not_call"):
            return None
        call = _start_from_farmer(store, settings, farmer)
    if sid:
        store.set("calls", call["id"], {"seen_sids": [*(call.get("seen_sids") or [])[-19:], sid]}, merge=True)
    media = []
    for i in range(min(int(form.get("NumMedia") or 0), 3)):
        mime = str(form.get(f"MediaContentType{i}", ""))
        url = str(form.get(f"MediaUrl{i}", ""))
        if url and mime.startswith(MEDIA_KINDS):
            data = await asyncio.to_thread(_download_media, settings, url)
            if data:
                media.append((data, mime.split(";")[0]))
    reply = await agent_reply(store, settings, call["id"], str(form.get("Body", "")).strip(), media)
    if not reply:
        return None
    try:
        sid = await asyncio.to_thread(_send, settings, normalize_phone(farmer["phone"]), reply)
        _note_sid(store, call["id"], sid)
    except Exception:  # noqa: BLE001 - the reply is in the chat; the dashboard shows it was not sent
        log.exception("whatsapp chat %s: Twilio did not take the reply", call["id"])
    return None


def _note_sid(store: Store, call_id: str, sid: str | None) -> None:
    """Mark the newest agent line with the Twilio SID it went out with."""
    call = store.get("calls", call_id) or {}
    lines = list(call.get("chat") or [])
    for line in reversed(lines):
        if line.get("who") == "agent":
            line["sid"] = sid
            break
    target = "chat" if call.get("status") in ("queued", "on_call") else ("transcript" if call.get("transcript") else None)
    if target == "chat":
        store.set("calls", call_id, {"chat": lines}, merge=True)


async def reply_as_farmer(store: Store, settings: Settings, call_id: str, text: str, generate=None) -> str | None:
    """The dashboard's demo chat: the planner types what the farmer would write."""
    call = store.get("calls", call_id)
    if not call or call.get("channel") != CHANNEL:
        raise services.ServiceError("WhatsApp chat not found.")
    if call["status"] not in ("queued", "on_call"):
        raise services.ServiceError("This chat has ended.")
    if call.get("whatsapp_live"):
        raise services.ServiceError("This chat is on real WhatsApp: the farmer answers from their phone.")
    text = " ".join((text or "").split())
    if not text:
        raise services.ServiceError("Write the farmer's message first.")
    return await agent_reply(store, settings, call_id, text[:1000], generate=generate)
