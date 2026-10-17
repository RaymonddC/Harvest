"""The tools the voice model can call, and their handlers.

Each call gets its own ToolHandlers bound to one farmer, so the model can never
read or write another farmer's records. Handlers return two things: the result the
model sees (never the floor or ceiling) and, separately, `last_ui`, a richer payload
for the call screen (captured answers, the check_offer price rail).
"""

from __future__ import annotations

import datetime as dt
import re
import math
import logging
from dataclasses import dataclass, field

from . import forecast as fc
from . import rules_engine, services
from .config import Settings
from .agent_profile import AgentProfileError, parse_answer
from .rules_engine import crop_label, normalize_crop
from .store import Store

log = logging.getLogger(__name__)

OUTCOMES = ["completed", "declined", "stopped", "escalated", "wrong_person"]

TOOL_DECLARATIONS = [
    {
        "name": "get_farmer",
        "description": "Get the profile of the person on this call: name, crop, language, village, "
                       "any harvest already on record, and the purpose of the call.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "record_harvest",
        "description": "Record the farmer's expected harvest. As soon as you have crop, volume and date, "
                       "call it with confirmed_by_farmer false: it returns the sentence to read back. "
                       "When the farmer says yes, call it again with confirmed_by_farmer true to save.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "crop": {"type": "STRING", "description": "Crop name, for example palm FFB."},
                "kg": {"type": "NUMBER", "description": "Expected volume in kilograms."},
                "ready_date": {"type": "STRING", "description": "Date the harvest is ready, YYYY-MM-DD."},
                "confidence": {"type": "STRING", "enum": ["firm", "unsure"],
                               "description": "unsure if the farmer hedged (maybe, I think, depends on rain)."},
                "every_days": {"type": "NUMBER",
                               "description": "Days between the farmer's harvest rounds, if they said (palm is often "
                                              "10 to 15). Leave it out if they did not say."},
                "confirmed_by_farmer": {"type": "BOOLEAN",
                                        "description": "True only after the farmer confirmed the read-back."},
            },
            "required": ["crop", "kg", "ready_date", "confirmed_by_farmer"],
        },
    },
    {
        "name": "get_reference_price",
        "description": "Get today's market reference price for a crop, to read aloud before any offer.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"crop": {"type": "STRING"}},
            "required": ["crop"],
        },
    },
    {
        "name": "check_offer",
        "description": "Get the price you may offer. Call it before every offer. Pass "
                       "farmer_counter_price when the farmer names a price. Say only the price it returns.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "crop": {"type": "STRING"},
                "kg": {"type": "NUMBER", "description": "Volume in kilograms the offer covers."},
                "farmer_counter_price": {"type": "NUMBER",
                                         "description": "Price per kg the farmer asked for, if any."},
            },
            "required": ["crop", "kg"],
        },
    },
    {
        "name": "save_offer",
        "description": "Send an agreed deal to the planner as a pending offer. The price must be one "
                       "that check_offer returned on this call. Set escalate to true to hand an "
                       "out-of-limit request to the planner instead.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "crop": {"type": "STRING"},
                "kg": {"type": "NUMBER"},
                "price_per_kg": {"type": "NUMBER"},
                "escalate": {"type": "BOOLEAN"},
                "farmer_requested_price": {"type": "NUMBER"},
            },
            "required": ["crop", "kg", "price_per_kg"],
        },
    },
    {
        "name": "record_answer",
        "description": "Save the farmer's answer to one of the planner's extra questions, by its id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question_id": {"type": "STRING", "description": "The id in brackets, e.g. q-1a2b3c4d."},
                "answer": {"type": "STRING", "description": "The answer as the farmer gave it; \"skipped\" if they "
                                                            "did not want to answer."},
            },
            "required": ["question_id", "answer"],
        },
    },
    {
        "name": "record_consent",
        "description": "Record the farmer's answer to the consent question, as soon as they answer it. "
                       "Then a call that is cut off later still keeps (or still does not keep) the transcript "
                       "as the farmer said.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"transcript_consent": {"type": "BOOLEAN",
                                                  "description": "True only if the farmer agreed."}},
            "required": ["transcript_consent"],
        },
    },
    {
        "name": "end_call",
        "description": "End the call after the closing sentence. Give a short summary and whether "
                       "the farmer agreed to the transcript being saved.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "outcome": {"type": "STRING", "enum": OUTCOMES},
                "summary": {"type": "STRING", "description": "One or two sentences for the planner."},
                "transcript_consent": {"type": "BOOLEAN"},
            },
            "required": ["outcome", "summary", "transcript_consent"],
        },
    },
]


