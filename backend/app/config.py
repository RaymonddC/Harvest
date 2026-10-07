"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def next_monday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    days = (7 - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=days)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_phone(raw: str) -> str:
    """Digits only, with a leading '+' - so "+62 810 0000 1000" (however it's stored
    or typed) and a REAL_CALL_ALLOWLIST entry compare equal, and Twilio gets strict E.164."""
    return "+" + "".join(c for c in (raw or "") if c.isdigit())


@dataclass(frozen=True)
class Settings:
    store_backend: str  # "memory" or "firestore"
    gcp_project: str | None
    live_model: str
    text_model: str
    voice_name: str
    mill_name: str
    planner_name: str
    demo_language: str
    demo_crop: str
    plan_start: dt.date
    weeks: int
    target_kg_per_week: int
    gap_tolerance: float  # a week is a gap when expected < target * (1 - tolerance)
    max_call_attempts: int
    max_call_seconds: int
    caption_translate_to: str | None  # e.g. "English"; None turns caption translation off
    planner_token: str | None
    seed_on_start: bool
    static_dir: Path | None
    cors_origins: tuple[str, ...]
    firebase_web_config: str | None  # JSON string, passed to the dashboard

    # VA-8 stretch goal: the real phone channel. All four must be set to dial out;
    # see services.twilio_ready and DECISIONS.md's "Adding a Twilio channel".
    twilio_account_sid: str | None
    twilio_auth_token: str | None
    twilio_from_number: str | None
    public_base_url: str | None  # this service's own https URL, e.g. the Cloud Run URL

    # Safety gate on top of Twilio being configured at all: dial_now() still refuses
    # every real call unless BOTH of these allow it. Deliberately env-only, not a
    # dashboard toggle - nothing to misclick live in front of an audience.
    real_calls_enabled: bool
    real_call_allowlist: tuple[str, ...]  # E.164, normalized; only these may ever be dialed


@lru_cache
def get_settings() -> Settings:
    plan_start_raw = os.environ.get("PLAN_START")
    plan_start = dt.date.fromisoformat(plan_start_raw) if plan_start_raw else next_monday()

    static_raw = os.environ.get("STATIC_DIR")
    if static_raw:
        static_dir: Path | None = Path(static_raw)
    else:
        candidate = Path(__file__).resolve().parents[2] / "web"
        static_dir = candidate if candidate.is_dir() else None

    store_backend = os.environ.get("STORE_BACKEND", "memory").lower()
    return Settings(
        store_backend=store_backend,
        gcp_project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        live_model=os.environ.get("LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-09-2025"),
        text_model=os.environ.get("TEXT_MODEL", "gemini-2.5-flash"),
        voice_name=os.environ.get("VOICE_NAME", "Kore"),
        mill_name=os.environ.get("MILL_NAME", "Koperasi Sawit Maju"),
        planner_name=os.environ.get("PLANNER_NAME", "Dewi"),
        demo_language=os.environ.get("DEMO_LANGUAGE", "Bahasa Indonesia"),
        demo_crop=os.environ.get("DEMO_CROP", "palm"),
        plan_start=plan_start,
        weeks=int(os.environ.get("FORECAST_WEEKS", "5")),
        target_kg_per_week=int(os.environ.get("TARGET_KG_PER_WEEK", "100000")),
        gap_tolerance=float(os.environ.get("GAP_TOLERANCE", "0.2")),
        max_call_attempts=int(os.environ.get("MAX_CALL_ATTEMPTS", "2")),
        max_call_seconds=int(os.environ.get("MAX_CALL_SECONDS", "360")),
        caption_translate_to=os.environ.get("CAPTION_TRANSLATE_TO", "English") or None,
        planner_token=os.environ.get("PLANNER_TOKEN") or None,
        seed_on_start=_bool("SEED_ON_START", store_backend == "memory"),
        static_dir=static_dir,
        cors_origins=tuple(
            o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()
        ),
        firebase_web_config=os.environ.get("FIREBASE_WEB_CONFIG") or None,
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID") or None,
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN") or None,
        twilio_from_number=os.environ.get("TWILIO_FROM_NUMBER") or None,
        public_base_url=os.environ.get("PUBLIC_BASE_URL") or None,
        real_calls_enabled=_bool("REAL_CALLS_ENABLED", False),
        real_call_allowlist=tuple(
            normalize_phone(n) for n in os.environ.get("REAL_CALL_ALLOWLIST", "").split(",") if n.strip()
        ),
    )
