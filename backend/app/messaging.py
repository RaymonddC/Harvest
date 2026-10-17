"""Text messages: a written copy of each confirmed deal for the farmer, and alerts for the planner.

Every message goes into the `messages` collection with a status in words, so the dashboard shows what was
sent and what was not. Real sending uses Twilio (SMS, or WhatsApp with TWILIO_WHATSAPP_FROM) and only happens
when MESSAGING_CHANNEL is "sms" or "whatsapp", Twilio is configured, and the number is on the same allowlist
as real calls (REAL_CALL_ALLOWLIST). Otherwise the message is still recorded, marked "not sent" with the reason.

Note for SMS from a US Twilio number: US carriers need A2P 10DLC registration, and Indonesian carriers filter
international SMS; WhatsApp needs an approved sender (or the Twilio sandbox) and approved templates for
messages outside a 24-hour reply window. Check delivery on a real phone before relying on it.
"""

from __future__ import annotations

import datetime as dt

from .config import Settings, normalize_phone
from .rules_engine import crop_label
from .store import Store

# The deal confirmation in each farmer language. {mill} {kg} {crop} {price} {week} are filled in.
# Thai, Vietnamese, Filipino, Javanese and Sundanese were written without a native reviewer: check before real use.
DEAL_TEXT = {
    "Bahasa Indonesia": "{mill}: kesepakatan disetujui. {kg} kg {crop}, harga {price}/kg, dikirim minggu mulai {week}. "
                        "Hubungi koperasi bila ada perubahan.",
    "Bahasa Malaysia": "{mill}: perjanjian diluluskan. {kg} kg {crop}, harga {price}/kg, dihantar minggu bermula {week}. "
                       "Hubungi koperasi jika ada perubahan.",
    "English": "{mill}: deal approved. {kg} kg {crop} at {price}/kg, delivery in the week from {week}. "
               "Contact the cooperative if anything changes.",
    "Javanese": "{mill}: kesepakatan disetujoni. {kg} kg {crop}, rega {price}/kg, dikirim minggu wiwit {week}. "
                "Hubungi koperasi yen ana owah-owahan.",
    "Sundanese": "{mill}: kasapukan disatujuan. {kg} kg {crop}, harga {price}/kg, dikirim minggu mimiti {week}. "
                 "Hubungi koperasi upami aya parobihan.",
    "Thai": "{mill}: อนุมัติข้อตกลงแล้ว {kg} กก. {crop} ราคา {price}/กก. ส่งในสัปดาห์ที่เริ่ม {week} "
            "หากมีการเปลี่ยนแปลงโปรดติดต่อสหกรณ์",
    "Vietnamese": "{mill}: thỏa thuận đã được duyệt. {kg} kg {crop}, giá {price}/kg, giao trong tuần từ {week}. "
                  "Liên hệ hợp tác xã nếu có thay đổi.",
    "Filipino": "{mill}: aprubado na ang kasunduan. {kg} kg {crop} sa {price}/kg, ihahatid sa linggong simula {week}. "
                "Tawagan ang kooperatiba kung may pagbabago.",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _money(price: float, currency: str) -> str:
    return f"Rp {round(price):,}".replace(",", ".") if currency == "IDR" else f"{price:,.2f} {currency}"


def channel_note(settings: Settings) -> str:
    if settings.messaging_channel not in ("sms", "whatsapp"):
        return "Text messages are off (MESSAGING_CHANNEL): they are recorded here, not sent."
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return "Text messages are on but Twilio is not set up: they are recorded, not sent."
    return f"Text messages go out by {settings.messaging_channel.upper()} to numbers on the allowlist."


def _why_not(store: Store, settings: Settings, to: str) -> str | None:
    if settings.messaging_channel not in ("sms", "whatsapp"):
        return "Messaging is off (MESSAGING_CHANNEL)."
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return "Twilio is not set up."
    sender = settings.twilio_whatsapp_from if settings.messaging_channel == "whatsapp" else settings.twilio_from_number
    if not sender:
        return "No sender number (TWILIO_FROM_NUMBER or TWILIO_WHATSAPP_FROM)."
    if not to:
        return "No phone number."
    from . import services

    if not services.number_allowed(store, settings, to):
        return f"{to} is not on the allowlist."
    return None


def send(store: Store, settings: Settings, to: str, body: str, kind: str, **refs) -> dict:
    """Record a message and send it when allowed. Never raises: a failed text must not break a call or approval."""
    number = normalize_phone(to) if to else ""
    doc = {"to": number, "body": body, "kind": kind, "channel": settings.messaging_channel, "created_at": _now(), **refs}
    reason = _why_not(store, settings, number)
    if reason:
        doc.update(status="not_sent", reason=reason)
    else:
        try:
            from twilio.rest import Client

            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            if settings.messaging_channel == "whatsapp":
                msg = client.messages.create(from_=f"whatsapp:{settings.twilio_whatsapp_from}", to=f"whatsapp:{number}", body=body)
            else:
                msg = client.messages.create(from_=settings.twilio_from_number, to=number, body=body)
            doc.update(status="sent", twilio_sid=getattr(msg, "sid", None))
        except Exception as e:  # noqa: BLE001 - record the failure, keep going
            doc.update(status="failed", reason=str(e)[:300])
    mid = store.add("messages", doc)
    return {**doc, "id": mid}


def send_deal_confirmation(store: Store, settings: Settings, offer: dict) -> dict | None:
    farmer = store.get("farmers", offer["farmer_id"])
    if not farmer or offer.get("status") != "approved":
        return None
    template = DEAL_TEXT.get(farmer.get("language") or "", DEAL_TEXT["English"])
    week = offer.get("deliver_week_start") or ""
    if week:
        week = dt.date.fromisoformat(week).strftime("%d/%m/%Y")
    body = template.format(mill=settings.mill_name, kg=f"{round(offer['kg']):,}".replace(",", "."),
                           crop=crop_label(offer.get("crop") or settings.demo_crop),
                           price=_money(offer["price_per_kg"], offer.get("currency", "IDR")), week=week)
    msg = send(store, settings, farmer.get("phone", ""), body, "deal_confirmation", farmer_id=farmer["id"],
               farmer_name=farmer.get("name"), offer_id=offer["id"])
    store.set("offers", offer["id"], {"text_status": msg["status"], "text_message_id": msg["id"]}, merge=True)
    return msg


def alert_planner(store: Store, settings: Settings, body: str, kind: str, **refs) -> list[dict]:
    """An alert for the planner: sent to each PLANNER_ALERT_TO number, and always kept in the outbox."""
    targets = list(settings.planner_alert_to) or [""]
    return [send(store, settings, to, body, kind, audience="planner", **refs) for to in targets]


def check_gap_alerts(store: Store, settings: Settings) -> list[dict]:
    """Alert once per new gap week (by calendar week), so the planner hears about a shortfall without looking."""
    from . import services

    sent = []
    for camp in services.list_campaigns(store, settings):
        crop = camp.get("crop") or settings.demo_crop
        name = camp.get("name") or crop_label(crop)
        alerted = set(camp.get("alerted_gaps") or [])
        rows = [r for r in store.list("forecast") if services._row_matches(r, camp["id"]) and r.get("is_gap")]
        new = [r for r in rows if r["week_start"] not in alerted]
        for r in new:
            n = len(r.get("shortlist") or [])
            body = (f"{settings.mill_name}: {name} week {r['week']} (from {r['week_start']}) is "
                    f"{round(r['gap_kg'] / 1000, 1)} t short. {n} farmers can bring harvest forward.")
            sent += alert_planner(store, settings, body, "gap_alert", crop=crop, week_start=r["week_start"])
        if new:
            store.set("campaigns", camp["id"], {"alerted_gaps": sorted(alerted | {r["week_start"] for r in new})}, merge=True)
    return sent
