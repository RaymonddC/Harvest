"""Call recordings: kept only with consent, in the call's language notice, playable by planners only, deleted after 90 days."""
import array
import contextlib
import dataclasses
import datetime as dt
import io
import json
import os
import time

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import access, live_session
from app.call_audio import AGENT_RATE, CallRecorder, GcsAudioStore, LocalAudioStore, make_audio_store, recording_enabled
from app.main import create_app
from app.prompt import build_system_instruction

from .test_api import FakeLive, audio, content, drain
from .test_auth import DEMO, login


def pcm(seconds, rate, value=3000):
    return array.array("h", [value] * int(seconds * rate)).tobytes()


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ---------- the recorder ----------

def test_the_agent_is_placed_as_it_plays_not_as_it_arrives():
    clock = Clock(); r = CallRecorder(clock)
    clock.t = 0.5; r.add_agent(pcm(2, AGENT_RATE))   # a 2 s piece arrives at 0.5 s: plays 0.5 to 2.5
    clock.t = 0.6; r.add_agent(pcm(2, AGENT_RATE))   # the next piece arrives at once but plays after the first: 2.5 to 4.5
    assert round(r.seconds(), 2) == 4.5
    clock.t = 1.0; r.add_agent(pcm(2, AGENT_RATE))   # a third piece arrives while those two still play: it waits until 4.5 s
    assert round(r.seconds(), 2) == 6.5
    assert r.line_start("agent") == 0.5              # all one stretch of speech, which started playing at 0.5 s
    clock.t = 9.0; r.add_agent(pcm(1, AGENT_RATE))   # after silence: a new turn starting at 9.0 s
    assert r.line_start("agent") == 9.0


def test_a_barge_in_cuts_the_audio_that_had_not_played_yet():
    clock = Clock(); r = CallRecorder(clock)
    clock.t = 0.0; r.add_agent(pcm(6, AGENT_RATE))   # 6 s of speech queued at once
    clock.t = 2.0; r.interrupted()                   # the farmer talks over it after 2 s
    assert round(r.seconds(), 2) == 2.0
    clock.t = 2.5; r.add_agent(pcm(1, AGENT_RATE))   # the agent answers; it plays from 2.5 s, not from 6 s
    assert round(r.seconds(), 2) == 3.5


def test_farmer_speech_start_marks_where_a_line_begins_and_the_file_is_stereo():
    clock = Clock(); r = CallRecorder(clock)
    for i in range(50):                              # 2 s of silence, then 1 s of speech, in 40 ms chunks
        clock.t = 0.04 * (i + 1); r.add_farmer(pcm(0.04, 16000, 0))
    for i in range(25):
        clock.t = 2.0 + 0.04 * (i + 1); r.add_farmer(pcm(0.04, 16000, 4000))
    assert 1.9 < r.line_start("farmer") < 2.1
    clock.t = 3.0; r.add_agent(pcm(1, AGENT_RATE, 2000))
    data, rate = sf.read(io.BytesIO(r.encode()))
    assert rate == 16000 and data.shape[1] == 2
    assert abs(len(data) / rate - 4.0) < 0.2         # farmer to 3 s, agent from 3 s to 4 s
    assert abs(data[: 16000 * 2, 0]).max() < 0.05 and abs(data[16000 * 2 + 2000: 16000 * 3 - 2000, 0]).max() > 0.05   # left = farmer
    assert abs(data[: 16000 * 3 - 2000, 1]).max() < 0.05 and abs(data[16000 * 3 + 2000:, 1]).max() > 0.03             # right = agent


def test_the_local_store_saves_reads_and_forgets_old_files(tmp_path):
    store = LocalAudioStore(tmp_path / "rec")
    assert store.save("call-1", b"abc") == "call-1.mp3" and store.read("call-1") == b"abc" and store.read("nope") is None
    store.save("call-2", b"def")
    old = time.time() - 91 * 86400
    os.utime(tmp_path / "rec" / "call-1.mp3", (old, old))
    assert store.purge(90) == 1 and store.read("call-1") is None and store.read("call-2") == b"def"
    assert store.save("../evil", b"x") == "evil.mp3"   # a call id can never leave the folder


# ---------- a whole call ----------

