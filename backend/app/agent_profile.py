"""What each campaign's agent sounds like and what extra it asks.

A campaign (one per crop) can set a persona - a name, one of Gemini's built-in voices and a speaking
style, or one of the ready-made presets - and up to MAX_QUESTIONS questions of its own. The agent asks
those on harvest calls, after the harvest is confirmed and before any offer, and saves each answer
with record_answer. The persona never changes the guardrails: the agent still says it is an AI first,
and prices still come only from check_offer.
"""

from __future__ import annotations

import re

from .store import new_id

# The languages a call can be in (the farmer form offers the same list; services.LANGUAGES).
LANGUAGES = ("Bahasa Indonesia", "Bahasa Malaysia", "English", "Javanese", "Sundanese", "Thai", "Vietnamese", "Filipino")

# Gemini Live's built-in voices (the same names on the Gemini API and Vertex AI).
VOICES: dict[str, str] = {
    "Kore": "Female · firm",
    "Aoede": "Female · warm",
    "Leda": "Female · youthful",
    "Zephyr": "Female · bright",
    "Charon": "Male · calm, informative",
    "Orus": "Male · firm",
    "Puck": "Male · upbeat",
    "Fenrir": "Male · lively",
}

STYLES: dict[str, dict[str, str]] = {
    "friendly": {"label": "Friendly",
                 "rule": "Warm and friendly, like a field officer the farmer knows. Use a little small talk only if the "
                         "farmer starts it, then come back to the questions."},
    "formal": {"label": "Formal",
               "rule": "Polite and formal. Use the respectful forms of address of the language (for example Bapak/Ibu), "
                       "full sentences, no slang."},
    "brief": {"label": "Brief",
              "rule": "Brief and efficient. Keep every sentence short, skip small talk, and move to the next question "
                      "as soon as you have an answer."},
}

PRESETS: dict[str, dict[str, str]] = {
    "field_officer": {"label": "Friendly field officer", "name": "Sari", "voice": "Aoede", "style": "friendly"},
    "cooperative_clerk": {"label": "Formal cooperative clerk", "name": "Rudi", "voice": "Charon", "style": "formal"},
    "quick_check": {"label": "Quick check-in", "name": "", "voice": "Kore", "style": "brief"},
}

QUESTION_TYPES: dict[str, str] = {"text": "Free text", "yes_no": "Yes or no", "number": "Number"}
MAX_QUESTIONS = 5
MAX_NAME = 30
MAX_QUESTION_LEN = 200

# A new campaign's agent (and the demo's): English on every call, switching to the farmer's language when they answer
# in it. Change it per campaign on the Agent page.
NEW_CAMPAIGN_PERSONA = {"preset": "", "name": "", "voice": "", "style": "", "language_mode": "fixed", "language": "English",
                        "switch": True, "also_speaks": []}

DEFAULT_PERSONA = {"preset": "", "name": "", "voice": "", "style": "", "language_mode": "farmer", "language": "",
                   "switch": True, "also_speaks": []}


class AgentProfileError(ValueError):
    pass


def options() -> dict:
    """Everything the Agent page offers, so the dashboard and the server use the same lists."""
    return {"voices": VOICES, "styles": {k: v["label"] for k, v in STYLES.items()}, "presets": PRESETS,
            "question_types": QUESTION_TYPES, "max_questions": MAX_QUESTIONS, "languages": list(LANGUAGES)}


def normalize_persona(raw: dict | None) -> dict:
    raw = raw or {}
    preset = str(raw.get("preset") or "")
    if preset and preset not in PRESETS:
        raise AgentProfileError(f"Unknown persona preset {preset!r}.")
    base = PRESETS.get(preset, {})
    name = " ".join(str(raw.get("name", base.get("name", "")) or "").split())
    if len(name) > MAX_NAME or re.search(r"[<>{}\[\]]", name):
        raise AgentProfileError(f"The agent's name must be at most {MAX_NAME} plain characters.")
    voice = str(raw.get("voice", base.get("voice", "")) or "")
    if voice and voice not in VOICES:
        raise AgentProfileError(f"Unknown voice {voice!r}. Use one of: {', '.join(VOICES)}.")
    style = str(raw.get("style", base.get("style", "")) or "")
    if style and style not in STYLES:
        raise AgentProfileError(f"Unknown speaking style {style!r}. Use one of: {', '.join(STYLES)}.")
    # Languages: start in each farmer's own language ("farmer") or in one for every call ("fixed"); switch when the
    # farmer answers in another language, to any of also_speaks (empty: any language on the list).
    mode = str(raw.get("language_mode") or "farmer")
    if mode not in ("farmer", "fixed"):
        raise AgentProfileError("Language mode must be farmer or fixed.")
    language = str(raw.get("language") or "")
    if mode == "fixed" and language not in LANGUAGES:
        raise AgentProfileError(f"Pick the call language. Use one of: {', '.join(LANGUAGES)}.")
    also = [x for x in dict.fromkeys(raw.get("also_speaks") or []) if x]
    bad = [x for x in also if x not in LANGUAGES]
    if bad:
        raise AgentProfileError(f"Unknown language {bad[0]!r}. Use one of: {', '.join(LANGUAGES)}.")
    return {"preset": preset, "name": name, "voice": voice, "style": style, "language_mode": mode,
            "language": language if mode == "fixed" else "", "switch": raw.get("switch", True) is not False,
            "also_speaks": also}


