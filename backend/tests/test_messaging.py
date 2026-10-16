import dataclasses

from app import messaging, services


class FakeMessages:
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


def on(settings, **extra):
    return dataclasses.replace(settings, twilio_account_sid="AC1", twilio_auth_token="tok", twilio_from_number="+15550000000",
                               messaging_channel="sms", real_call_allowlist=("+628114617000",), **extra)


def test_off_by_default_messages_are_recorded_not_sent(store, settings):
    m = messaging.send(store, settings, "+62 811 4617 000", "hi", "test")
    assert m["status"] == "not_sent" and "MESSAGING_CHANNEL" in m["reason"]
    assert store.get("messages", m["id"])["to"] == "+628114617000"


def test_sends_only_to_the_allowlist(store, settings, monkeypatch):
    fake = FakeMessages()
    monkeypatch.setattr("twilio.rest.Client", fake.client())
    s = on(settings)
    assert messaging.send(store, s, "+628114617000", "hi", "test")["status"] == "sent"
    assert messaging.send(store, s, "+628000000000", "hi", "test")["status"] == "not_sent"
    assert len(fake.sent) == 1 and fake.sent[0]["to"] == "+628114617000"
    w = dataclasses.replace(s, messaging_channel="whatsapp", twilio_whatsapp_from="+14155238886")
    messaging.send(store, w, "+628114617000", "hi", "test")
    assert fake.sent[-1]["to"] == "whatsapp:+628114617000" and fake.sent[-1]["from_"] == "whatsapp:+14155238886"


def test_a_twilio_error_is_recorded_not_raised(store, settings, monkeypatch):
    class Boom:
        def __init__(self, *a):
            raise RuntimeError("21608 unverified")
    monkeypatch.setattr("twilio.rest.Client", Boom)
    m = messaging.send(store, on(settings), "+628114617000", "hi", "test")
    assert m["status"] == "failed" and "21608" in m["reason"]


def test_deal_confirmation_in_the_farmers_language_after_the_voice_confirmation(store, settings, monkeypatch):
    fake = FakeMessages()
    monkeypatch.setattr("twilio.rest.Client", fake.client())
    s = on(settings)
    store.set("farmers", "s01", {"phone": "+628114617000"}, merge=True)
    offer = services.offer_from_rival_quote(store, s, "rq01")
    services.decide_offer(store, s, offer["id"], approve=True)
    call_id = next(c["id"] for c in store.list("calls") if c.get("offer_id") == offer["id"])
    services.finish_call(store, s, call_id, ended_cleanly=True, outcome="completed", summary="ok", consent=False, transcript=[])
    body = fake.sent[-1]["body"]
    assert body.startswith("Koperasi Sawit Maju: kesepakatan disetujui. 12.000 kg Palm FFB, harga Rp 3.280/kg")
    assert store.get("offers", offer["id"])["text_status"] == "sent"


def test_planner_hears_about_a_new_gap_once_and_about_waiting_offers(store, settings):
    s = dataclasses.replace(settings, planner_alert_to=("+628114617000",))
    first = messaging.check_gap_alerts(store, s)
    assert len(first) == 1 and "week 3" in first[0]["body"] and first[0]["audience"] == "planner"
    assert messaging.check_gap_alerts(store, s) == []  # already told
    services.offer_from_rival_quote(store, s, "rq01")
    waiting = [m for m in store.list("messages") if m["kind"] == "offer_waiting"]
    assert len(waiting) == 1 and "Rival supplier" in waiting[0]["body"]
