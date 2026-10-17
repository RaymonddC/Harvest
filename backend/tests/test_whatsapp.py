"""The WhatsApp chat agent: the same tools and rules as a call, run one message at a time (whatsapp.py)."""

import asyncio
import dataclasses
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app import prompt, services, whatsapp
from app.main import create_app

PHONE = "+628114617000"


class ScriptedModel:
    """Stands in for Gemini: each call returns the next scripted turn (text, or tool calls)."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []  # (contents, instruction) of every request

    async def __call__(self, contents, instruction):
        self.seen.append((list(contents), instruction))
        turn = self.turns.pop(0)
        if isinstance(turn, str):
            parts = [types.Part(text=turn)]
        else:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in turn]
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])


def farmer_of(store):
    return next(f for f in store.list("farmers") if f.get("type", "farmer") == "farmer")


def live(settings, **extra):
    return dataclasses.replace(settings, twilio_account_sid="AC1", twilio_auth_token="tok",
                               twilio_whatsapp_from="+14155238886", public_base_url="https://gw.example",
                               real_call_allowlist=(PHONE,), **extra)


class FakeTwilio:
    def __init__(self):
        self.sent = []

    def client(self):
        outer = self

        class Messages:
            def create(self, **kw):
                outer.sent.append(kw)
                return type("M", (), {"sid": f"SM{len(outer.sent)}"})()

        class Client:
            def __init__(self, sid, token):
                self.messages = Messages()

        return Client


def run(coro):
    return asyncio.run(coro)


def test_demo_chat_opens_with_the_ai_notice_and_consent_question(store, settings):
    f = farmer_of(store)
    r = whatsapp.open_chat(store, settings, f["id"])
    call = store.get("calls", r["call_id"])
    assert not r["live"] and "not set up" in r["note"]
    assert call["channel"] == "whatsapp" and call["status"] == "on_call" and call["whatsapp_live"] is False
    opening = call["chat"][0]["text"]
    assert call["chat"][0]["who"] == "agent" and "AI" in opening and settings.mill_name in opening
    assert "setuju" in opening  # the consent question, in the farmer's language (Indonesian in the test seed)
    with pytest.raises(services.ServiceError, match="already has a WhatsApp chat open"):
        whatsapp.open_chat(store, settings, f["id"])


def test_a_whole_harvest_chat_saves_the_harvest_and_keeps_the_transcript(store, settings):
    f = farmer_of(store)
    cid = whatsapp.open_chat(store, settings, f["id"])["call_id"]
    ready = (settings.plan_start + dt.timedelta(days=9)).isoformat()
    crop = "palm FFB"
    model = ScriptedModel([
        [("record_consent", {"transcript_consent": True})],
        "Terima kasih. Kapan panen berikutnya, dan kira-kira berapa kilo?",
        [("record_harvest", {"crop": crop, "kg": 2000, "ready_date": ready, "confirmed_by_farmer": False})],
        "Jadi 2.000 kg, siap tanggal itu. Betul?",
        [("record_harvest", {"crop": crop, "kg": 2000, "ready_date": ready, "confirmed_by_farmer": True})],
        [("end_call", {"outcome": "completed", "summary": "2,000 kg ready.", "transcript_consent": True})],
        "Terima kasih, sampai jumpa.",
    ])
    assert "Kapan panen" in run(whatsapp.reply_as_farmer(store, settings, cid, "Ya, setuju", generate=model))
    assert "Betul?" in run(whatsapp.reply_as_farmer(store, settings, cid, "2 ton, minggu depan", generate=model))
    assert "sampai jumpa" in run(whatsapp.reply_as_farmer(store, settings, cid, "Betul", generate=model))
    harvest = store.get("harvests", f"h-{f['id']}-palm")
    assert harvest["kg"] == 2000 and harvest["ready_date"] == ready and harvest["call_id"] == cid
    call = store.get("calls", cid)
    assert call["status"] == "done" and call["consent"] is True and call["summary"] == "2,000 kg ready."
    assert [line["who"] for line in call["transcript"]] == ["agent", "farmer", "agent", "farmer", "agent", "farmer", "agent"]
    assert call["chat_contents"] is None and call["chat_state"] is None  # the working copy is gone
    # The model saw the opening it had sent, and the chat instruction (not the phone one).
    contents, instruction = model.seen[0]
    assert contents[1].role == "model" and "AI" in contents[1].parts[0].text
    assert "WhatsApp" in instruction and "Opening: your first message was already sent" in instruction
    with pytest.raises(services.ServiceError, match="ended"):
        run(whatsapp.reply_as_farmer(store, settings, cid, "halo", generate=model))


def test_the_read_back_rule_holds_across_messages(store, settings):
    """Nothing is saved until the farmer saw the numbers: the session state is kept between messages."""
    f = farmer_of(store)
    cid = whatsapp.open_chat(store, settings, f["id"])["call_id"]
    ready = (settings.plan_start + dt.timedelta(days=9)).isoformat()
    args = {"crop": "palm FFB", "kg": 1500, "ready_date": ready}
    model = ScriptedModel([
        [("record_harvest", {**args, "confirmed_by_farmer": True})],  # skips the read-back: refused, becomes it
        "1.500 kg, betul?",
        [("record_harvest", {**args, "confirmed_by_farmer": True})],  # next message: now it saves
        "Tersimpan.",
    ])
    run(whatsapp.reply_as_farmer(store, settings, cid, "1500 kg", generate=model))
    assert store.get("harvests", f"h-{f['id']}-palm") is None or store.get("harvests", f"h-{f['id']}-palm")["kg"] != 1500
    assert store.get("calls", cid)["chat_state"]["read_back"]["palm"]["kg"] == 1500
    run(whatsapp.reply_as_farmer(store, settings, cid, "betul", generate=model))
    assert store.get("harvests", f"h-{f['id']}-palm")["kg"] == 1500


def test_no_consent_keeps_no_transcript(store, settings):
    f = farmer_of(store)
    cid = whatsapp.open_chat(store, settings, f["id"])["call_id"]
    model = ScriptedModel([
        [("record_consent", {"transcript_consent": False})],
        [("end_call", {"outcome": "declined", "summary": "Did not want to chat.", "transcript_consent": False})],
        "Baik, maaf mengganggu.",
    ])
    run(whatsapp.reply_as_farmer(store, settings, cid, "Tidak", generate=model))
    call = store.get("calls", cid)
    assert call["status"] == "declined" and call["transcript"] is None and call["chat"] is None


def test_a_failed_turn_answers_sorry_and_keeps_the_chat_open(store, settings):
    f = farmer_of(store)
    cid = whatsapp.open_chat(store, settings, f["id"])["call_id"]

    async def broken(contents, instruction):
        raise RuntimeError("quota")

    assert run(whatsapp.reply_as_farmer(store, settings, cid, "halo", generate=broken)) == whatsapp.SORRY
    call = store.get("calls", cid)
    assert call["status"] == "on_call" and call["chat"][-1]["text"] == whatsapp.SORRY


def test_quiet_chats_end_after_a_day_without_a_retry(store, settings):
    f = farmer_of(store)
    cid = whatsapp.open_chat(store, settings, f["id"])["call_id"]
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=whatsapp.CHAT_IDLE_HOURS + 1)
    assert whatsapp.close_stale_chats(store, settings, later) == 1
    call = store.get("calls", cid)
    assert call["status"] == "dropped" and call["outcome"] == "no_reply" and not call.get("retry_queued")
    assert not [c for c in store.list("calls") if c["farmer_id"] == f["id"] and c["status"] == "queued"]


def test_real_whatsapp_only_to_allowlisted_numbers_with_the_template(store, settings, monkeypatch):
    fake = FakeTwilio()
    monkeypatch.setattr("twilio.rest.Client", fake.client())
    s = live(settings, twilio_whatsapp_opening_sid="HX123")
    f = farmer_of(store)
    other = [x for x in store.list("farmers") if x.get("type", "farmer") == "farmer"][1]
    store.set("farmers", f["id"], {"phone": "+62 811 4617 000"}, merge=True)
    r = whatsapp.open_chat(store, s, f["id"])
    assert r["live"] and fake.sent[-1]["to"] == f"whatsapp:{PHONE}" and fake.sent[-1]["content_sid"] == "HX123"
    assert '"2": "' + s.mill_name in fake.sent[-1]["content_variables"]
    assert not whatsapp.open_chat(store, s, other["id"])["live"]  # not on the allowlist: a demo chat, nothing sent
    assert len(fake.sent) == 1
    with pytest.raises(services.ServiceError, match="real WhatsApp"):
        run(whatsapp.reply_as_farmer(store, s, r["call_id"], "hi"))


def test_incoming_messages_reach_the_agent_and_strangers_are_ignored(store, settings, monkeypatch):
    s = live(settings)
    f = farmer_of(store)
    store.set("farmers", f["id"], {"phone": "+62 811 4617 000"}, merge=True)
    model = ScriptedModel(["Halo Pak, ini asisten AI. Apakah ini benar Pak? Boleh kami simpan catatan chat ini?"])
    monkeypatch.setattr(whatsapp, "_generate", lambda settings: model)
    stranger = {"From": "whatsapp:+628999999999", "Body": "halo", "MessageSid": "SM0"}
    assert run(whatsapp.handle_incoming(store, s, stranger)) is None
    msg = {"From": f"whatsapp:{PHONE}", "Body": "Panen saya minggu depan", "MessageSid": "SM1", "NumMedia": "0"}
    assert "asisten AI" in run(whatsapp.handle_incoming(store, s, msg))
    chat = whatsapp.open_chat_for(store, f["id"])
    assert chat["farmer_started"] and chat["chat"][0] == {**chat["chat"][0], "who": "farmer", "text": "Panen saya minggu depan"}
    assert "the farmer wrote first" in model.seen[0][1]
    assert run(whatsapp.handle_incoming(store, s, msg)) is None  # the same message again is not answered twice


def test_webhook_checks_twilio_signature_and_answers_in_twiml(store, settings, monkeypatch):
    from twilio.request_validator import RequestValidator

    s = live(settings)
    f = farmer_of(store)
    store.set("farmers", f["id"], {"phone": "+62 811 4617 000"}, merge=True)
    monkeypatch.setattr(whatsapp, "_generate", lambda settings: ScriptedModel(["Harga & jadwal <ok>"]))
    client = TestClient(create_app(s, store))
    form = {"From": f"whatsapp:{PHONE}", "Body": "halo", "MessageSid": "SM9", "NumMedia": "0"}
    assert client.post("/twilio/whatsapp", data=form, headers={"X-Twilio-Signature": "bad"}).status_code == 403
    sig = RequestValidator("tok").compute_signature("https://gw.example/twilio/whatsapp", form)
    r = client.post("/twilio/whatsapp", data=form, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200 and "<Message>Harga &amp; jadwal &lt;ok&gt;</Message>" in r.text


def test_api_starts_a_chat_and_a_whatsapp_campaign(store, settings, monkeypatch):
    client = TestClient(create_app(settings, store))
    f = farmer_of(store)
    r = client.post(f"/api/farmers/{f['id']}/whatsapp", json={})
    assert r.status_code == 200 and r.json()["live"] is False
    model = ScriptedModel(["Terima kasih."])
    monkeypatch.setattr(whatsapp, "_generate", lambda settings: model)
    assert client.post(f"/api/chats/{r.json()['call_id']}/reply", json={"text": "Ya"}).json()["reply"] == "Terima kasih."
    assert client.post(f"/api/chats/{r.json()['call_id']}/end").status_code == 200
    assert store.get("calls", r.json()["call_id"])["status"] == "dropped"
    started = client.post("/api/campaign/start", json={"kind": "collect", "channel": "whatsapp"}).json()
    assert started["channel"] == "whatsapp" and started["queued"] > 0 and started["chats"]["demo"] == started["queued"]
    assert all(c["status"] == "on_call" for c in store.list("calls") if c.get("channel") == "whatsapp" and c["id"] != r.json()["call_id"])


def test_the_phone_instruction_is_unchanged_and_the_chat_one_shares_its_tool_rules(store, settings):
    f = farmer_of(store)
    voice = prompt.build_system_instruction(settings, f, "collect", None)
    chat = prompt.build_system_instruction(settings, f, "collect", None, chat=True, chat_opening_sent="Halo")
    assert voice.startswith("You are a polite phone assistant") and "WhatsApp" not in voice
    assert chat.startswith("You are a polite WhatsApp assistant") and prompt.TOOL_RULES.split("\n")[1] in chat
    assert "Ending the chat" in chat and "Ending the call" not in chat


class FakeHttp:
    def __init__(self, senders, update_status=200):
        self.senders, self.update_status, self.calls = senders, update_status, []

    def _resp(self, status, data):
        return type("R", (), {"status_code": status, "json": lambda self: data, "text": str(data)})()

    def get(self, url, params=None):
        self.calls.append(("GET", url))
        return self._resp(200, {"senders": self.senders})

    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self._resp(self.update_status, {})

    put = post


def test_connect_points_the_sender_webhook_at_the_service(settings):
    s = live(settings)
    http = FakeHttp([{"sid": "XE1", "sender_id": "whatsapp:+14155238886", "status": "ONLINE"}])
    r = whatsapp.connect_webhook(s, http=http)
    assert r["webhook"] == "https://gw.example/twilio/whatsapp" and r["status"] == "ONLINE"
    assert http.calls[-1] == ("POST", f"{whatsapp.SENDERS_URL}/XE1",
                              {"webhook": {"callback_url": "https://gw.example/twilio/whatsapp", "callback_method": "POST"}})
    with pytest.raises(services.ServiceError, match="not a WhatsApp sender"):
        whatsapp.connect_webhook(s, http=FakeHttp([{"sid": "XE2", "sender_id": "whatsapp:+10000000000"}]))
    with pytest.raises(services.ServiceError, match="not set up"):
        whatsapp.connect_webhook(settings, http=http)
