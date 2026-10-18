"""Gemini text calls (not the live voice): caption translation, the forecast note, call insights.

Google retires model names, and Vertex AI and AI Studio do not offer the same ones, so the name in TEXT_MODEL can
answer 404 ("not found"). Then the next name in FALLBACK_MODELS is tried, and the first one that works is remembered
for the rest of the process, so a retired name costs one failed request, not one per call.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

FALLBACK_MODELS = ("gemini-2.0-flash-001",)
_working: str | None = None
_client = None


def _not_found(e: Exception) -> bool:
    return getattr(e, "code", None) == 404 or "NOT_FOUND" in str(e)


def _models(settings) -> list[str]:
    first = _working or settings.text_model
    return [first, *[m for m in (settings.text_model, *FALLBACK_MODELS) if m != first]]


def client():
    global _client
    if _client is None:
        from .live_session import genai_client

        _client = genai_client()
    return _client


def generate(settings, contents, config=None):
    """generate_content with the model fallback. Raises the last error when no model works."""
    global _working
    last = None
    for model in _models(settings):
        try:
            resp = client().models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:  # noqa: BLE001
            if _not_found(e):
                last = e
                continue
            raise
        if model != _working:
            _working = model
            if model != settings.text_model:
                log.warning("TEXT_MODEL %s is not available; using %s (set TEXT_MODEL to skip the retry)", settings.text_model, model)
        return resp
    raise last or RuntimeError("No Gemini text model is available.")


async def agenerate(settings, contents, config=None):
    """The same, without blocking the event loop."""
    global _working
    last = None
    for model in _models(settings):
        try:
            resp = await client().aio.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:  # noqa: BLE001
            if _not_found(e):
                last = e
                continue
            raise
        if model != _working:
            _working = model
            if model != settings.text_model:
                log.warning("TEXT_MODEL %s is not available; using %s (set TEXT_MODEL to skip the retry)", settings.text_model, model)
        return resp
    raise last or RuntimeError("No Gemini text model is available.")