def call_language(persona: dict | None, farmer_language: str | None, default: str) -> str:
    """The language a call starts in."""
    p = persona or {}
    if p.get("language_mode") == "fixed" and p.get("language") in LANGUAGES:
        return p["language"]
    return farmer_language or default


def switch_languages(persona: dict | None, start: str) -> list[str] | None:
    """The languages the agent may switch to during a call (None: it stays in the start language)."""
    p = persona or {}
    if p.get("switch", True) is False:
        return None
    return [x for x in (p.get("also_speaks") or LANGUAGES) if x != start]


def language_rule(start: str, switch_to: list[str] | None) -> str:
    if not switch_to:
        return (f"- Speak only {start}, in every sentence, even if the farmer answers in another language. Never slip "
                f"into English, not even for prices, numbers, units or the word \"reference\": say them in {start} too.")
    return (f"- Start in {start}. Never slip into English for prices, numbers or units unless English is the language "
            f"of the call.\n- If the farmer answers in another language, or asks for one, and it is one of these: "
            f"{', '.join(switch_to)}, switch to it completely and stay in it for the rest of the call (prices, numbers "
            f"and the read-back included). Do not switch for a single borrowed word; many farmers mix in a few words of "
            f"Indonesian. If they speak a language not on this list, carry on in {start}, slowly and simply.")


def normalize_questions(raw: list | None) -> list[dict]:
    out = []
    for item in raw or []:
        text = " ".join(str((item or {}).get("text", "")).split())
        if not text:
            continue
        if len(text) > MAX_QUESTION_LEN:
            raise AgentProfileError(f"A question can be at most {MAX_QUESTION_LEN} characters.")
        qtype = str(item.get("type") or "text")
        if qtype not in QUESTION_TYPES:
            raise AgentProfileError(f"Unknown question type {qtype!r}. Use one of: {', '.join(QUESTION_TYPES)}.")
        qid = str(item.get("id") or "")
        if not re.fullmatch(r"q-[a-z0-9]{4,12}", qid):
            qid = new_id("q")
        out.append({"id": qid, "text": text, "type": qtype})
    if len(out) > MAX_QUESTIONS:
        raise AgentProfileError(f"At most {MAX_QUESTIONS} questions per campaign.")
    if len({q["id"] for q in out}) != len(out):
        raise AgentProfileError("Two questions have the same id.")
    return out


def profile_of(campaign: dict | None) -> dict:
    """The persona and questions a campaign document holds (defaults when it has none)."""
    c = campaign or {}
    persona = {**DEFAULT_PERSONA, **{k: v for k, v in (c.get("persona") or {}).items() if k in DEFAULT_PERSONA}}
    return {"persona": persona, "questions": list(c.get("questions") or [])}


def persona_rules(persona: dict) -> str:
    """Lines for the system instruction. Empty when the campaign keeps the default agent."""
    lines = []
    if persona.get("name"):
        lines.append(f"Your name is {persona['name']}. Introduce yourself by that name in the opening, and still say "
                     "you are an AI.")
    style = STYLES.get(persona.get("style") or "")
    if style:
        lines.append(f"Speaking style: {style['rule']}")
    return ("Persona:\n- " + "\n- ".join(lines) + "\n") if lines else ""


def questions_stage(questions: list[dict]) -> str:
    """The extra stage for the planner's own questions (harvest calls only)."""
    if not questions:
        return ""
    kinds = {"text": "free answer", "yes_no": "yes or no", "number": "a number"}
    listed = "\n".join(f'   - [{q["id"]}] "{q["text"]}" ({kinds[q["type"]]})' for q in questions)
    return ("Extra questions from the planner. Ask them after the harvest is confirmed (record_harvest saved) and "
            "before any offer, one at a time, in the call's language. Put each into natural words, keep its meaning. "
            "After each answer call record_answer with the question's id in brackets and the answer as the farmer gave "
            "it (for yes or no: \"yes\" or \"no\"; for a number: just the number). If the farmer does not want to "
            "answer one, record \"skipped\" and move on. Do not read the ids aloud.\n" + listed + "\n")


def parse_answer(question: dict, answer: str) -> str:
    """Tidy an answer for its type; raises AgentProfileError when it does not fit."""
    text = " ".join(str(answer or "").split())
    if not text:
        raise AgentProfileError("The answer is empty. Ask again, or record \"skipped\".")
    if text.lower() == "skipped":
        return "skipped"
    if question["type"] == "yes_no":
        low = text.lower()
        yes = {"yes", "y", "ya", "iya", "betul", "benar", "setuju", "oo", "opo", "có", "vâng", "ใช่", "ครับ", "ค่ะ"}
        no = {"no", "n", "tidak", "nggak", "enggak", "bukan", "hindi", "không", "ไม่", "ไม่ใช่"}
        if low in yes:
            return "yes"
        if low in no:
            return "no"
        raise AgentProfileError('For this question record "yes" or "no".')
    if question["type"] == "number":
        m = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(" ", ""))
        if not m:
            raise AgentProfileError("For this question record just the number the farmer said.")
        return m.group(0).replace(",", ".")
    return text[:500]
