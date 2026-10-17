"""The consent notice is fixed wording in the call's language (not translated by the model on the fly)."""
import pytest

from app import services
from app.prompt import NOTICES, RETENTION_DAYS, build_system_instruction, notice_for

ENGLISH = "With your permission, Koperasi Sawit Maju keeps a written transcript"


def instruction(settings, language):
    farmer = {"name": "Pak Wahyu", "language": language, "crop": "palm"}
    return build_system_instruction(settings, farmer, "collect", 3)


def test_every_language_a_farmer_can_have_has_fixed_wording():
    assert set(services.LANGUAGES) == set(NOTICES)  # a new language cannot be added without its notice
    for lang in services.LANGUAGES:
        n = notice_for(lang, "Koperasi Sawit Maju", "Pak Wahyu")
        assert "AI" in n["hello"] and "Koperasi Sawit Maju" in n["hello"], lang   # says it is an AI, and for whom
        assert "Pak Wahyu" in n["ask"] and n["consent"].endswith("?"), lang


@pytest.mark.parametrize("language", services.LANGUAGES)
def test_the_prompt_gives_the_notice_in_the_call_language(settings, language):
    n = notice_for(language, settings.mill_name, "Pak Wahyu")
    text = instruction(settings, language)
    assert n["hello"] in text and n["ask"] in text and n["consent"] in text
    if language != "English":
        assert ENGLISH not in text and "Hello, this is an AI assistant" not in text  # no English to leak into the call


def test_aliases_and_the_default_language(settings):
    assert notice_for("indonesian", "M", "N") == notice_for("Bahasa Indonesia", "M", "N")
    assert notice_for("  BAHASA  indonesia", "M", "N") is not None
    # a farmer with no language of their own gets the default language of the deployment
    text = build_system_instruction(settings, {"name": "Pak X", "crop": "palm"}, "collect", 3)
    assert notice_for(settings.demo_language, settings.mill_name, "Pak X")["consent"] in text


def test_unknown_language_falls_back_to_a_translated_notice(settings):
    assert notice_for("Klingon", "M", "N") is None
    text = instruction(settings, "Klingon")
    assert "With your permission Koperasi Sawit Maju keeps a written transcript" in text and "Say all of it in Klingon" in text


def test_recording_wording_says_what_is_kept_and_for_how_long():
    assert RETENTION_DAYS == 90
    for lang in services.LANGUAGES:
        t = notice_for(lang, "Koperasi Sawit Maju", "Pak Wahyu", recording=True)["consent"]
        assert "90" in t and "Koperasi Sawit Maju" in t, lang
        assert t != notice_for(lang, "Koperasi Sawit Maju", "Pak Wahyu")["consent"], lang


def test_the_notice_addresses_the_farmer_not_bapak_slash_ibu():
    """Read aloud, the written "Bapak/Ibu" sounded like a form; the notice uses the farmer's own form of address."""
    def consent(name, lang="Bahasa Indonesia"):
        return notice_for(lang, "Koperasi Sawit Maju", name, recording=True)["consent"]

    assert "izin Bapak," in consent("Pak Slamet") and "Apakah Bapak setuju?" in consent("Pak Slamet")
    assert "izin Ibu," in consent("Bu Sari") and "Apakah Ibu setuju?" in consent("Bu Sari")
    assert "Anda" in consent("Gary")
    for lang in services.LANGUAGES:
        assert "/" not in consent("Pak Wahyu", lang) and "/" not in consent("Gary", lang), lang


def test_the_opening_is_two_turns_and_the_agent_talks_like_a_person(settings):
    text = instruction(settings, "Bahasa Indonesia")
    assert "in two turns" in text and "Then stop and wait for the answer" in text
    assert "Never start your sentence again from the beginning" in text  # no restarting when the farmer cuts in
    assert "Never say \"FFB\"" in text and "how can I help you" in text