class TalkingLive(FakeLive):
    def __init__(self, consent=True):
        super().__init__()
        agent_audio = content(model_turn=__import__("google.genai.types", fromlist=["x"]).Content(parts=[
            __import__("google.genai.types", fromlist=["x"]).Part(inline_data=__import__("google.genai.types", fromlist=["x"]).Blob(
                data=pcm(1.0, 24000, 1500), mime_type="audio/pcm"))]))
        self.turns[0] = [self.turns[0][0], self.turns[0][1], agent_audio, content(turn_complete=True)]
        end = self.turns[4][0]
        end.tool_call.function_calls[0].args["transcript_consent"] = consent


@pytest.fixture
def recorded(settings, store, tmp_path, monkeypatch):
    def make(consent=True, folder=True):
        fake = TalkingLive(consent)

        @contextlib.asynccontextmanager
        async def connect(model, config):
            yield fake

        async def no_translate(text, target):
            return None

        monkeypatch.setattr(live_session, "default_connect", connect)
        monkeypatch.setattr(live_session, "make_translator", lambda s: no_translate)
        s = dataclasses.replace(settings, call_audio_dir=(tmp_path / "rec") if folder else None)
        return TestClient(create_app(s, store)), s
    return make


def run(client, store):
    call_id = client.post("/api/farmers/b001/call", json={"kind": "gap_fill"}).json()["call_id"]
    with client.websocket_connect(f"/ws/call/{call_id}") as ws:
        for _ in range(3):
            ws.send_bytes(b"\1\0" * 640)
        events, _ = drain(ws)
    return call_id, store.get("calls", call_id)


def test_a_call_the_farmer_agreed_to_is_recorded_with_line_times(recorded, store, tmp_path):
    client, s = recorded()
    with client:
        call_id, call = run(client, store)
    meta = call["audio"]
    assert meta["name"] == f"{call_id}.mp3" and meta["bytes"] > 1000 and meta["seconds"] >= 1.0
    expires = dt.datetime.fromisoformat(meta["expires_at"]) - dt.datetime.now(dt.timezone.utc)
    assert dt.timedelta(days=89) < expires <= dt.timedelta(days=90)
    assert (tmp_path / "rec" / f"{call_id}.mp3").is_file()
    assert all(isinstance(line["t"], float) for line in call["transcript"])
    assert call["transcript"][0]["who"] == "agent" and call["transcript"][0]["t"] >= 0


def test_no_consent_means_nothing_is_kept(recorded, store, tmp_path):
    client, s = recorded(consent=False)
    with client:
        call_id, call = run(client, store)
    assert call["consent"] is False and "audio" not in call and call["transcript"] is None
    assert not list((tmp_path / "rec").glob("*")) if (tmp_path / "rec").exists() else True


def test_without_a_folder_calls_are_not_recorded_and_the_notice_says_so(recorded, store, settings):
    client, s = recorded(folder=False)
    with client:
        call_id, call = run(client, store)
    assert "audio" not in call
    farmer = {"name": "Pak Wahyu", "language": "Bahasa Indonesia", "crop": "palm"}
    off = build_system_instruction(settings, farmer, "collect", 3)
    on = build_system_instruction(dataclasses.replace(settings, call_audio_dir="/x", call_audio_retention_days=90), farmer, "collect", 3)
    assert "merekam percakapan ini" in on and "selama 90 hari" in on     # the notice says what is really kept
    assert "merekam" not in off and "catatan tertulis" in off


# ---------- who may listen ----------

def test_only_a_planner_may_listen_and_expired_recordings_are_refused(settings, store, tmp_path):
    s = dataclasses.replace(settings, auth_required=True, jwt_secret="t" * 32, demo_password=DEMO, call_audio_dir=tmp_path / "rec")
    LocalAudioStore(tmp_path / "rec").save("call-ok", b"ID3-fake-mp3")
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).isoformat(timespec="seconds")
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(timespec="seconds")
    store.set("calls", "call-ok", {"audio": {"name": "call-ok.mp3", "expires_at": soon}}, merge=True)
    LocalAudioStore(tmp_path / "rec").save("call-old", b"x")
    store.set("calls", "call-old", {"audio": {"name": "call-old.mp3", "expires_at": past}}, merge=True)
    with TestClient(create_app(s, store)) as c:
        planner = login(c, "planner")
        r = c.get("/api/calls/call-ok/audio", headers=planner)
        assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3-fake-mp3"
        for role in ("coordinator", "viewer", "farmer"):
            assert c.get("/api/calls/call-ok/audio", headers=login(c, role)).status_code == 403, role
        assert c.get("/api/calls/call-ok/audio").status_code in (401, 403)             # not signed in
        assert c.get("/api/calls/nope/audio", headers=planner).status_code == 404         # no recording
        assert c.get("/api/calls/call-old/audio", headers=planner).status_code == 410     # past its 90 days


