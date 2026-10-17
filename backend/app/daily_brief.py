"""The daily brief: once a day Gemini reads what happened in the last 24 hours and keeps the planner's task list up to date.

Run by the hourly job once a day from 07:00 WIB (marker `brief_day` on campaign "current"), or now from the Overview
("Write today's brief"). It gathers the facts the app already holds:
  calls        made, answered, not reached, and the summaries and concerns of calls the farmer agreed to keep
               (call_insights.py; nothing from a call without consent, PDP Law)
  answers      harvests saved, offers made, approved or waiting, deliveries weighed
  open issues  open complaints, unpaid deliveries, follow-ups due, the forecast weeks that are short
  open tasks   the tasks an earlier brief created and nobody has ticked off yet
and asks Gemini for a short summary and the task changes: new tasks (a farmer, what to do, in how many days) and the
earlier tasks that are now done. New tasks are notes of kind "task" by "Daily brief" with a follow-up date, so they
show on the farmer's card and in "What to do next" when due; one open brief task per farmer at most. Only farmers in
the facts can get a task, and at most MAX_NEW a day. The brief itself is saved in collection "briefs", one per day.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from google.genai import types

from . import crm, gemini_text
from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

BY = "Daily brief"
MAX_NEW = 8
HOUR = 7  # local time (WIB) the hourly job writes the brief
TZ = dt.timezone(dt.timedelta(hours=7), "WIB")
NOT_REACHED = crm.NOT_REACHED

PROMPT = """You are the assistant of the planner at a palm-oil mill cooperative. An AI agent phones smallholder farmers
to learn their coming harvest and to offer a price. Below are the facts of the last 24 hours, the open issues and the
open tasks you created on earlier days. Answer in English, as JSON only:
{"summary": "<three to five plain sentences for the planner: what happened, what is going well, what needs attention>",
 "new_tasks": [{"farmer_id": "<an id from the facts>", "text": "<one short action, starting with a verb, without the farmer's name>", "due_in_days": <0 to 7>}],
 "done_task_ids": ["<id of an open task the facts show is now done or no longer needed>"]}
Make a task only for something a person should do (call back, sort out a payment, answer a complaint, check a farmer
who sounded unhappy or stopped answering). At most %d new tasks, the most important first; none for a farmer who
already has an open task. Use only farmer ids that appear in the facts. Use plain words, no figures you were not given."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "new_tasks": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "farmer_id": {"type": "STRING"}, "text": {"type": "STRING"}, "due_in_days": {"type": "INTEGER"}},
            "required": ["farmer_id", "text", "due_in_days"]}},
        "done_task_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "new_tasks", "done_task_ids"],
}


def _when(doc: dict, *keys: str) -> dt.datetime | None:
    for k in keys:
        try:
            t = dt.datetime.fromisoformat(str(doc.get(k)))
        except (TypeError, ValueError):
            continue
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    return None


def facts(store: Store, now: dt.datetime) -> dict:
    """What Gemini reads: the last 24 hours, the open issues and the open brief tasks (farmers by id and name)."""
    since = now - dt.timedelta(hours=24)
    today = now.astimezone(TZ).date().isoformat()
    names = {f["id"]: f.get("name", f["id"]) for f in store.list("farmers")}
    who = lambda fid: {"farmer_id": fid, "name": names.get(fid, fid)}  # noqa: E731
    recent = lambda docs, *keys: [d for d in docs if (t := _when(d, *keys)) and t >= since]  # noqa: E731

    calls = [c for c in recent(store.list("calls"), "ended_at", "started_at", "created_at") if c.get("farmer_id") in names]
    call_rows = []
    for c in calls:
        row = {**who(c["farmer_id"]), "kind": c.get("kind"), "status": c.get("status"), "outcome": c.get("outcome")}
        ins = c.get("insights") or {}
        if c.get("consent") and ins:  # only what the farmer agreed to keep
            row.update(summary=ins.get("summary"), sentiment=ins.get("sentiment"), concerns=ins.get("concerns"))
        call_rows.append(row)
    offers = store.list("offers")
    notes = store.list("notes")
    out = {
        "today": today,
        "calls": call_rows,
        "calls_not_reached": sum(1 for c in calls if c.get("status") in NOT_REACHED or c.get("outcome") in NOT_REACHED),
        "harvest_answers": [{**who(h["farmer_id"]), "kg": h.get("kg"), "ready_date": h.get("ready_date"), "confidence": h.get("confidence")}
                           for h in recent(store.list("harvests"), "updated_at") if h.get("farmer_id") in names],
        "offers_new": [{**who(o["farmer_id"]), "kg": o.get("kg"), "status": o.get("status")}
                       for o in recent(offers, "created_at") if o.get("farmer_id") in names],
        "offers_waiting": sum(1 for o in offers if o.get("status") in ("pending", "escalated")),
        "deliveries": [{**who(d["farmer_id"]), "net_kg": d.get("net_kg"), "paid": bool(d.get("paid"))}
                       for d in recent(store.list("deliveries"), "created_at", "date") if d.get("farmer_id") in names],
        "unpaid_deliveries": [{**who(d["farmer_id"]), "date": d.get("date"), "amount": d.get("amount")}
                              for d in store.list("deliveries") if not d.get("paid") and d.get("farmer_id") in names][:15],
        "open_complaints": [{**who(n["farmer_id"]), "text": n.get("text")} for n in notes
                            if n.get("kind") == "complaint" and not n.get("done") and n.get("farmer_id") in names][:15],
        "follow_ups_due": [{**who(n["farmer_id"]), "text": n.get("text"), "on": n.get("follow_up_on")} for n in notes
                           if n.get("follow_up_on") and not n.get("done") and n["follow_up_on"] <= today and n.get("by") != BY][:15],
        "short_weeks": [{"crop": r.get("crop"), "week": r.get("week"), "gap_kg": r.get("gap_kg")}
                        for r in store.list("forecast") if r.get("is_gap")][:8],
        "open_tasks": [{"id": n["id"], **who(n["farmer_id"]), "text": n.get("text"), "due": n.get("follow_up_on")}
                       for n in notes if n.get("kind") == "task" and n.get("by") == BY and not n.get("done")],
    }
    return out


