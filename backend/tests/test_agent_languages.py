"""The agent's languages: each farmer's own or one for every call, and switching to the farmer's language."""

import pytest

from app import agent_profile, live_session, prompt


def test_defaults_each_farmers_own_language_and_switching_on():
    p = agent_profile.normalize_persona({})
    assert p["language_mode"] == "farmer" and p["switch"] is True and p["also_speaks"] == []
    assert agent_profile.call_language(p, "Javanese", "Bahasa Indonesia") == "Javanese"
    assert "Bahasa Indonesia" in agent_profile.switch_languages(p, "Javanese")


def test_fixed_language_and_a_short_switch_list():
    p = agent_profile.normalize_persona({"language_mode": "fixed", "language": "Bahasa Indonesia",
                                         "also_speaks": ["Javanese", "English"]})
    assert agent_profile.call_language(p, "Sundanese", "English") == "Bahasa Indonesia"
    assert agent_profile.switch_languages(p, "Bahasa Indonesia") == ["Javanese", "English"]
    rule = agent_profile.language_rule("Bahasa Indonesia", ["Javanese", "English"])
    assert "Start in Bahasa Indonesia" in rule and "Javanese, English" in rule


def test_no_switching_keeps_one_language():
    p = agent_profile.normalize_persona({"switch": False})
    assert agent_profile.switch_languages(p, "Thai") is None
    assert agent_profile.language_rule("Thai", None).startswith("- Speak only Thai")


def test_bad_language_settings_are_refused():
    with pytest.raises(agent_profile.AgentProfileError):
        agent_profile.normalize_persona({"language_mode": "fixed", "language": "Klingon"})
    with pytest.raises(agent_profile.AgentProfileError):
        agent_profile.normalize_persona({"also_speaks": ["Klingon"]})
    with pytest.raises(agent_profile.AgentProfileError):
        agent_profile.normalize_persona({"language_mode": "sometimes"})


def test_prompt_and_speech_hint_follow_the_settings(settings):
    farmer = {"id": "f1", "name": "Pak Uji", "language": "Javanese", "crop": "palm"}
    camp = {"persona": {"language_mode": "fixed", "language": "Bahasa Indonesia", "switch": True, "also_speaks": ["Javanese"]}}
    text = prompt.build_system_instruction(settings, farmer, "collect", None, campaign=camp)
    assert "Start in Bahasa Indonesia" in text and "Javanese" in text
    assert live_session.stt_language_codes("bahasa indonesia", ["Javanese"]) == ["id-ID", "jv-ID"]
    plain = prompt.build_system_instruction(settings, farmer, "collect", None, campaign={"persona": {"switch": False}})
    assert "Speak only Javanese" in plain