def test_the_built_in_planner_role_gets_the_new_permission_once(store):
    store.set("roles", "planner", {"label": "Planner", "builtin": True, "capabilities": ["campaign.run"]})  # saved before it existed
    access.ensure_defaults(store)
    assert "calls.listen" in store.get("roles", "planner")["capabilities"]
    store.set("roles", "planner", {"capabilities": ["campaign.run"]}, merge=True)                            # a planner takes it away
    access.ensure_defaults(store)
    assert "calls.listen" not in store.get("roles", "planner")["capabilities"]                                # and it is not given back
    assert "calls.listen" not in access.DEFAULT_ROLES["coordinator"]["capabilities"]


# ---------- the cloud bucket ----------

class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    def upload_from_string(self, data, content_type=None):
        self.bucket.files[self.name] = (data, content_type)

    def exists(self):
        return self.name in self.bucket.files

    def download_as_bytes(self):
        return self.bucket.files[self.name][0]

    def delete(self):
        del self.bucket.files[self.name]


class FakeBucket:
    def __init__(self):
        self.files = {}

    def blob(self, name):
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self):
        self.b = FakeBucket()

    def bucket(self, name):
        return self.b


def test_the_bucket_store_saves_reads_and_deletes_and_never_escapes_its_name():
    client = FakeClient()
    st = GcsAudioStore("b", client=client)
    assert st.save("call/../x", b"mp3") == "callx.mp3"
    assert client.b.files["callx.mp3"] == (b"mp3", "audio/mpeg")
    assert st.read("call/../x") == b"mp3" and st.read("nope") is None
    assert st.delete("call/../x") is True and st.delete("call/../x") is False
    assert st.purge(90) == 0  # the bucket's own rule deletes old files


def test_a_bucket_setting_turns_recording_on_and_beats_the_folder(settings, tmp_path, monkeypatch):
    assert not recording_enabled(settings)
    s = dataclasses.replace(settings, call_audio_bucket="my-bucket")
    assert recording_enabled(s)
    made = []
    monkeypatch.setattr("app.call_audio.GcsAudioStore", lambda name: made.append(name) or "gcs")
    assert make_audio_store(dataclasses.replace(s, call_audio_dir=tmp_path)) == "gcs" and made == ["my-bucket"]


def test_a_planner_can_delete_a_recording_now_and_the_transcript_stays(settings, store, tmp_path):
    s = dataclasses.replace(settings, auth_required=True, jwt_secret="t" * 32, demo_password=DEMO, call_audio_dir=tmp_path / "rec")
    LocalAudioStore(tmp_path / "rec").save("call-x", b"fake")
    store.set("calls", "call-x", {"audio": {"name": "call-x.mp3"}, "transcript": [{"who": "farmer", "text": "hi"}]}, merge=True)
    with TestClient(create_app(s, store)) as c:
        assert c.delete("/api/calls/call-x/audio", headers=login(c, "viewer")).status_code == 403
        assert (tmp_path / "rec" / "call-x.mp3").exists()
        assert c.delete("/api/calls/call-x/audio", headers=login(c, "planner")).status_code == 200
        assert not (tmp_path / "rec" / "call-x.mp3").exists()
        call = store.get("calls", "call-x")
        assert not call["audio"] and call["audio_deleted"]["at"] and call["transcript"]
        assert c.get("/api/calls/call-x/audio", headers=login(c, "planner")).status_code == 404
        assert c.delete("/api/calls/call-x/audio", headers=login(c, "planner")).status_code == 404
