"""The six tools the voice model can call, and their handlers.

Each call gets its own ToolHandlers bound to one farmer, so the model can never
read or write another farmer's records. Handlers return two things: the result the
model sees (never the floor or ceiling) and, separately, `last_ui`, a richer payload
for the call screen (captured answers, the check_offer price rail).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from . import forecast as fc
from . import rules_engine, services
from .config import Settings
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
    saved_offer_ids: list[str] = field(default_factory=list)


def _weekday_label(date: dt.date, settings: Settings) -> str:
    w = fc.week_index(date, settings.plan_start, settings.weeks)
    return f"{fc.week_label(w) if w else 'Later'} · {date:%a}"


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
                             confirmed_by_farmer: bool, confidence: str = "firm") -> dict:
        crop_id = normalize_crop(crop)
        kg = float(kg)
        try:
            date = dt.date.fromisoformat(str(ready_date)[:10])
        except ValueError:
            return {"error": "ready_date must be a date in YYYY-MM-DD form."}
        confidence = "unsure" if confidence == "unsure" else "firm"
        self.last_ui = {"captured": {"crop": crop_label(crop_id), "kg": round(kg),
                                     "ready": _weekday_label(date, self.settings),
                                     "confidence": confidence.title(),
                                     "status": "saved" if confirmed_by_farmer else "waiting"}}
        if not confirmed_by_farmer:
            return {"saved": False, "status": "waiting_for_read_back",
                    "read_back": f"{round(kg):,} kg of {crop_label(crop_id)}, ready on {date:%A %d %B}.",
                    "say": "Read this back in the farmer's language and ask if it is right. If they "
                           "say yes, call record_harvest again with confirmed_by_farmer true."}
        result = services.record_harvest(self.store, self.settings, self.session.farmer["id"], crop_id,
                                         kg, date.isoformat(), self.session.call_id, confidence)
        return {"saved": True, **result}

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
        counter = float(farmer_counter_price) if farmer_counter_price else None
        rung = self.session.rung_index.get(crop_id, -1)
        decision = rules_engine.check_offer(limits, rung, float(kg), counter)
        self.session.rung_index[crop_id] = decision.rung_index
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
        crop_id = normalize_crop(crop)
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
        offer = services.create_offer(self.store, self.settings, farmer=self.session.farmer, crop=crop_id,
                                      kg=float(kg), price=price, deliver_week=self.session.gap_week,
                                      call_id=self.session.call_id, negotiation=negotiation)
        self.session.saved_offer_ids.append(offer["id"])
        self.last_ui = {"offer_saved": {"status": "pending", "kg": offer["kg"], "price": offer["price_per_kg"]}}
        return {"saved": True, "status": "pending", "offer_id": offer["id"], "kg": offer["kg"],
                "price_per_kg": offer["price_per_kg"], "deliver_week": fc.week_label(self.session.gap_week),
                "say": "Repeat the terms and say the cooperative must approve the deal before it is final."}

    def _tool_end_call(self, outcome: str, summary: str, transcript_consent: bool) -> dict:
        self.session.ended = True
        self.session.outcome = outcome if outcome in OUTCOMES else "completed"
        self.session.summary = summary
        self.session.consent = bool(transcript_consent)
        self.last_ui = {"consent": self.session.consent}
        return {"ok": True, "say": "Say goodbye in one short sentence. The line closes after it."}
