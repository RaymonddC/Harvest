"""The farmer relationship around the calls: segments, satisfaction and complaints, churn signals, notes and follow-ups,
and payment of deliveries.

Segments come from what the mill knows about each farmer:
  reliability  share of promised kg delivered (track_record): reliable >= 90%, mixed >= 60%, unreliable below,
               new while there are not yet two recorded weeks
  size         usual kg a week: small under 500, medium under 1,000, large from 1,000
  certified    ISPO or RSPO on record, or not
A campaign can name a segment (campaign "segment"); its calls then go only to farmers in it.

Churn signals say who may be drifting away: stopped answering (the last two agent calls did not reach them),
delivers less than promised (reliability under 60%), unhappy (a low rating or an open complaint), and maybe
selling elsewhere (an approved deal whose delivery week is over with nothing delivered).

Notes (collection "notes") are the planner's own record: a note, a call or visit they made, the farmer's feedback
(with a rating), a complaint or a task (the daily brief writes tasks too, daily_brief.py), each optionally with a
follow-up date. A follow-up is done when ticked off.
"""

from __future__ import annotations

import datetime as dt

from .store import Store

RELIABLE, MIXED = 0.9, 0.6
SMALL, LARGE = 500, 1000
NOTE_KINDS = {"note": "Note", "call": "Call I made", "visit": "Visit", "feedback": "Feedback", "complaint": "Complaint", "task": "To do"}
NOT_REACHED = {"no_answer", "busy", "failed", "canceled", "not_connected", "dropped"}
SEGMENT_KEYS = {"reliability": ("reliable", "mixed", "unreliable", "new"), "size": ("small", "medium", "large"),
                "certified": ("yes", "no")}


class CrmError(ValueError):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------- segments ----------

def segment_of(farmer: dict, reliability: float | None) -> dict:
    if reliability is None:
        rel = "new"
    else:
        rel = "reliable" if reliability >= RELIABLE else "mixed" if reliability >= MIXED else "unreliable"
    kg = float(farmer.get("usual_kg_week") or 0)
    size = "large" if kg >= LARGE else "medium" if kg >= SMALL else "small"
    return {"reliability": rel, "size": size, "certified": "yes" if farmer.get("certification") else "no"}


def check_segment(segment: dict | None) -> dict | None:
    """A campaign's segment, tidied: only known keys and values; empty means everyone."""
    if not segment:
        return None
    out = {}
    for key, value in segment.items():
        if value in (None, "", "any"):
            continue
        if key not in SEGMENT_KEYS or value not in SEGMENT_KEYS[key]:
            raise CrmError(f"Unknown segment {key}={value!r}.")
        out[key] = value
    return out or None


def in_segment(seg: dict, wanted: dict | None) -> bool:
    return not wanted or all(seg.get(k) == v for k, v in wanted.items())


# ---------- churn signals ----------

