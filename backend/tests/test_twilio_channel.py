import asyncio
import base64
import json

from app.audio_codec import pcm16_to_mulaw
from app.twilio_channel import TwilioChannel


class FakeTwilioWs:
    """Stands in for a FastAPI WebSocket carrying Twilio's own message shapes."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def receive(self):
        return self._incoming.pop(0)

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        self.closed = True


def text_msg(payload: dict) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def run(coro):
    return asyncio.run(coro)


def test_start_event_captures_stream_sid_and_yields_no_audio():
    ws = FakeTwilioWs([text_msg({"event": "start", "start": {"streamSid": "MZ123"}})])
    ch = TwilioChannel(ws)

    async def go():
        await ch.accept()
        return await ch.recv()

    assert run(go()) == {}
    assert ws.accepted
    assert ch.stream_sid == "MZ123"


def test_media_event_decodes_mulaw_to_16k_pcm16():
    # One mu-law byte -> 8kHz PCM16 (1 sample) -> resampled to 16kHz (~2 samples).
    mulaw_byte = pcm16_to_mulaw(b"\x00\x00")
    payload = base64.b64encode(mulaw_byte).decode()
    ws = FakeTwilioWs([text_msg({"event": "media", "media": {"payload": payload}})])
    out = run(TwilioChannel(ws).recv())
    assert isinstance(out, bytes) and len(out) == 4  # 2 samples * 2 bytes, 16kHz


def test_stop_event_and_disconnect_both_end_the_call():
    ws = FakeTwilioWs([text_msg({"event": "stop"})])
    assert run(TwilioChannel(ws).recv()) is None

    ws2 = FakeTwilioWs([{"type": "websocket.disconnect"}])
    assert run(TwilioChannel(ws2).recv()) is None


def test_send_audio_resamples_to_8k_mulaw_and_wraps_as_media_event():
    ws = FakeTwilioWs([])
    ch = TwilioChannel(ws)
    ch.stream_sid = "MZ123"
    pcm_24k = b"\x00\x00" * 48  # 48 samples at 24kHz -> 16 samples at 8kHz
    run(ch.send_audio(pcm_24k))
    assert len(ws.sent) == 1
    evt = ws.sent[0]
    assert evt["event"] == "media" and evt["streamSid"] == "MZ123"
    decoded_mulaw = base64.b64decode(evt["media"]["payload"])
    assert len(decoded_mulaw) == 16


def test_send_audio_before_start_waits_for_it_instead_of_racing():
    ws = FakeTwilioWs([text_msg({"event": "start", "start": {"streamSid": "MZ123"}})])
    ch = TwilioChannel(ws)

    async def go():
        # If send_audio ran to completion without "start" ever arriving, this would
        # hang - asyncio.gather proves it only proceeds once recv() processes "start".
        await asyncio.wait_for(asyncio.gather(ch.send_audio(b"\x00\x00" * 10), ch.recv()), timeout=1)

    run(go())
    assert len(ws.sent) == 1 and ws.sent[0]["event"] == "media"


def test_interrupted_control_sends_twilio_clear_event():
    ws = FakeTwilioWs([])
    ch = TwilioChannel(ws)
    ch.stream_sid = "MZ123"
    run(ch.send_control({"type": "interrupted"}))
    assert ws.sent == [{"event": "clear", "streamSid": "MZ123"}]


def test_other_control_messages_are_not_sent_to_twilio():
    ws = FakeTwilioWs([])
    ch = TwilioChannel(ws)
    ch.stream_sid = "MZ123"
    run(ch.send_control({"type": "caption", "who": "agent", "text": "hello"}))
    run(ch.send_control({"type": "ended", "status": "done"}))
    assert ws.sent == []


def test_close_closes_the_underlying_socket():
    ws = FakeTwilioWs([])
    run(TwilioChannel(ws).close())
    assert ws.closed
