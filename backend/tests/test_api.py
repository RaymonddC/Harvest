import asyncio
import contextlib
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app import live_session, main, services
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


def test_upload_reports_skipped_lines_and_keeps_good_ones(client, store):
    csv = ("name,phone,crop,language,usual_kg_week\n"
           "Pak Baik,+62 812 0000 8888,karet,Bahasa Indonesia,300\n"
           "Pak Salah,+62 812 0000 9999,tomato,Bahasa Indonesia,10\n"
           "Ibu Pendek,123,palm,Bahasa Indonesia,10\n")
    r = client.post("/api/farmers/upload", json={"csv": csv}).json()
    assert r["added"] == 1 and len(r["skipped"]) == 2
    assert "Line 3" in r["skipped"][0] and "tomato" in r["skipped"][0]
    assert any(f["name"] == "Pak Baik" and f["crop"] == "rubber" and f["usual_kg_week"] == 300
               for f in store.list("farmers"))


def test_add_farmer_validates_and_does_not_duplicate(client, store):
    body = {"name": "Ibu Baru", "phone": "+62 812 0000 1234", "crop": "coffee",
            "language": "Bahasa Indonesia", "village": "Dumai", "usual_kg_week": 120}
    fid = client.post("/api/farmers", json=body).json()["id"]
    assert store.get("farmers", fid)["crop"] == "coffee" and store.get("farmers", fid)["to_call"] is True
    client.post("/api/farmers", json={**body, "name": "Ibu Baru 2"})  # same phone: update, not a duplicate
    assert [f["name"] for f in store.list("farmers") if f["phone"] == body["phone"]] == ["Ibu Baru 2"]
    assert client.post("/api/farmers", json={**body, "crop": "tomato"}).status_code == 400
    assert client.post("/api/farmers", json={**body, "phone": "12"}).status_code == 400
    assert client.post("/api/farmers", json={"name": "X"}).status_code == 400


def test_edit_farmer_keeps_id_and_call_flags(client, store):
    fid = client.post("/api/farmers", json={"name": "Pak Lama", "phone": "+62 812 0000 4321", "crop": "palm",
                                            "language": "Bahasa Indonesia"}).json()["id"]
    store.set("farmers", fid, {"do_not_call": True}, merge=True)
    r = client.put(f"/api/farmers/{fid}", json={"name": "Pak Baru", "phone": "+62 812 0000 4321",
                                                "crop": "karet", "language": "Bahasa Indonesia", "usual_kg_week": 50})
    assert r.status_code == 200
    saved = store.get("farmers", fid)
    assert saved["name"] == "Pak Baru" and saved["crop"] == "rubber" and saved["usual_kg_week"] == 50
    assert saved["do_not_call"] is True and saved["to_call"] is True
    assert client.put(f"/api/farmers/{fid}", json={"name": "X"}).status_code == 400
    assert client.put("/api/farmers/nope", json={"name": "A", "phone": "+62 812 0000 4321", "crop": "palm",
                                                 "language": "Bahasa Indonesia"}).status_code == 400


def test_delete_farmer_withdraws_waiting_calls_but_keeps_history(client, store):
    fid = client.post("/api/farmers", json={"name": "Pak Hapus", "phone": "+62 812 0000 9876", "crop": "palm",
                                            "language": "Bahasa Indonesia"}).json()["id"]
    waiting = client.post(f"/api/farmers/{fid}/call", json={}).json()["call_id"]
    store.set("calls", "done-1", {"id": "done-1", "farmer_id": fid, "status": "done", "kind": "collect"})
    r = client.delete(f"/api/farmers/{fid}").json()
    assert r["calls_withdrawn"] == 1
    assert store.get("farmers", fid) is None and store.get("calls", waiting) is None
    assert store.get("calls", "done-1") is not None
    assert client.delete(f"/api/farmers/{fid}").status_code == 400


def test_cannot_delete_a_farmer_who_is_on_a_call(client, store):
    fid = client.post("/api/farmers", json={"name": "Pak Sibuk", "phone": "+62 812 0000 5555", "crop": "palm",
                                            "language": "Bahasa Indonesia"}).json()["id"]
    store.set("calls", "live-1", {"id": "live-1", "farmer_id": fid, "status": "on_call", "kind": "collect"})
    assert client.delete(f"/api/farmers/{fid}").status_code == 400
    assert store.get("farmers", fid) is not None


def test_language_must_be_one_of_the_supported_list(client, store):
    body = {"name": "Pak Bahasa", "phone": "+62 812 0000 7001", "crop": "palm", "language": "Indonesian"}
    fid = client.post("/api/farmers", json=body).json()["id"]
    assert store.get("farmers", fid)["language"] == "Bahasa Indonesia"  # alias is normalised
    r = client.post("/api/farmers", json={**body, "phone": "+62 812 0000 7002", "language": "Klingon"})
    assert r.status_code == 400 and "Unknown language" in r.json()["detail"]


