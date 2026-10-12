import json
from pathlib import Path

from app import live_session

WEB = Path(__file__).resolve().parents[2] / "web"


def test_the_sample_call_is_ordered_and_every_clip_exists():
    sample = json.loads((WEB / "samples" / "gap-fill.json").read_text())
    times = [e["t"] for e in sample["events"]]
    assert times == sorted(times)
    clips = [e["audio"] for e in sample["events"] if "audio" in e]
    assert sample["audio"] is True and clips
    for clip in clips:
        assert (WEB / clip).stat().st_size > 1000, clip
    assert {e["who"] for e in sample["events"] if "audio" in e} == {"agent", "farmer"}
    assert sample["events"][-1]["msg"]["type"] == "ended"


def test_every_stand_in_farmer_line_has_a_16khz_clip():
    import wave

    for line in json.loads((WEB / "samples" / "farmer-lines.json").read_text()):
        with wave.open(str(WEB / line["audio"]), "rb") as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2), line["audio"]


def test_the_vertex_token_is_used_only_when_set_with_vertex(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "some-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("VERTEX_ACCESS_TOKEN", "not-a-real-token")
    client = live_session.genai_client()
    assert client.vertexai is True
    assert client._api_client._credentials.token == "not-a-real-token"
