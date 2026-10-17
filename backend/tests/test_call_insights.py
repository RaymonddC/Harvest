"""Call insights: Gemini's summary and sentiment after a call, only with consent; a negative call is a churn signal."""

import json

from app import call_insights, crm, gemini_text, services


class Resp:
    def __init__(self, data):
        self.text = json.dumps(data)


def farmer(store):
    return next(f for f in store.list("farmers") if f.get("type", "farmer") == "farmer")


def finished_call(store, settings, consent=True):
    f = farmer(store)
    cid = services.queue_call(store, f, "collect")
    services.finish_call(store, settings, cid, ended_cleanly=True, outcome="completed", summary="ok", consent=consent,
                         transcript=[{"who": "agent", "text": "Kapan panen?"}, {"who": "farmer", "text": "Minggu depan. Tapi bayarnya telat terus."}])
    return f, cid


def test_insights_are_written_only_with_consent(store, settings):
    seen = []

    def gen(contents, config):
        seen.append(contents)
        return Resp({"summary": "Harvest next week; complains about late payment.", "sentiment": "negative", "score": -0.7,
                     "concerns": ["late payment"]})

    f, cid = finished_call(store, settings, consent=True)
    out = call_insights.analyze(store, settings, cid, generate=gen)
    assert out["sentiment"] == "negative" and out["concerns"] == ["late payment"] and "bayarnya telat" in seen[0]
    assert store.get("calls", cid)["insights"]["score"] == -0.7
    signals = crm.churn_signals(f, None, [store.get("calls", cid)], [], [])
    assert any(s["key"] == "sounded_unhappy" and "late payment" in s["text"] for s in signals)
    _, other = finished_call(store, settings, consent=False)
    assert call_insights.analyze(store, settings, other, generate=gen) is None and len(seen) == 1  # nothing sent


def test_bad_answers_are_tidied_and_failures_are_quiet(store, settings):
    _, cid = finished_call(store, settings)
    out = call_insights.analyze(store, settings, cid, generate=lambda c, k: Resp({"summary": "x", "sentiment": "angry", "score": 9, "concerns": list("abcdef")}))
    assert out["sentiment"] == "neutral" and out["score"] == 1.0 and len(out["concerns"]) == 3

    def boom(c, k):
        raise RuntimeError("quota")
    assert call_insights.analyze(store, settings, cid, generate=boom) is None


def test_a_retired_text_model_falls_back(settings, monkeypatch):
    class NotFound(Exception):
        code = 404

    asked = []

    class Models:
        def generate_content(self, model, contents, config=None):
            asked.append(model)
            if model != "gemini-2.5-flash":
                raise NotFound("NOT_FOUND")
            return "ok"

    monkeypatch.setattr(gemini_text, "_client", type("C", (), {"models": Models()})())
    monkeypatch.setattr(gemini_text, "_working", None)
    import dataclasses
    s = dataclasses.replace(settings, text_model="gemini-retired")
    assert gemini_text.generate(s, "hi") == "ok" and asked == ["gemini-retired", "gemini-2.5-flash"]
    assert gemini_text.generate(s, "hi") == "ok" and asked[-1] == "gemini-2.5-flash" and len(asked) == 3
