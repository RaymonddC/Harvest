"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import datetime as dt
import os
import secrets
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
    vad_silence_ms: int  # silence that ends the farmer's turn; shorter means the agent answers sooner
    mill_name: str
    demo_language: str
    demo_crop: str
    plan_start: dt.date
    weeks: int
    target_kg_per_week: int
    gap_tolerance: float  # a week is a gap when expected < target * (1 - tolerance)
    max_call_attempts: int
    max_call_seconds: int
    caption_translate_to: str | None  # e.g. "English"; None turns caption translation off
    auth_required: bool  # False leaves every planner action open (scripts, local experiments)
    jwt_secret: str  # signs sign-in tokens; set it in the cloud or each instance signs differently
    jwt_ttl_seconds: int
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
    # E.164, normalized; only these may ever be dialed. "*" (same convention as
    # CORS_ORIGINS above) means no restriction - every number is allowed. Empty
    # (the default) means none are: a real call needs this set explicitly either way.
    real_call_allowlist: tuple[str, ...]


def _load_dotenv(folders: tuple[Path, ...] | None = None) -> None:
    """Read a local `.env` into the environment. Real environment variables always win, and blank
    values are skipped so a copied `.env.example` does not set anything to the empty string."""
    try:
        from dotenv import dotenv_values
    except ImportError:  # not installed yet: skip .env; real environment variables still work
        return

    here = Path(__file__).resolve()
    for folder in folders or (here.parents[2], here.parents[1]):  # repo root, then backend/
        for key, value in dotenv_values(folder / ".env").items():
            if value and key not in os.environ:
                os.environ[key] = value


@lru_cache
def get_settings() -> Settings:
    if os.environ.get("HARVEST_NO_DOTENV") != "1":  # the tests set this
        _load_dotenv()
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
        live_model=os.environ.get("LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"),
        text_model=os.environ.get("TEXT_MODEL", "gemini-3.8-flash"),
        voice_name=os.environ.get("VOICE_NAME", "Kore"),
        vad_silence_ms=int(os.environ.get("VAD_SILENCE_MS", "400")),
        mill_name=os.environ.get("MILL_NAME", "Koperasi Sawit Maju"),
        demo_language=os.environ.get("DEMO_LANGUAGE", "Bahasa Indonesia"),
        demo_crop=os.environ.get("DEMO_CROP", "palm"),
        plan_start=plan_start,
        weeks=int(os.environ.get("FORECAST_WEEKS", "5")),
        target_kg_per_week=int(os.environ.get("TARGET_KG_PER_WEEK", "100000")),
        gap_tolerance=float(os.environ.get("GAP_TOLERANCE", "0.2")),
        max_call_attempts=int(os.environ.get("MAX_CALL_ATTEMPTS", "2")),
        max_call_seconds=int(os.environ.get("MAX_CALL_SECONDS", "360")),
        caption_translate_to=os.environ.get("CAPTION_TRANSLATE_TO", "English") or None,
        auth_required=_bool("AUTH_REQUIRED", True),
        jwt_secret=os.environ.get("JWT_SECRET") or secrets.token_hex(32),
        jwt_ttl_seconds=int(os.environ.get("JWT_TTL_SECONDS", str(12 * 3600))),
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
            n if n == "*" else normalize_phone(n)
            for n in (n.strip() for n in os.environ.get("REAL_CALL_ALLOWLIST", "").split(","))
            if n
        ),
    )