@dataclass
class CallSession:
    call_id: str
    farmer: dict
    kind: str  # "collect", "gap_fill" or "confirm"
    gap_week: int | None = None
    offer: dict | None = None  # the approved offer, for confirm calls
    rung_index: dict[str, int] = field(default_factory=dict)  # per crop
    quoted_prices: dict[str, set[float]] = field(default_factory=dict)  # per crop
    first_offer: dict[str, float] = field(default_factory=dict)  # per crop
    last_counter: dict[str, float] = field(default_factory=dict)  # per crop
    ended: bool = False
    outcome: str | None = None
    summary: str | None = None
    consent: bool | None = None
    consent_at: str | None = None  # when the farmer's answer was first recorded: part of the proof of consent (PDP Law, Art. 24)
    saved_offer_ids: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)  # the campaign's extra questions
    answers: dict[str, dict] = field(default_factory=dict)  # question id -> {question, type, answer}
    read_back: dict[str, tuple[float, str]] = field(default_factory=dict)  # per crop: (kg, date) last read back
    end_refused: bool = False  # end_call was refused once because a read-back was never saved
    saved_kg: dict[str, float] = field(default_factory=dict)  # per crop: the volume saved on this call
    price_warned: set[tuple[str, float]] = field(default_factory=set)  # (crop, number) already refused as a price
    checked_kg: dict[str, float] = field(default_factory=dict)  # per crop: the volume check_offer last priced
    full_warned: set[tuple[str, str]] = field(default_factory=set)  # (crop, date) the farmer was already told is a full week


def _weekday_label(date: dt.date, settings: Settings) -> str:
    w = fc.week_index(date, settings.plan_start, settings.weeks)
    return f"{fc.week_label(w) if w else 'Later'} · {date:%a}"


_CROP_ID = re.compile(r"^[a-z0-9][a-z0-9 -]{0,39}$")


def _crop_id(crop: str) -> str:
    """The crop id a tool may use: normalized, and plain words only (it becomes part of stored document ids)."""
    crop_id = normalize_crop(crop)
    if not _CROP_ID.match(crop_id):
        raise ValueError(f"{crop!r} is not a crop name")
    return crop_id


def _volume(kg) -> float:
    kg = float(kg)
    if not math.isfinite(kg) or kg <= 0:
        raise ValueError("kg must be a positive number")
    return kg