def churn_signals(farmer: dict, reliability: float | None, calls: list[dict], notes: list[dict], offers: list[dict],
                  today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    out = []
    agent = sorted((c for c in calls if c.get("kind") in ("collect", "gap_fill") and c["status"] not in ("queued", "on_call")),
                   key=lambda c: c.get("ended_at") or c.get("created_at") or "", reverse=True)
    if len(agent) >= 2 and all((c.get("outcome") in NOT_REACHED) or c["status"] == "dropped" for c in agent[:2]) \
            and not any(c.get("outcome") == "withdrawn" for c in agent[:2]):
        out.append({"key": "stopped_answering", "text": "Stopped answering: the last two calls did not reach them"})
    if reliability is not None and reliability < MIXED:
        out.append({"key": "under_delivers", "text": f"Delivers {round(reliability * 100)}% of what they promise"})
    heard = sorted((c for c in calls if (c.get("insights") or {}).get("sentiment")), key=lambda c: c.get("ended_at") or c.get("created_at") or "")
    if heard and heard[-1]["insights"]["sentiment"] == "negative":
        worry = ", ".join(heard[-1]["insights"].get("concerns") or [])
        out.append({"key": "sounded_unhappy", "text": "Sounded unhappy on the last call" + (f" ({worry})" if worry else "")})
    rated = sorted((n for n in notes if n.get("kind") == "feedback" and n.get("rating")), key=lambda n: n.get("at") or "")
    if rated and int(rated[-1]["rating"]) <= 2:
        out.append({"key": "unhappy", "text": f"Unhappy: rated the mill {rated[-1]['rating']} of 5"})
    elif any(n.get("kind") == "complaint" and not n.get("done") for n in notes):
        out.append({"key": "unhappy", "text": "An open complaint"})
    for o in offers:
        start = o.get("deliver_week_start")
        if o.get("status") == "approved" and start and not o.get("delivered_kg"):
            try:
                over = dt.date.fromisoformat(start) + dt.timedelta(days=7) < today
            except ValueError:
                over = False
            if over:
                out.append({"key": "selling_elsewhere", "text": f"Approved deal for the week of {start}, nothing delivered: selling elsewhere?"})
                break
    return out


# ---------- the whole picture for the dashboard ----------

def overview(store: Store, farmer_ids: set[str] | None = None, today: dt.date | None = None) -> dict:
    from . import track_record

    rel = track_record.reliabilities(store)
    calls, notes, offers = {}, {}, {}
    for c in store.list("calls"):
        calls.setdefault(c["farmer_id"], []).append(c)
    for n in store.list("notes"):
        notes.setdefault(n["farmer_id"], []).append(n)
    for o in store.list("offers"):
        offers.setdefault(o.get("farmer_id"), []).append(o)
    farmers = {}
    for f in store.list("farmers"):
        if f.get("type") == "supplier" or (farmer_ids is not None and f["id"] not in farmer_ids):
            continue
        r = rel.get(f["id"])
        farmers[f["id"]] = {"reliability": r, "segment": segment_of(f, r),
                            "churn": churn_signals(f, r, calls.get(f["id"], []), notes.get(f["id"], []),
                                                   offers.get(f["id"], []), today)}
    unpaid = [d for d in store.list("deliveries") if not d.get("paid") and (farmer_ids is None or d["farmer_id"] in farmer_ids)]
    return {"farmers": farmers,
            "unpaid": {"count": len(unpaid), "amount": sum(d.get("amount") or 0 for d in unpaid),
                       "currency": (unpaid[0].get("currency") if unpaid else None) or "IDR"}}


# ---------- notes and follow-ups ----------

def add_note(store: Store, farmer_id: str, kind: str, text: str, rating: int | None = None,
             follow_up_on: str | None = None, by: str | None = None) -> dict:
    farmer = store.get("farmers", farmer_id)
    if not farmer:
        raise CrmError("Farmer not found.")
    if kind not in NOTE_KINDS:
        raise CrmError(f"Unknown kind {kind!r}. Use one of: {', '.join(NOTE_KINDS)}.")
    text = " ".join((text or "").split())
    if not text and kind != "feedback":
        raise CrmError("Write what happened.")
    if len(text) > 1000:
        raise CrmError("A note can be at most 1,000 characters.")
    if rating is not None:
        if kind not in ("feedback", "complaint"):
            rating = None
        elif not 1 <= int(rating) <= 5:
            raise CrmError("A rating is 1 to 5.")
    if kind == "feedback" and rating is None and not text:
        raise CrmError("Give a rating or write what the farmer said.")
    if follow_up_on:
        try:
            follow_up_on = dt.date.fromisoformat(str(follow_up_on)[:10]).isoformat()
        except ValueError as e:
            raise CrmError("The follow-up date must be YYYY-MM-DD.") from e
    doc = {"farmer_id": farmer_id, "farmer_name": farmer.get("name", farmer_id), "kind": kind, "text": text,
           "rating": int(rating) if rating is not None else None, "follow_up_on": follow_up_on or None,
           "done": False, "by": by or "Planner", "at": _now()}
    nid = store.add("notes", doc)
    return {**doc, "id": nid}


def set_note_done(store: Store, note_id: str, done: bool, by: str | None = None) -> dict:
    note = store.get("notes", note_id)
    if not note:
        raise CrmError("Note not found.")
    store.set("notes", note_id, {"done": bool(done), "done_at": _now() if done else None, "done_by": by if done else None}, merge=True)
    return store.get("notes", note_id)


def delete_note(store: Store, note_id: str) -> dict:
    if not store.get("notes", note_id):
        raise CrmError("Note not found.")
    store.delete("notes", note_id)
    return {"deleted": note_id}


# ---------- payment of deliveries ----------

def set_paid(store: Store, delivery_id: str, paid: bool, ref: str | None = None, by: str | None = None) -> dict:
    d = store.get("deliveries", delivery_id)
    if not d:
        raise CrmError("Delivery not found.")
    ref = " ".join((ref or "").split())[:80] or None
    store.set("deliveries", delivery_id, {"paid": bool(paid), "paid_at": _now() if paid else None,
                                           "paid_by": by if paid else None, "payment_ref": ref if paid else None}, merge=True)
    return {**store.get("deliveries", delivery_id), "id": delivery_id}
