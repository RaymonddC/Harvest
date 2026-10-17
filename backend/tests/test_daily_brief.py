"""The daily brief: the facts Gemini reads (consented summaries only), the tasks it may add or close, and the hourly job."""

import dataclasses
import datetime as dt
import json
import types as pytypes

from app import crm, daily_brief, services

NOW = dt.datetime(2026, 10, 20, 1, 30, tzinfo=dt.timezone.utc)  # 08:30 WIB


def _call(store, fid, consent, **kw):
    return store.add("calls", {"farmer_id": fid, "kind": "collect", "status": "done", "consent": consent,
                               "ended_at": (NOW - dt.timedelta(hours=2)).isoformat(),
                               "insights": {"summary": "Wants faster payment.", "sentiment": "negative", "concerns": ["late payment"]}, **kw})


def _reply(**raw):
    return lambda contents, config: pytypes.SimpleNamespace(text=json.dumps(raw))


def test_facts_keep_only_what_the_farmer_agreed_to(store):
    a, b = [f["id"] for f in store.list("farmers")[:2]]
    _call(store, a, True)
    _call(store, b, False)
    rows = {r["farmer_id"]: r for r in daily_brief.facts(store, NOW)["calls"]}
    assert rows[a]["summary"] == "Wants faster payment." and "summary" not in rows[b]


def test_write_adds_tasks_for_known_farmers_once_and_closes_done_ones(store, settings):
    a, b = [f["id"] for f in store.list("farmers")[:2]]
    _call(store, a, True)
    old = crm.add_note(store, b, "task", "Ask about transport", follow_up_on="2026-10-19", by=daily_brief.BY)
    out = daily_brief.write(store, settings, NOW, generate=_reply(
        summary="One farmer is unhappy about payment.",
        new_tasks=[{"farmer_id": a, "text": "Call back about the late payment", "due_in_days": 1},
                   {"farmer_id": a, "text": "A second task for the same farmer", "due_in_days": 0},
                   {"farmer_id": "nobody", "text": "Made up", "due_in_days": 0}],
        done_task_ids=[old["id"], "not-a-task"]))
    assert [t["farmer_id"] for t in out["tasks_added"]] == [a] and out["tasks_added"][0]["due"] == "2026-10-21"
    assert [t["id"] for t in out["tasks_done"]] == [old["id"]] and store.get("notes", old["id"])["done"]
    assert store.get("briefs", "2026-10-20")["summary"].startswith("One farmer")
    task = store.get("notes", out["tasks_added"][0]["id"])
    assert task["kind"] == "task" and task["by"] == daily_brief.BY and not task["done"]


def test_a_gemini_failure_saves_nothing(store, settings):
    def boom(contents, config):
        raise RuntimeError("quota")
    assert "error" in daily_brief.write(store, settings, NOW, generate=boom)
    assert not store.get("briefs", "2026-10-20")


def test_the_hourly_job_writes_it_once_a_day_from_seven(store, settings, monkeypatch):
    s = dataclasses.replace(settings, daily_brief=True)
    calls = []
    monkeypatch.setattr(daily_brief, "write", lambda st, se, now: calls.append(now) or st.set("briefs", now.date().isoformat(), {"summary": "x"}))
    wib = dt.timezone(dt.timedelta(hours=7))
    services.scheduled_calls(store, s, dt.datetime(2026, 10, 20, 6, 5, tzinfo=wib))
    assert calls == []
    services.scheduled_calls(store, s, dt.datetime(2026, 10, 20, 7, 5, tzinfo=wib))
    services.scheduled_calls(store, s, dt.datetime(2026, 10, 20, 8, 5, tzinfo=wib))
    assert len(calls) == 1


def test_written_again_the_same_day_keeps_the_first_runs_tasks(store, settings):
    a = store.list("farmers")[0]["id"]
    _call(store, a, True)
    daily_brief.write(store, settings, NOW, generate=_reply(summary="First.", done_task_ids=[],
                                                            new_tasks=[{"farmer_id": a, "text": "Call back", "due_in_days": 0}]))
    out = daily_brief.write(store, settings, NOW, generate=_reply(summary="Second.", new_tasks=[], done_task_ids=[]))
    assert out["summary"] == "Second." and [t["text"] for t in out["tasks_added"]] == ["Call back"]
