import asyncio
import contextlib
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app import live_session, main
from app.main import create_app


@pytest.fixture
def client(settings, store, monkeypatch):
    monkeypatch.setattr(main, "_polish", lambda *a, **k: None)  # no Gemini in tests
    app = create_app(settings, store)
    with TestClient(app) as c:
        yield c


def test_health_state_and_config(client):
    assert client.get("/healthz").json()["ok"]
    state = client.get("/api/state").json()
    assert {"farmers", "forecast", "offers", "limits", "calls", "settings"} <= state.keys()
    assert state["settings"]["planner_name"] == "Dewi"
    cfg = client.get("/config.js").text
    assert "Koperasi Sawit Maju" in cfg and '"plannerName": "Dewi"' in cfg


def test_summary_includes_gap_note(client):
    r = client.get("/api/forecast/summary").json()
    assert r["gap_week"] == 3 and r["gap_note_by"] == "template"
    assert r["gap_note"].startswith("31 farmers moved delivery to week 4")


def test_limits_validation(client, store):
    bad = client.put("/api/limits/palm", json={"floor_price": 3400, "ceiling_price": 3350, "reference_price": 3100})
    assert bad.status_code == 400
    ok = client.put("/api/limits/sawit", json={"floor_price": 2950, "ceiling_price": 3400, "reference_price": 3150})
    doc = store.get("limits", "palm")
    assert ok.status_code == 200 and doc["ceiling_price"] == 3400 and doc["currency"] == "IDR"
    assert doc["reference_source"]  # kept across edits


def test_campaign_queues_calls(client, store):
    r = client.post("/api/campaign/start", json={"kind": "collect"}).json()
    assert r["queued"] == 12 and r["gap_week"] == 3
    assert client.post("/api/campaign/start", json={"kind": "collect"}).json()["queued"] == 0
    gap = client.post("/api/campaign/start", json={"kind": "gap_fill"}).json()
    assert gap["queued"] == 16  # fifteen pull-forward farmers and the rival supplier
    assert client.post("/api/campaign/stop").json()["status"] == "stopped"


def test_rival_quote_approve_and_undo(client, store):
    r = client.post("/api/rival-quotes/rq01/offer")
    offer_id = r.json()["id"]
    assert client.post("/api/rival-quotes/rq01/offer").status_code == 400
    assert store.get("forecast", "W3")["pending_kg"] == 12_000
    a = client.post(f"/api/offers/{offer_id}/approve").json()
    assert a["status"] == "approved"
    assert store.get("offers", offer_id)["decided_by"] == "Dewi"
    assert store.get("forecast", "W3")["expected_kg"] == 73_000
    confirm = [c for c in store.list("calls") if c["kind"] == "confirm"]
    assert len(confirm) == 1 and confirm[0]["offer_id"] == offer_id
    assert client.post(f"/api/offers/{offer_id}/reject").status_code == 400

    undo = client.post(f"/api/offers/{offer_id}/undo").json()
    assert undo["status"] == "pending"
    assert store.get("forecast", "W3")["expected_kg"] == 61_000
    assert not [c for c in store.list("calls") if c["kind"] == "confirm"]  # queued confirmation withdrawn
    assert client.post(f"/api/offers/{offer_id}/undo").status_code == 400


def test_undo_refused_after_voice_confirmation(client, store):
    offer_id = client.post("/api/rival-quotes/rq01/offer").json()["id"]
    client.post(f"/api/offers/{offer_id}/approve")
    store.set("offers", offer_id, {"confirmed_by_voice": True}, merge=True)
    assert client.post(f"/api/offers/{offer_id}/undo").status_code == 400


def test_upload_farmers(client, store):
    csv = "name,phone,crop,language,village\nPak Test,+62 812 0000 7777,Kelapa Sawit,Bahasa Indonesia,Lirik\n"
    assert client.post("/api/farmers/upload", json={"csv": csv}).json()["added"] == 1
    assert any(f["name"] == "Pak Test" and f["crop"] == "palm" for f in store.list("farmers"))
    assert client.post("/api/farmers/upload", json={"csv": "a,b\n1,2"}).status_code == 400


def test_planner_token(settings, store):
    app = create_app(dataclasses.replace(settings, planner_token="s3cret"), store)
    with TestClient(app) as c:
        assert c.post("/api/campaign/stop").status_code == 401
        assert c.post("/api/campaign/stop", headers={"X-Planner-Token": "s3cret"}).status_code == 200


def test_csv_download(client):
    r = client.get("/api/forecast.csv")
    assert r.status_code == 200 and r.text.startswith("week,")


# ---------- voice gateway with a fake Live session ----------

def fn_call(name, args, cid):
    return types.LiveServerMessage(tool_call=types.LiveServerToolCall(
        function_calls=[types.FunctionCall(id=cid, name=name, args=args)]))


def content(**kw):
    return types.LiveServerMessage(server_content=types.LiveServerContent(**kw))


def audio():
    return content(model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"\0\0" * 10, mime_type="audio/pcm"))]))


