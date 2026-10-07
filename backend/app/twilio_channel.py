"""Twilio Media Streams channel: the real-phone leg (VA-8 stretch goal).

Twilio carries 8 kHz mono mu-law, base64-framed, over its own WebSocket message
protocol (connected/start/media/stop/mark). This adapts that to the same
Channel interface run_call() already talks to for the browser - see
live_session.Channel - so none of the negotiation/tool/retry code needed to
change to add this.

Twilio does not sign the Media Streams WebSocket handshake itself (only the
/twilio/voice webhook that sets it up); the call_id in the stream URL is an
unguessable id (store.new_id), and run_call() already refuses anything that
isn't the queued call it expects, which is enough for a hackathon demo.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging

from fastapi import WebSocket

from .audio_codec import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16

log = logging.getLogger(__name__)

TWILIO_RATE = 8000
GATEWAY_IN_RATE = 16000  # live_session.INPUT_MIME: what run_call sends to Gemini
GATEWAY_OUT_RATE = 24000  # what Gemini's audio comes back as


class TwilioChannel:
    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self.stream_sid: str | None = None
        self._started = asyncio.Event()

    async def accept(self) -> None:
        await self._ws.accept()

    async def recv(self) -> bytes | dict | None:
        msg = await self._ws.receive()
        if msg["type"] == "websocket.disconnect":
            return None
        text = msg.get("text")
        if text is None:
            return {}
        try:
            evt = json.loads(text)
        except ValueError:
            return {}
        kind = evt.get("event")
        if kind == "start":
            self.stream_sid = evt["start"]["streamSid"]
            self._started.set()
            return {}
        if kind == "media":
            mulaw = base64.b64decode(evt["media"]["payload"])
            pcm_8k = mulaw_to_pcm16(mulaw)
            return resample_pcm16(pcm_8k, TWILIO_RATE, GATEWAY_IN_RATE)
        if kind == "stop":
            return None
        return {}  # "connected", "mark": nothing to act on

    async def send_audio(self, pcm16: bytes) -> None:
        if not self.stream_sid:
            # Gemini's greeting can be ready before Twilio's "start" frame is processed
            # (no real risk in production - Twilio sends it immediately on connect,
            # well before a real network round trip to Gemini could return anything) -
            # wait for it rather than drop audio or race run_call's task bookkeeping.
            await self._started.wait()
        pcm_8k = resample_pcm16(pcm16, GATEWAY_OUT_RATE, TWILIO_RATE)
        payload = base64.b64encode(pcm16_to_mulaw(pcm_8k)).decode("ascii")
        await self._send({"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}})

    async def send_control(self, payload: dict) -> None:
        # The one run_call control message a phone leg must act on: flush
        # whatever Twilio already buffered when the farmer talks over the
        # agent. Twilio keeps playing queued audio until told to clear it.
        if payload.get("type") == "interrupted" and self.stream_sid:
            await self._send({"event": "clear", "streamSid": self.stream_sid})
        # Everything else (captions, tool events, connected/ended/error) has no
        # screen on a phone call; it's already in the transcript services.finish_call
        # saves, so nothing is lost by not sending it anywhere.

    async def _send(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send_text(json.dumps(payload))

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()