def write(store: Store, settings: Settings, now: dt.datetime | None = None, generate=None) -> dict:
    """Write today's brief and update the task list. Returns the saved brief (or an error)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    f = facts(store, now)
    generate = generate or (lambda contents, config: gemini_text.generate(settings, contents, config))
    try:
        resp = generate(f"{PROMPT % MAX_NEW}\n\nFacts:\n{json.dumps(f, ensure_ascii=False, default=str)}",
                        types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA))
        raw = json.loads(getattr(resp, "text", resp) or "{}")
    except Exception as e:  # noqa: BLE001 - the brief is a help; nothing else depends on it
        log.warning("daily brief: Gemini could not write it", exc_info=True)
        return {"error": f"Gemini could not write the brief: {str(e)[:200]}"}

    open_tasks = {t["id"]: t for t in f["open_tasks"]}
    closed = []
    for tid in raw.get("done_task_ids") or []:
        if tid in open_tasks:
            crm.set_note_done(store, tid, True, by=BY)
            closed.append({"id": tid, "name": open_tasks[tid]["name"], "text": open_tasks[tid]["text"]})
    busy = {t["farmer_id"] for tid, t in open_tasks.items() if tid not in {c["id"] for c in closed}}
    known = {r["farmer_id"] for key in ("calls", "harvest_answers", "offers_new", "deliveries", "unpaid_deliveries",
                                        "open_complaints", "follow_ups_due") for r in f[key]}
    today = dt.date.fromisoformat(f["today"])
    added = []
    for t in raw.get("new_tasks") or []:
        fid, text = t.get("farmer_id"), " ".join(str(t.get("text") or "").split())[:300]
        if len(added) >= MAX_NEW or fid not in known or fid in busy or not text:
            continue
        try:
            days = max(0, min(7, int(t.get("due_in_days", 1))))
        except (TypeError, ValueError):
            days = 1
        note = crm.add_note(store, fid, "task", text, follow_up_on=(today + dt.timedelta(days=days)).isoformat(), by=BY)
        busy.add(fid)
        added.append({"id": note["id"], "farmer_id": fid, "name": note["farmer_name"], "text": text, "due": note["follow_up_on"]})

    earlier = store.get("briefs", f["today"]) or {}  # written again today: keep what the first run did
    gone = {c["id"] for c in closed}
    added = [t for t in earlier.get("tasks_added") or [] if t["id"] not in gone] + added
    closed = (earlier.get("tasks_done") or []) + closed
    brief = {"date": f["today"], "summary": " ".join(str(raw.get("summary") or "").split())[:1200],
             "tasks_added": added, "tasks_done": closed,
             "counts": {"calls": len(f["calls"]), "not_reached": f["calls_not_reached"], "harvests": len(f["harvest_answers"]),
                        "offers": len(f["offers_new"]), "deliveries": len(f["deliveries"])},
             "made_at": now.isoformat(timespec="seconds")}
    store.set("briefs", f["today"], brief)
    return {**brief, "id": f["today"]}


def due(store: Store, now: dt.datetime) -> bool:
    """True once a day from HOUR o'clock local time, until today's brief is written."""
    local = now.astimezone(TZ)
    return local.hour >= HOUR and not store.get("briefs", local.date().isoformat())