def test_setup_page_language_options_match_the_backend():
    import re
    from pathlib import Path
    html = (Path(__file__).resolve().parents[2] / "web/setup.html").read_text()
    block = re.search(r'<select name="language"[^>]*>(.*?)</select>', html, re.S).group(1)
    assert tuple(re.findall(r"<option>(.*?)</option>", block)) == services.LANGUAGES


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


def twilio_settings(settings, **extra):
    return dataclasses.replace(settings, twilio_account_sid="AC_test", twilio_auth_token="test-token",
                               twilio_from_number="+15550000000", public_base_url="https://gw.example.test",
                               **extra)


def allowlisted_settings(store, settings, farmer_id="f01", **extra):
    from app.config import normalize_phone

    phone = store.get("farmers", farmer_id)["phone"]
    return twilio_settings(settings, real_calls_enabled=True,
                           real_call_allowlist=(normalize_phone(phone),), **extra)


def test_dial_now_requires_twilio_config(store, settings):
    with pytest.raises(services.ServiceError):
        services.dial_now(store, settings, "f01")


def test_dial_now_refuses_when_real_calls_are_disabled(store, settings):
    # twilio_settings() alone leaves real_calls_enabled at its default (off).
    with pytest.raises(services.ServiceError, match="turned off"):
        services.dial_now(store, twilio_settings(settings), "f01")


def test_dial_now_refuses_a_number_not_on_the_allowlist(store, settings):
    s = twilio_settings(settings, real_calls_enabled=True, real_call_allowlist=("+10000000000",))
    with pytest.raises(services.ServiceError, match="allowlist"):
        services.dial_now(store, s, "f01")


def test_dial_now_wildcard_allowlist_allows_any_number(store, settings, monkeypatch):
    # REAL_CALL_ALLOWLIST=* (same convention as CORS_ORIGINS): production, not a
    # specific test number - any farmer's number is allowed through.
    monkeypatch.setattr("twilio.rest.Client", type("FakeClient", (), {
        "__init__": lambda self, sid, token: setattr(self, "calls", type("C", (), {
            "create": lambda self, **kw: type("R", (), {"sid": "CA_fake"})()})())}))
    s = twilio_settings(settings, real_calls_enabled=True, real_call_allowlist=("*",))
    call_id = services.dial_now(store, s, "f01")
    assert store.get("calls", call_id)["channel"] == "twilio"


def test_dial_now_refuses_do_not_call_farmer(store, settings):
    store.set("farmers", "f01", {"do_not_call": True}, merge=True)
    with pytest.raises(services.ServiceError, match="asked not to be called"):
        services.dial_now(store, allowlisted_settings(store, settings), "f01")


def test_dial_now_places_a_twilio_call_and_queues_it(store, settings, monkeypatch):
    created = []

    class FakeCalls:
        def create(self, **kw):
            created.append(kw)
            return type("FakeCall", (), {"sid": "CA_fake"})()

    class FakeClient:
        def __init__(self, sid, token):
            self.calls = FakeCalls()

    monkeypatch.setattr("twilio.rest.Client", FakeClient)
    s = allowlisted_settings(store, settings)
    call_id = services.dial_now(store, s, "f01")

    call = store.get("calls", call_id)
    assert call["channel"] == "twilio" and call["status"] == "queued"
    stored_phone = store.get("farmers", "f01")["phone"]
    assert " " in stored_phone  # seed_data formats it for display, e.g. "+62 810 0000 1000"
    assert created[0]["to"] == "+" + "".join(c for c in stored_phone if c.isdigit())  # E.164, no spaces
    assert " " not in created[0]["to"]
    assert created[0]["to"] in s.real_call_allowlist
    assert created[0]["from_"] == s.twilio_from_number
    assert created[0]["url"] == f"https://gw.example.test/twilio/voice?call_id={call_id}"


def test_dial_now_rolls_back_the_queued_call_on_twilio_failure(store, settings, monkeypatch):
    class FakeCalls:
        def create(self, **kw):
            raise RuntimeError("Twilio said no")

    class FakeClient:
        def __init__(self, sid, token):
            self.calls = FakeCalls()

    monkeypatch.setattr("twilio.rest.Client", FakeClient)
    before = len(store.list("calls"))
    with pytest.raises(services.ServiceError):
        services.dial_now(store, allowlisted_settings(store, settings), "f01")
    assert len(store.list("calls")) == before