class FakeLive:
    """Plays a scripted gap-fill call from the design: offer 3,220, counter 3,300, save, end."""

    def __init__(self):
        self.tool_responses = []
        self.turns = [
            [content(output_transcription=types.Transcription(text="Selamat siang, saya asisten AI ")),
             content(output_transcription=types.Transcription(text="dari Koperasi Sawit Maju.")),
             audio(), content(turn_complete=True)],
            [content(input_transcription=types.Transcription(text="Bisa, 1.600 kg.")),
             fn_call("get_reference_price", {"crop": "sawit"}, "0"),
             fn_call("check_offer", {"crop": "palm", "kg": 1600}, "1")],
            [content(input_transcription=types.Transcription(text="Kalau Rp 3.300 bisa?")),
             fn_call("check_offer", {"crop": "palm", "kg": 1600, "farmer_counter_price": 3300}, "2")],
            [fn_call("save_offer", {"crop": "palm", "kg": 1600, "price_per_kg": 3300}, "3")],
            [fn_call("end_call", {"outcome": "completed", "summary": "1.6 t pulled into W3 at 3,300.",
                                  "transcript_consent": True}, "4")],
            [audio(), content(turn_complete=True)],
        ]

    async def send_client_content(self, **kw):
        pass

    async def send_realtime_input(self, **kw):
        pass

    async def send_tool_response(self, function_responses):
        self.tool_responses.extend(function_responses)

    async def receive(self):
        if not self.turns:
            await asyncio.sleep(3600)
        for msg in self.turns.pop(0):
            yield msg


def drain(ws):
    events, audio_frames = [], 0
    while True:
        msg = ws.receive()
        if msg.get("bytes"):
            audio_frames += 1
            continue
        if msg.get("text") is None:
            break
        evt = json.loads(msg["text"])
        events.append(evt)
        if evt["type"] == "ended":
            break
    return events, audio_frames


@pytest.fixture
def fake_voice(monkeypatch):
    fake = FakeLive()

    @contextlib.asynccontextmanager
    async def fake_connect(model, config):
        assert config.system_instruction and config.tools
        yield fake

    async def fake_translate(text, target):
        return f"[{target}] {text}"

    monkeypatch.setattr(live_session, "default_connect", fake_connect)
    monkeypatch.setattr(live_session, "make_translator", lambda settings: fake_translate)
    return fake


def test_voice_call_end_to_end(client, store, fake_voice):
    call_id = client.post("/api/farmers/b001/call", json={"kind": "gap_fill"}).json()["call_id"]
    with client.websocket_connect(f"/ws/call/{call_id}") as ws:
        ws.send_bytes(b"\1\0" * 160)
        events, audio_frames = drain(ws)

    kinds = [e["type"] for e in events]
    assert kinds[0] == "connected" and kinds[-1] == "ended" and audio_frames >= 1
    assert events[0]["language"] == "Bahasa Indonesia"
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["name"] for t in tools] == ["get_reference_price", "check_offer", "check_offer", "save_offer", "end_call"]
    assert tools[2]["result"]["decision"] == "accept"
    assert tools[2]["ui"]["rail"]["counter"] == 3300 and tools[2]["ui"]["rail"]["ceiling"] == 3350
    assert "3350" not in json.dumps(tools[2]["result"])

    captions = [e for e in events if e["type"] == "caption"]
    assert captions[0]["index"] == captions[1]["index"] == 0  # fragments of one line
    translations = [e for e in events if e["type"] == "translation"]
    assert translations and translations[0]["text"].startswith("[English] Selamat siang")

    call = store.get("calls", call_id)
    assert call["status"] == "done" and call["consent"] is True
    assert call["transcript"][0]["who"] == "agent" and call["transcript"][0]["translation"]
    offers = store.list("offers")
    assert len(offers) == 1 and offers[0]["price_per_kg"] == 3300 and offers[0]["status"] == "pending"


def test_confirmation_call_marks_offer_and_reports_deal(client, store, fake_voice):
    offer_id = client.post("/api/rival-quotes/rq01/offer").json()["id"]
    client.post(f"/api/offers/{offer_id}/approve")
    call_id = next(c["id"] for c in store.list("calls") if c["kind"] == "confirm")
    fake_voice.turns = [
        [content(output_transcription=types.Transcription(text="Koperasi sudah menyetujui.")), audio(),
         content(turn_complete=True)],
        [fn_call("end_call", {"outcome": "completed", "summary": "Deal confirmed.", "transcript_consent": False}, "1")],
        [audio(), content(turn_complete=True)],
    ]
    with client.websocket_connect(f"/ws/call/{call_id}") as ws:
        events, _ = drain(ws)
    ended = events[-1]
    assert ended["kind"] == "confirm" and ended["deal"]["kg"] == 12_000 and ended["deal"]["decided_by"] == "Dewi"
    assert store.get("offers", offer_id)["confirmed_by_voice"] is True
    assert store.get("calls", call_id)["transcript"] is None  # no consent, no transcript


def test_dropped_call_retries_once(client, store, monkeypatch):
    @contextlib.asynccontextmanager
    async def broken_connect(model, config):
        raise RuntimeError("no network")
        yield  # pragma: no cover

    monkeypatch.setattr(live_session, "default_connect", broken_connect)
    call_id = client.post("/api/farmers/f01/call", json={}).json()["call_id"]
    with client.websocket_connect(f"/ws/call/{call_id}") as ws:
        events, _ = drain(ws)
    assert "error" in [e["type"] for e in events] and events[-1]["retry_queued"] is True
    assert store.get("calls", call_id)["status"] == "dropped"
    retries = [c for c in store.list("calls") if c["farmer_id"] == "f01" and c["status"] == "queued"]
    assert len(retries) == 1 and retries[0]["attempt"] == 2
    with client.websocket_connect(f"/ws/call/{retries[0]['id']}") as ws:
        events, _ = drain(ws)
    assert events[-1]["retry_queued"] is False
    assert not [c for c in store.list("calls") if c["farmer_id"] == "f01" and c["status"] == "queued"]
