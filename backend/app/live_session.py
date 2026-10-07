"""Voice gateway: relays browser audio to the Gemini Live API and runs tool calls.

Browser to gateway (WebSocket):
  binary frames   16 kHz mono PCM16 microphone audio
  {"type": "hangup"}
Gateway to browser:
  binary frames   24 kHz mono PCM16 agent audio
  {"type": "connected" | "caption" | "translation" | "interrupted" | "tool" | "ended" | "error", ...}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Awaitable, Callable

from fastapi import WebSocket
from google.genai import types

from . import forecast as fc
from . import services
from .config import Settings
from .prompt import KICKOFF, build_system_instruction
from .store import Store
from .tools import TOOL_DECLARATIONS, CallSession, ToolHandlers

log = logging.getLogger(__name__)

INPUT_MIME = "audio/pcm;rate=16000"
GOODBYE_GRACE_SECONDS = 10
WRAP_UP_NUDGE = ("(The call is close to its time limit. Summarise what was agreed, call end_call, "
                 "then say goodbye.)")

Translate = Callable[[str, str], Awaitable[str | None]]


class Transcript:
    """Speaker-labelled lines built from streaming transcription fragments."""

    def __init__(self) -> None:
        self.lines: list[dict] = []

    def add(self, who: str, text: str) -> tuple[int, int | None]:
        """Append a fragment. Returns (index of its line, index of a line that just closed or None)."""
        if self.lines and self.lines[-1]["who"] == who:
            self.lines[-1]["text"] += text
            return len(self.lines) - 1, None
        closed = len(self.lines) - 1 if self.lines else None
        self.lines.append({"who": who, "text": text.lstrip()})
        return len(self.lines) - 1, closed

    def cleaned(self) -> list[dict]:
        out = []
        for line in self.lines:
            text = " ".join(line["text"].split())
            if text:
                item = {"who": line["who"], "text": text}
                if line.get("translation"):
                    item["translation"] = line["translation"]
                out.append(item)
        return out


def build_live_config(settings: Settings, system_instruction: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_instruction,
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.voice_name))),
    )


def default_connect(model: str, config: types.LiveConnectConfig):
    from google import genai

    client = genai.Client()  # GOOGLE_API_KEY, or GOOGLE_GENAI_USE_VERTEXAI with project and location
    return client.aio.live.connect(model=model, config=config)


def make_translator(settings: Settings) -> Translate:
    client = None

    async def translate(text: str, target: str) -> str | None:
        nonlocal client
        try:
            if client is None:
                from google import genai
                client = genai.Client()
            resp = await client.aio.models.generate_content(
                model=settings.text_model,
                contents=f"Translate this phone-call line into {target}. Reply with the translation only.\n\n{text}")
            return (resp.text or "").strip() or None
        except Exception:  # noqa: BLE001 - captions without translation are still useful
            log.warning("caption translation failed", exc_info=True)
            return None

    return translate


def confirm_details(store: Store, settings: Settings, offer: dict | None) -> dict | None:
    if not offer:
        return None
    o = store.get("offers", offer["id"]) or offer
    dw = o.get("deliver_week")
    return {"kg": o["kg"], "crop": o["crop"], "price_per_kg": o["price_per_kg"],
            "currency": o.get("currency", "IDR"), "deliver_week": dw,
            "deliver_start": fc.week_start(dw, settings.plan_start).isoformat() if dw else None,
            "from_week": o.get("from_week"), "decided_by": o.get("decided_by")}


async def run_call(ws: WebSocket, store: Store, settings: Settings, call_id: str,
                   connect: Callable[[str, types.LiveConnectConfig], Any] | None = None,
                   translate: Translate | None = None) -> None:
    await ws.accept()
    call = store.get("calls", call_id)
    if not call or call.get("status") != "queued":
        await ws.send_json({"type": "error", "message": "This call is not waiting to be answered."})
        await ws.close()
        return
    farmer = store.get("farmers", call["farmer_id"])
    if not farmer:
        await ws.send_json({"type": "error", "message": "Farmer not found."})
        await ws.close()
        return

    offer = store.get("offers", call["offer_id"]) if call.get("offer_id") else None
    harvest = store.get("harvests", f"h-{farmer['id']}-{farmer.get('crop', '')}")
    session = CallSession(call_id=call_id, farmer=farmer, kind=call["kind"],
                          gap_week=call.get("gap_week"), offer=offer)
    handlers = ToolHandlers(store, settings, session)
    transcript = Transcript()
    instruction = build_system_instruction(settings, farmer, call["kind"], call.get("gap_week"),
                                           harvest=harvest, offer=offer)
    store.set("calls", call_id, {"status": "on_call", "started_at": services.now_iso()}, merge=True)
    connect = connect or default_connect
    language = (farmer.get("language") or settings.demo_language or "").lower()
    target = settings.caption_translate_to
    if target and target.lower() in language:
        target = None  # captions are already in the target language
    translate = translate or (make_translator(settings) if target else None)
    pending_translations: set[asyncio.Task] = set()

    async def send(payload: dict) -> None:
        with contextlib.suppress(Exception):
            await ws.send_json(payload)

    async def translate_line(index: int) -> None:
        text = " ".join(transcript.lines[index]["text"].split())
        if not text or not translate or not target:
            return
        result = await translate(text, target)
        if result:
            transcript.lines[index]["translation"] = result
            await send({"type": "translation", "index": index, "text": result})

    def close_line(index: int | None) -> None:
        if index is None or not target or transcript.lines[index].get("queued"):
            return
        transcript.lines[index]["queued"] = True
        task = asyncio.create_task(translate_line(index))
        pending_translations.add(task)
        task.add_done_callback(pending_translations.discard)

    async def caption(who: str, text: str) -> None:
        index, closed = transcript.add(who, text)
        close_line(closed)
        await send({"type": "caption", "who": who, "text": text, "index": index})

    try:
        async with connect(settings.live_model, build_live_config(settings, instruction)) as live:
            await send({"type": "connected", "farmer": farmer.get("name"), "village": farmer.get("village"),
                        "language": farmer.get("language"), "kind": call["kind"],
                        "mill": settings.mill_name, "gap_week": call.get("gap_week")})
            await live.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=KICKOFF)]), turn_complete=True)

            async def upstream() -> None:
                while True:
                    msg = await ws.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("bytes"):
                        await live.send_realtime_input(audio=types.Blob(data=msg["bytes"], mime_type=INPUT_MIME))
                    elif msg.get("text"):
                        with contextlib.suppress(ValueError):
                            if json.loads(msg["text"]).get("type") == "hangup":
                                return

            async def downstream() -> None:
                spoke_after_end = False
                while True:
                    async for msg in live.receive():
                        if msg.tool_call:
                            responses = []
                            for fn in msg.tool_call.function_calls or []:
                                result = handlers.dispatch(fn.name, fn.args)
                                await send({"type": "tool", "name": fn.name, "args": fn.args or {},
                                            "result": result, "ui": handlers.last_ui})
                                responses.append(types.FunctionResponse(id=fn.id, name=fn.name, response=result))
                            await live.send_tool_response(function_responses=responses)
                        sc = msg.server_content
                        if not sc:
                            continue
                        if sc.interrupted:
                            await send({"type": "interrupted"})
                        if sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    if session.ended:
                                        spoke_after_end = True
                                    with contextlib.suppress(Exception):
                                        await ws.send_bytes(part.inline_data.data)
                        if sc.input_transcription and sc.input_transcription.text:
                            await caption("farmer", sc.input_transcription.text)
                        if sc.output_transcription and sc.output_transcription.text:
                            await caption("agent", sc.output_transcription.text)
                        if sc.turn_complete:
                            if transcript.lines and transcript.lines[-1]["who"] == "agent":
                                close_line(len(transcript.lines) - 1)
                            if session.ended and spoke_after_end:
                                return

            async def goodbye_watchdog() -> None:
                while not session.ended:
                    await asyncio.sleep(0.2)
                await asyncio.sleep(GOODBYE_GRACE_SECONDS)

            async def time_limit() -> None:
                await asyncio.sleep(max(settings.max_call_seconds - 45, 1))
                if not session.ended:
                    await live.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=WRAP_UP_NUDGE)]),
                        turn_complete=True)
                await asyncio.sleep(75)
                if not session.ended:
                    session.ended, session.outcome = True, "completed"
                    session.summary = session.summary or "Call reached the time limit."

            tasks = {asyncio.create_task(t()) for t in (upstream, downstream, goodbye_watchdog, time_limit)}
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                if t.exception():
                    raise t.exception()
    except Exception as e:  # noqa: BLE001 - report any relay failure to the caller and keep data
        log.exception("call %s failed", call_id)
        await send({"type": "error", "message": f"Voice session failed: {e}"})
    finally:
        if transcript.lines:
            close_line(len(transcript.lines) - 1)
        if pending_translations:
            with contextlib.suppress(Exception):
                await asyncio.wait(pending_translations, timeout=4)
        services.finish_call(store, settings, call_id, ended_cleanly=session.ended,
                             outcome=session.outcome, summary=session.summary,
                             consent=session.consent, transcript=transcript.cleaned())
        final = store.get("calls", call_id) or {}
        await send({"type": "ended", "status": final.get("status"), "summary": final.get("summary"),
                    "kind": call["kind"], "consent": final.get("consent"),
                    "retry_queued": bool(final.get("retry_queued")),
                    "deal": confirm_details(store, settings, offer) if call["kind"] == "confirm" else None})
        with contextlib.suppress(Exception):
            await ws.close()
