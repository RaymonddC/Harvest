import pytest

from app import services
from app.prompt import build_system_instruction
from app.tools import CallSession, ToolHandlers


def test_preset_fills_name_voice_and_style_and_bad_values_are_refused(store, settings):
    r = services.set_agent_profile(store, settings, "palm", {"preset": "field_officer"},
                                   [{"text": "Butuh pupuk bulan ini?", "type": "yes_no"}])
    assert r["persona"] == {"preset": "field_officer", "name": "Sari", "voice": "Aoede", "style": "friendly",
                            "language_mode": "farmer", "language": "", "switch": True, "also_speaks": []}
    assert r["questions"][0]["id"].startswith("q-") and r["questions"][0]["type"] == "yes_no"
    for persona, questions, msg in (({"voice": "Robot"}, [], "Unknown voice"),
                                    ({"style": "shouty"}, [], "speaking style"),
                                    ({"name": "x" * 40}, [], "at most"),
                                    ({}, [{"text": "a", "type": "essay"}], "question type"),
                                    ({}, [{"text": f"q{i}"} for i in range(6)], "At most")):
        with pytest.raises(services.ServiceError, match=msg):
            services.set_agent_profile(store, settings, "palm", persona, questions)


def test_the_call_uses_the_campaigns_name_voice_style_and_questions(store, settings):
    services.set_agent_profile(store, settings, "palm", {"name": "Sari", "voice": "Puck", "style": "formal"},
                               [{"text": "Ada hama di kebun?", "type": "text"}])
    camp = services.get_campaign(store, settings, "palm")
    farmer = store.get("farmers", "f01")
    text = build_system_instruction(settings, farmer, "collect", 3, campaign=camp)
    assert "Halo, saya Sari, asisten AI yang menelepon untuk" in text  # the name, and still says it is an AI
    assert "Your name is Sari" in text and "Polite and formal" in text
    qid = camp["questions"][0]["id"]
    assert f'[{qid}] "Ada hama di kebun?"' in text and "record_answer" in text
    assert services.settings_for_crop(store, settings, "palm").voice_name == "Puck"
    confirm = build_system_instruction(settings, farmer, "confirm", None, campaign=camp,
                                       offer={"kg": 1, "crop": "palm", "price_per_kg": 1, "deliver_week": 3})
    assert qid not in confirm  # extra questions are for harvest calls only


def test_record_answer_saves_typed_answers_and_the_csv_lists_them(store, settings):
    services.set_agent_profile(store, settings, "palm", {}, [
        {"text": "Butuh pupuk?", "type": "yes_no"}, {"text": "Berapa pohon?", "type": "number"},
        {"text": "Ada masalah?", "type": "text"}])
    qs = services.get_campaign(store, settings, "palm")["questions"]
    call_id = services.queue_call(store, store.get("farmers", "f01"), "collect")
    h = ToolHandlers(store, settings, CallSession(call_id=call_id, farmer=store.get("farmers", "f01"),
                                                  kind="collect", questions=qs))
    assert h.dispatch("record_answer", {"question_id": qs[0]["id"], "answer": "Iya"})["answer"] == "yes"
    assert "error" in h.dispatch("record_answer", {"question_id": qs[1]["id"], "answer": "banyak"})
    assert h.dispatch("record_answer", {"question_id": qs[1]["id"], "answer": "sekitar 120 pohon"})["answer"] == "120"
    left = h.dispatch("record_answer", {"question_id": f"[{qs[2]['id']}]", "answer": "Hujan terus"})
    assert left["questions_left"] == []
    assert "error" in h.dispatch("record_answer", {"question_id": "q-nope0000", "answer": "x"})
    answers = store.get("calls", call_id)["answers"]
    assert [a["answer"] for a in answers.values()] == ["yes", "120", "Hujan terus"]
    csv = services.answers_csv(store, settings)
    assert "Butuh pupuk?,yes" in csv and "Pak Rahmat" in csv


def test_new_languages_have_the_named_opening(settings):
    for lang, expect in (("Thai", "ฉันชื่อ Sari"), ("Vietnamese", "tôi là Sari"), ("Filipino", "ako si Sari"),
                         ("English", "this is Sari, an AI assistant")):
        camp = {"persona": {"name": "Sari"}}
        text = build_system_instruction(settings, {"name": "Pak A", "language": lang, "crop": "palm"}, "collect", None,
                                        campaign=camp)
        assert expect in text, lang