class ToolHandlers:
    def __init__(self, store: Store, settings: Settings, session: CallSession) -> None:
        self.store = store
        self.settings = settings
        self.session = session
        self.last_ui: dict | None = None

    def dispatch(self, name: str, args: dict | None) -> dict:
        args = dict(args or {})
        self.last_ui = None
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"error": f"Unknown tool {name}."}
        try:
            result = handler(**args)
        except services.ServiceError as e:
            result = {"error": str(e)}
        except (TypeError, ValueError) as e:
            result = {"error": f"Bad arguments for {name}: {e}"}
        except Exception as e:  # noqa: BLE001  a store or network failure must not end the call
            log.exception("tool %s failed", name, extra={"call_id": self.session.call_id})
            result = {"error": f"{name} could not be done right now ({type(e).__name__}). Carry on with the call and tell "
                               "the farmer the planner will follow up if it matters."}
        log.info("tool %s(%s) -> %s", name, args, result, extra={"call_id": self.session.call_id})
        return result

    # ----- tools -----

    def _tool_get_farmer(self) -> dict:
        f = self.session.farmer
        crop = normalize_crop(f.get("crop", ""))
        harvest = self.store.get("harvests", f"h-{f['id']}-{crop}")
        out = {
            "name": f.get("name"), "type": f.get("type", "farmer"), "crop": crop_label(crop),
            "language": f.get("language"), "village": f.get("village"),
            "call_purpose": self.session.kind,
            "harvest_on_record": None,
        }
        if harvest:
            week = fc.week_index(harvest["ready_date"], self.settings.plan_start, self.settings.weeks)
            out["harvest_on_record"] = {"kg": harvest["kg"], "ready_date": harvest["ready_date"],
                                        "week": fc.week_label(week) if week else None,
                                        "confidence": harvest.get("confidence", "firm")}
        if self.session.gap_week:
            ws = fc.week_start(self.session.gap_week, self.settings.plan_start)
            out["gap_week"] = {"label": fc.week_label(self.session.gap_week), "starts": ws.isoformat()}
        if self.session.offer:
            o = self.session.offer
            out["approved_offer"] = {"crop": crop_label(o["crop"]), "kg": o["kg"],
                                     "price_per_kg": o["price_per_kg"], "currency": o.get("currency", "IDR"),
                                     "deliver_week": fc.week_label(o["deliver_week"]) if o.get("deliver_week") else None}
        return out

    def _tool_record_harvest(self, crop: str, kg: float, ready_date: str,
                             confirmed_by_farmer: bool, confidence: str = "firm",
                             every_days: float | None = None) -> dict:
        crop_id = _crop_id(crop)
        kg = _volume(kg)
        try:
            date = dt.date.fromisoformat(str(ready_date)[:10])
        except ValueError:
            return {"error": "ready_date must be a date in YYYY-MM-DD form."}
        confidence = "unsure" if confidence == "unsure" else "firm"
        looks_like_price = self._looks_like_price(crop_id, kg)
        if looks_like_price:
            self.session.price_warned.add((crop_id, kg))
            return {"saved": False, "status": "looks_like_a_price",
                    "error": f"Not saved. {round(kg):,} looks like a price per kilogram, not a harvest volume: the "
                             f"volume already recorded on this call is {round(self.session.saved_kg[crop_id]):,} kg. "
                             "Do not change the harvest. If the farmer named a price, use it as farmer_counter_price "
                             "in check_offer. Only if they clearly said a NEW volume in kilograms, ask them to "
                             "confirm it and call this again."}
        full = self._full_week_warning(crop_id, kg, date)
        if full:
            return full
        self.last_ui = {"captured": {"crop": crop_label(crop_id), "kg": round(kg),
                                     "ready": _weekday_label(date, self.settings),
                                     "confidence": confidence.title(),
                                     "status": "saved" if confirmed_by_farmer else "waiting"}}
        if not confirmed_by_farmer:
            if self.session.read_back.get(crop_id) == (kg, date.isoformat()) and self.session.saved_kg.get(crop_id) != kg:
                # Seen in recorded calls: the agent reads the same numbers back again and again while the farmer
                # keeps saying yes, and never saves. Say plainly what the next step is instead of a fresh read-back.
                return {"saved": False, "status": "already_read_back",
                        "say": "You already read these exact numbers back. If the farmer said yes, call record_harvest "
                               "now with the same numbers and confirmed_by_farmer true. Do not read them back again. "
                               "Only if the farmer corrected something, call it with the new numbers."}
            self.session.read_back[crop_id] = (kg, date.isoformat())
            self._note_read_back(crop_id, kg, date, confidence)
            return {"saved": False, "status": "waiting_for_read_back",
                    "read_back": f"{round(kg):,} kg of {crop_label(crop_id)}, ready on {date:%A %d %B}.",
                    "say": "Check it with the farmer in one natural sentence in their language, the way a person "
                           "says it (for example \"Jadi sekitar dua ton, besok hari Sabtu ya, Pak?\"), with the crop "
                           "in their own word, not read out like a record. If they say yes, call record_harvest again "
                           "with confirmed_by_farmer true."}
        if self.session.read_back.get(crop_id) != (kg, date.isoformat()):
            # Enforced here, not only in the prompt: nothing is saved until these exact numbers were read back.
            # The call that skipped the read-back becomes the read-back step, so there is nothing to retry.
            self.session.read_back[crop_id] = (kg, date.isoformat())
            self._note_read_back(crop_id, kg, date, confidence)
            self.last_ui = {"captured": {**self.last_ui["captured"], "status": "waiting"}}
            return {"saved": False, "status": "read_back_required",
                    "read_back": f"{round(kg):,} kg of {crop_label(crop_id)}, ready on {date:%A %d %B}.",
                    "say": "Not saved yet: the farmer has not heard these numbers back. Check them with the farmer "
                           "in one natural sentence in their language (the way a person says it, not like a record) "
                           "and ask if it is right. If they say yes, call record_harvest "
                           "again with the same numbers and confirmed_by_farmer true. This is the normal next "
                           "step, not an error; do not apologise."}
        try:
            every = float(every_days) if every_days else None
        except (TypeError, ValueError):
            every = None
        if every is not None and not fc.MIN_EVERY_DAYS <= every <= fc.MAX_EVERY_DAYS:
            every = None  # a cycle outside 5 to 45 days was misheard; keep the harvest, drop the cycle
        result = services.record_harvest(self.store, self.settings, self.session.farmer["id"], crop_id,
                                         kg, date.isoformat(), self.session.call_id, confidence, every)
        self.session.saved_kg[crop_id] = kg
        self.store.set("calls", self.session.call_id, {"harvest_read_back": None}, merge=True)
        if (crop_id, date.isoformat()) in self.session.full_warned and result.get("harvest_id"):
            # The farmer was told the week is full and kept the date: the planner sees it on the harvest.
            self.store.set("harvests", result["harvest_id"], {"week_full": {"week": result.get("week_label"),
                                                                           "kept_by_farmer": True}}, merge=True)
        return {"saved": True, **result}

    def _full_week_warning(self, crop_id: str, kg: float, date: dt.date) -> dict | None:
        """First time the farmer names a week the mill already has enough for, nothing is saved: the agent tells the
        farmer and offers the nearest later week with room. If the farmer keeps the date, the second try saves it
        (flagged for the planner), so a farmer can never be refused."""
        key = (crop_id, date.isoformat())
        if key in self.session.full_warned or self.session.farmer.get("type") == "supplier":
            return None
        camp = services.campaign_of_farmer(self.store, self.settings, self.session.farmer)
        if not camp:
            return None
        weeks = services.campaign_weeks(self.settings, camp)
        week = fc.week_index(date, self.settings.plan_start, weeks)
        if not week:
            return None
        old = self.store.get("harvests", f"h-{self.session.farmer['id']}-{crop_id}")
        own = 0.0
        if old and fc.week_index(old["ready_date"], self.settings.plan_start, weeks) == week:
            own = float(old.get("kg", 0)) * fc.harvest_weight(old)  # the farmer's current record is not "other supply"
        fill = services.week_fill(self.store, self.settings, camp["id"], week, own_kg=own)
        if not fill or not fill["full"]:
            return None
        self.session.full_warned.add(key)
        later = services.next_week_with_room(self.store, self.settings, camp["id"], week)
        if later:
            ask = (f"Tell the farmer, kindly, that the mill already has enough fruit for {fill['label']} and ask whether they "
                   f"could deliver around {later['week_start']} ({later['label']}) instead; fruit can wait a few days but not "
                   "longer than three weeks. If they agree, call record_harvest with that new date. If they want to keep "
                   "their date, call record_harvest again with the same date and it will be saved for the planner to sort out.")
        else:
            ask = (f"Tell the farmer that the mill already has enough fruit for {fill['label']} and no later week within three "
                   "weeks has room right now. Ask what they prefer; if they keep their date, call record_harvest again "
                   "with the same date and it will be saved for the planner to sort out. Do not promise anything.")
        return {"saved": False, "status": "week_full", "week": fill["label"],
                "suggested_week": later["label"] if later else None,
                "suggested_from": later["week_start"] if later else None, "say": ask}

    def _note_read_back(self, crop_id: str, kg: float, date: dt.date, confidence: str) -> None:
        self.store.set("calls", self.session.call_id, {"harvest_read_back": {
            "crop": crop_id, "kg": round(kg), "ready_date": date.isoformat(), "confidence": confidence}}, merge=True)

    def _unsaved_read_back(self) -> tuple[str, float, str] | None:
        """A harvest read back to the farmer on this call but never saved with confirmed_by_farmer true."""
        for crop_id, (kg, date) in self.session.read_back.items():
            if self.session.saved_kg.get(crop_id) != kg:
                return crop_id, kg, date
        return None

    def _looks_like_price(self, crop_id: str, kg: float) -> bool:
        """A second, different 'volume' that falls inside this crop's price range is almost surely a price the
        farmer said ("naik jadi 3300"), not a harvest. Refused once; the same number again is let through,
        so a real correction is never blocked for good."""
        if crop_id not in self.session.saved_kg or kg == self.session.saved_kg[crop_id]:
            return False
        if (crop_id, kg) in self.session.price_warned:
            return False
        doc = self.store.get("limits", crop_id)
        if not doc:
            return False
        return float(doc["floor_price"]) * 0.9 <= kg <= float(doc["ceiling_price"]) * 1.1

    def _tool_get_reference_price(self, crop: str) -> dict:
        limits = services.get_limits(self.store, crop)
        return {"crop": crop_label(limits.crop), "reference_price": limits.reference,
                "currency": limits.currency, "unit": limits.unit,
                "say": f"Today's market reference price is {limits.reference:,.0f} {limits.currency} "
                       f"per {limits.unit}."}

    def _tool_check_offer(self, crop: str, kg: float, farmer_counter_price: float | None = None) -> dict:
        if self.session.kind == "confirm":
            return {"error": "This is a confirmation call. Do not make new offers."}
        if not self.session.gap_week:
            return {"error": "There is no supply gap to fill right now. Do not make an offer."}
        limits = services.get_limits(self.store, crop)
        crop_id = limits.crop
        harvest = self.store.get("harvests", f"h-{self.session.farmer['id']}-{crop_id}")
        hw = fc.week_index(harvest["ready_date"], self.settings.plan_start, self.settings.weeks) if harvest else None
        if self.session.farmer.get("type") != "supplier" and harvest and (hw is None or hw <= self.session.gap_week):
            when = f"week {hw}" if hw else "outside the forecast weeks"
            return {"error": f"No offer: this farmer's harvest is ready in {when}, not after the short week "
                             f"({fc.week_label(self.session.gap_week)}), so there is nothing to bring forward. Do not "
                             "make an offer; thank the farmer and close the call."}
        unsaved = self._unsaved_read_back()
        if unsaved:
            return {"error": f"First save the harvest you read back ({round(unsaved[1]):,} kg, ready {unsaved[2]}): if the "
                             "farmer said yes, call record_harvest with those numbers and confirmed_by_farmer true, "
                             "then make the offer."}
        counter = float(farmer_counter_price) if farmer_counter_price else None
        rung = self.session.rung_index.get(crop_id, -1)
        decision = rules_engine.check_offer(limits, rung, float(kg), counter)
        self.session.rung_index[crop_id] = decision.rung_index
        if decision.decision != "invalid":
            self.session.checked_kg[crop_id] = float(kg)
        if decision.price is not None and decision.decision != "invalid":
            # The escalate decision hands back the ceiling as the best price the agent may still say.
            self.session.quoted_prices.setdefault(crop_id, set()).add(decision.price)
            self.session.first_offer.setdefault(crop_id, decision.price)
        if counter:
            self.session.last_counter[crop_id] = counter
        current = self.session.first_offer.get(crop_id)
        self.last_ui = {"rail": {
            "floor": limits.floor, "reference": limits.reference, "ceiling": limits.ceiling,
            "offer": decision.price if counter is None else current, "counter": counter,
            "kg": round(float(kg)), "decision": decision.decision, "allowed": decision.allowed,
            "currency": limits.currency,
        }}
        return {
            "decision": decision.decision, "allowed": decision.allowed,
            "price_per_kg": decision.price, "currency": limits.currency,
            "reference_price": limits.reference, "premium_pct": decision.premium_pct,
            "is_best_price": decision.at_ceiling, "reason": decision.reason,
            "deliver_week": fc.week_label(self.session.gap_week),
        }

    def _tool_save_offer(self, crop: str, kg: float, price_per_kg: float, escalate: bool = False,
                         farmer_requested_price: float | None = None) -> dict:
        if self.session.kind == "confirm":
            return {"error": "This is a confirmation call. Do not save new offers."}
        crop_id = _crop_id(crop)
        kg = _volume(kg)
        price = round(float(price_per_kg), 2)
        quoted = self.session.quoted_prices.get(crop_id, set())
        negotiation = {"first_offer": self.session.first_offer.get(crop_id),
                       "counter": self.session.last_counter.get(crop_id),
                       "rung": self.session.rung_index.get(crop_id, 0)}
        if escalate:
            requested = float(farmer_requested_price or self.session.last_counter.get(crop_id) or price)
            offer = services.create_offer(
                self.store, self.settings, farmer=self.session.farmer, crop=crop_id, kg=float(kg),
                price=max(quoted) if quoted else price, deliver_week=self.session.gap_week,
                call_id=self.session.call_id, status="escalated", requested_price=requested,
                negotiation={**negotiation, "escalated": True})
            self.session.saved_offer_ids.append(offer["id"])
            self.last_ui = {"offer_saved": {"status": "escalated", "kg": offer["kg"]}}
            return {"saved": True, "status": "escalated",
                    "say": "Tell the farmer the planner will review the request and call back. "
                           "Nothing is agreed yet."}
        if price not in quoted:
            return {"error": "That price was not returned by check_offer on this call. "
                             "Call check_offer and use its price."}
        if kg > self.session.checked_kg.get(crop_id, 0) + 0.5:
            return {"error": "You are saving more kilograms than the volume check_offer priced. Call check_offer "
                             "again with this volume, then save."}
        offer = services.create_offer(self.store, self.settings, farmer=self.session.farmer, crop=crop_id,
                                      kg=float(kg), price=price, deliver_week=self.session.gap_week,
                                      call_id=self.session.call_id, negotiation=negotiation)
        self.session.saved_offer_ids.append(offer["id"])
        self.last_ui = {"offer_saved": {"status": "pending", "kg": offer["kg"], "price": offer["price_per_kg"]}}
        return {"saved": True, "status": "pending", "offer_id": offer["id"], "kg": offer["kg"],
                "price_per_kg": offer["price_per_kg"], "deliver_week": fc.week_label(self.session.gap_week),
                "say": "Repeat the terms and say the cooperative must approve the deal before it is final."}

    def _tool_record_answer(self, question_id: str, answer: str) -> dict:
        question = next((q for q in self.session.questions if q["id"] == str(question_id).strip("[] ")), None)
        if not question:
            return {"error": "No extra question has that id on this call. Use an id from your instructions."}
        try:
            value = parse_answer(question, answer)
        except AgentProfileError as e:
            return {"error": str(e)}
        self.session.answers[question["id"]] = {"question": question["text"], "type": question["type"], "answer": value}
        self.store.set("calls", self.session.call_id, {"answers": dict(self.session.answers)}, merge=True)
        self.last_ui = {"answer": {"question": question["text"], "answer": value}}
        left = [q["id"] for q in self.session.questions if q["id"] not in self.session.answers]
        return {"saved": True, "answer": value, "questions_left": left}

    def _set_consent(self, value) -> None:
        """A refusal stays a refusal: once the farmer said no, nothing the model says later can turn it into a yes."""
        if self.session.consent is None:
            self.session.consent_at = services.now_iso()
        self.session.consent = bool(value) and self.session.consent is not False

    def _tool_record_consent(self, transcript_consent: bool) -> dict:
        # finish_call keeps the transcript whenever session.consent is true, also when the call drops later.
        self._set_consent(transcript_consent)
        self.last_ui = {"consent": self.session.consent}
        return {"ok": True, "say": "Carry on with the call. Do not ask the consent question again."}

    def _tool_end_call(self, outcome: str, summary: str, transcript_consent: bool) -> dict:
        unsaved = self._unsaved_read_back()
        if unsaved and not self.session.end_refused and outcome == "completed":
            # Refused once only, so a call can never be held open by this: the second end_call always ends it,
            # and the read-back stays on the call (harvest_read_back) for the planner to confirm by hand.
            self.session.end_refused = True
            return {"ended": False, "error": f"Not ended yet: you read back {round(unsaved[1]):,} kg ready {unsaved[2]} "
                                             "but never saved it. If the farmer said yes to that read-back, call "
                                             "record_harvest with the same numbers and confirmed_by_farmer true, then "
                                             "call end_call again. If they did not confirm it, call end_call again."}
        self.session.ended = True
        self.session.outcome = outcome if outcome in OUTCOMES else "completed"
        self.session.summary = summary
        self._set_consent(transcript_consent)
        self.last_ui = {"consent": self.session.consent}
        return {"ok": True, "say": "Say goodbye in one short sentence. The line closes after it."}