def test_twilio_voice_webhook_validates_signature(settings, store):
    from twilio.request_validator import RequestValidator

    s = twilio_settings(settings)
    app = create_app(s, store)
    call_id = services.queue_call(store, store.get("farmers", "f01"), "collect", channel="twilio")
    url = f"https://gw.example.test/twilio/voice?call_id={call_id}"
    form = {"CallSid": "CA123", "From": "+15550000001", "To": "+15550000000", "CallStatus": "in-progress"}
    good_sig = RequestValidator(s.twilio_auth_token).compute_signature(url, form)

    with TestClient(app) as c:
        bad = c.post(f"/twilio/voice?call_id={call_id}", data=form, headers={"X-Twilio-Signature": "wrong"})
        assert bad.status_code == 403

        ok = c.post(f"/twilio/voice?call_id={call_id}", data=form, headers={"X-Twilio-Signature": good_sig})
        assert ok.status_code == 200 and "<Connect><Stream" in ok.text
        assert f"/twilio/stream/{call_id}" in ok.text


def test_twilio_voice_webhook_404s_when_not_configured(client):
    r = client.post("/twilio/voice?call_id=does-not-matter", data={})
    assert r.status_code == 404


def test_twilio_voice_webhook_apologises_for_an_unknown_call(settings, store):
    from twilio.request_validator import RequestValidator

    s = twilio_settings(settings)
    app = create_app(s, store)
    url = "https://gw.example.test/twilio/voice?call_id=no-such-call"
    good_sig = RequestValidator(s.twilio_auth_token).compute_signature(url, {})
    with TestClient(app) as c:
        r = c.post("/twilio/voice?call_id=no-such-call", data={}, headers={"X-Twilio-Signature": good_sig})
        assert r.status_code == 200 and "<Hangup/>" in r.text


def test_twilio_stream_runs_the_same_call_over_mulaw(store, settings, fake_voice):
    import base64

    from starlette.websockets import WebSocketDisconnect

    from app.audio_codec import pcm16_to_mulaw

    s = twilio_settings(settings)
    app = create_app(s, store)
    call_id = services.queue_call(store, store.get("farmers", "b001"), "gap_fill", gap_week=3,
                                  channel="twilio")
    events = []
    with TestClient(app) as c:
        with c.websocket_connect(f"/twilio/stream/{call_id}") as ws:
            ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1"}}))
            payload = base64.b64encode(pcm16_to_mulaw(b"\x01\x00" * 160)).decode()
            ws.send_text(json.dumps({"event": "media", "media": {"payload": payload}}))
            # Twilio has no screen for "ended"/"error" control messages (send_control
            # only ever forwards "interrupted" as Twilio's own clear event) - the call
            # ending shows up as the socket closing, not as a final text message.
            try:
                while True:
                    events.append(json.loads(ws.receive_text()))
            except WebSocketDisconnect:
                pass
    assert any(e.get("event") == "media" for e in events)  # the agent's greeting, as mu-law frames
    assert store.get("calls", call_id)["status"] == "done"


def test_twilio_stream_refuses_a_browser_channel_call(store, settings):
    from starlette.websockets import WebSocketDisconnect

    s = twilio_settings(settings)
    app = create_app(s, store)
    call_id = services.queue_call(store, store.get("farmers", "f01"), "collect")  # default channel: browser
    with TestClient(app) as c, pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/twilio/stream/{call_id}") as ws:
            ws.receive_text()  # the mismatch error is sent to run_call's channel, but
            # TwilioChannel has nowhere to show it - the socket just closes, same as a
            # real phone call would just disconnect rather than speak an internal error.
    assert store.get("calls", call_id)["status"] == "queued"  # refused before anything ran


def test_non_browser_channel_is_refused(store, settings):
    """No adapter exists yet for a non-browser channel; /ws/call must say so, not hang."""
    farmer = store.list("farmers")[0]
    call_id = services.queue_call(store, farmer, "collect", channel="twilio")
    app = create_app(settings, store)
    with TestClient(app) as c, c.websocket_connect(f"/ws/call/{call_id}") as ws:
        msg = json.loads(ws.receive()["text"])
    assert msg["type"] == "error" and "twilio" in msg["message"]


@pytest.mark.parametrize("outcome,ended_cleanly,confirmed", [
    ("completed", True, True),
    ("escalated", True, False),
    ("wrong_person", True, False),
    ("declined", True, False),
    (None, False, False),
])
def test_only_a_completed_confirmation_call_marks_the_offer_confirmed(
        client, store, settings, outcome, ended_cleanly, confirmed):
    offer_id = client.post("/api/rival-quotes/rq01/offer").json()["id"]
    client.post(f"/api/offers/{offer_id}/approve")
    call_id = next(c["id"] for c in store.list("calls") if c["kind"] == "confirm")
    services.finish_call(store, settings, call_id, ended_cleanly=ended_cleanly, outcome=outcome,
                         summary=None, consent=False, transcript=[])
    assert bool(store.get("offers", offer_id).get("confirmed_by_voice")) is confirmed
