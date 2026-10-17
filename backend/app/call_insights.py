"""After a call: a short summary for the planner and how the farmer sounded, written by Gemini from the transcript.

Only calls whose farmer agreed to the transcript are read (no transcript is kept otherwise, and none is sent to Gemini:
PDP Law, see DECISIONS.md). The result is saved on the call as `insights`:
  summary    one or two plain sentences: what was agreed, and anything the planner should follow up
  sentiment  positive, neutral or negative (how the farmer sounded about the mill)
  score      -1 (very unhappy) to 1 (very happy)
  concerns   up to three short phrases the farmer raised (price, late payment, transport, ...)
A negative call feeds the farmer's churn signals ("Sounded unhappy on the last call", crm.py).
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from google.genai import types

from . import gemini_text
from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

SENTIMENTS = ("positive", "neutral", "negative")
PROMPT = """You read the transcript of a phone call between an AI assistant calling for a palm-oil mill cooperative and a
smallholder farmer. The call may be in Indonesian or another language. Answer in English, as JSON only:
{"summary": "<one or two plain sentences for the mill's planner: what the farmer said and agreed, and anything to follow up>",
 "sentiment": "positive" | "neutral" | "negative",
 "score": <number from -1 (very unhappy with the mill) to 1 (very happy)>,
 "concerns": ["<short phrase>", ...]}
Judge sentiment by how the farmer sounded about the mill and the deal, not by whether they had a harvest.
"concerns" lists at most three things the farmer raised (for example late payment, low price, transport); [] if none."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "sentiment": {"type": "STRING", "enum": list(SENTIMENTS)},
        "score": {"type": "NUMBER"},
        "concerns": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "sentiment", "score", "concerns"],
}


def _clean(raw: dict) -> dict:
    sentiment = raw.get("sentiment") if raw.get("sentiment") in SENTIMENTS else "neutral"
    try:
        score = max(-1.0, min(1.0, float(raw.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    concerns = [" ".join(str(c).split())[:60] for c in (raw.get("concerns") or []) if str(c).strip()][:3]
    return {"summary": " ".join(str(raw.get("summary") or "").split())[:400], "sentiment": sentiment,
            "score": round(score, 2), "concerns": concerns}


def analyze(store: Store, settings: Settings, call_id: str, generate=None) -> dict | None:
    """Write the insights for one finished call. None when there is nothing to read (no consent, no transcript)."""
    call = store.get("calls", call_id)
    if not call or not call.get("consent") or not call.get("transcript"):
        return None
    lines = "\n".join(f"{'Assistant' if l.get('who') == 'agent' else 'Farmer'}: {l.get('text', '')}" for l in call["transcript"])
    generate = generate or (lambda contents, config: gemini_text.generate(settings, contents, config))
    try:
        resp = generate(f"{PROMPT}\n\nTranscript:\n{lines}",
                        types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA))
        raw = json.loads(getattr(resp, "text", resp) or "{}")
    except Exception:  # noqa: BLE001 - insights are a bonus; the call itself is already saved
        log.warning("call %s: Gemini could not write the call insights", call_id, exc_info=True)
        return None
    out = {**_clean(raw), "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    store.set("calls", call_id, {"insights": out}, merge=True)
    return out
