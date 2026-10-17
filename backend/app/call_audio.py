"""Call recordings: both sides of a call on one timeline, kept only with the farmer's consent.

CallRecorder collects the audio while the call runs (in memory: a call is at most a few minutes). run_call hands it
to a CallAudioStore at the end when the farmer agreed; with no consent it is simply dropped, so nothing is ever
written for a farmer who said no. The file is a stereo MP3: farmer on the left, agent on the right, 16 kHz.
"""

from __future__ import annotations

import array
import io
import logging
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

FARMER_RATE = 16000   # what the browser (and the Twilio adapter) send in
AGENT_RATE = 24000    # what Gemini sends back
OUT_RATE = 16000
LOUD = 500            # peak (of 32767) above which a chunk counts as speech
SPEECH_GAP_S = 0.8    # this much quiet ends a stretch of speech


class CallRecorder:
    """Lays the two streams on the call's clock.

    The farmer's microphone arrives in real time, so a chunk is placed where it was captured. The agent's audio
    arrives faster than it plays, so it is placed the way the browser plays it: one piece after the other, never
    before the previous one has finished. A barge-in cuts what was still waiting to be played.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._t0 = clock()
        self.farmer = bytearray()
        self.agent = bytearray()
        self._agent_play_end = 0.0           # seconds on the call's clock
        self._turn_start = 0.0               # when the agent's current turn starts playing
        self._farmer_speech_start = 0.0
        self._farmer_last_loud = -99.0

    def now(self) -> float:
        return self._clock() - self._t0

    # ----- audio in -----

    def add_farmer(self, pcm16: bytes) -> None:
        t = self.now()
        n = len(pcm16) // 2
        start = max(0, int(t * FARMER_RATE) - n)
        have = len(self.farmer) // 2
        if start > have:
            self.farmer += b"\0\0" * (start - have)
        self.farmer += pcm16[: n * 2]
        peak = max(map(abs, array.array("h", pcm16[: n * 2])), default=0)
        if peak > LOUD:
            if t - self._farmer_last_loud > SPEECH_GAP_S:
                self._farmer_speech_start = max(0.0, t - n / FARMER_RATE)
            self._farmer_last_loud = t

    def add_agent(self, pcm24: bytes) -> None:
        t = self.now()
        n = len(pcm24) // 2
        start = max(self._agent_play_end, t)
        if t >= self._agent_play_end:
            self._turn_start = start  # nothing was playing: this starts a new stretch of speech
        have = len(self.agent) // 2
        start_sample = int(start * AGENT_RATE)
        if start_sample > have:
            self.agent += b"\0\0" * (start_sample - have)
        self.agent += pcm24[: n * 2]
        self._agent_play_end = start + n / AGENT_RATE

    def interrupted(self) -> None:
        """The farmer talked over the agent: what had not played yet is thrown away, as the browser does."""
        t = self.now()
        keep = int(t * AGENT_RATE) * 2
        if len(self.agent) > keep:
            del self.agent[keep:]
        self._agent_play_end = min(self._agent_play_end, t)

    # ----- where a transcript line starts, in seconds from the start of the call -----

    def line_start(self, who: str) -> float:
        return round(self._turn_start if who == "agent" else self._farmer_speech_start, 2)

    # ----- out -----

    def seconds(self) -> float:
        return max(len(self.farmer) / 2 / FARMER_RATE, len(self.agent) / 2 / AGENT_RATE)

    def encode(self) -> bytes:
        """Stereo MP3 (farmer left, agent right). Needs numpy and soundfile; run it off the event loop."""
        import numpy as np
        import soundfile as sf

        f = np.frombuffer(bytes(self.farmer[: len(self.farmer) // 2 * 2]), dtype="<i2").astype("float32") / 32768
        a24 = np.frombuffer(bytes(self.agent[: len(self.agent) // 2 * 2]), dtype="<i2").astype("float32") / 32768
        n_out = max(len(f), int(len(a24) * OUT_RATE / AGENT_RATE))
        a = np.interp(np.arange(int(len(a24) * OUT_RATE / AGENT_RATE)) * AGENT_RATE / OUT_RATE, np.arange(len(a24)), a24) if len(a24) else a24
        stereo = np.zeros((max(n_out, 1), 2), dtype="float32")
        stereo[: len(f), 0] = f
        stereo[: len(a), 1] = a
        out = io.BytesIO()
        sf.write(out, stereo, OUT_RATE, format="MP3", subtype="MPEG_LAYER_III")
        return out.getvalue()


class CallAudioStore(Protocol):
    def save(self, call_id: str, data: bytes) -> str: ...
    def read(self, call_id: str) -> bytes | None: ...
    def purge(self, older_than_days: int) -> int: ...
    def delete(self, call_id: str) -> bool: ...


class LocalAudioStore:
    """Files in a folder. Fine for a laptop or one server with a disk that lasts; use a bucket in the cloud."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    def _path(self, call_id: str) -> Path:
        safe = "".join(ch for ch in call_id if ch.isalnum() or ch in "-_")
        return self.folder / f"{safe}.mp3"

    def save(self, call_id: str, data: bytes) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self._path(call_id)
        path.write_bytes(data)
        return path.name

    def read(self, call_id: str) -> bytes | None:
        path = self._path(call_id)
        return path.read_bytes() if path.is_file() else None

    def delete(self, call_id: str) -> bool:
        path = self._path(call_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    def purge(self, older_than_days: int) -> int:
        """Delete recordings older than the retention period. Returns how many were removed."""
        if not self.folder.is_dir():
            return 0
        cutoff = time.time() - older_than_days * 86400
        gone = 0
        for p in self.folder.glob("*.mp3"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
                gone += 1
        return gone


class GcsAudioStore:
    """Files in a private Cloud Storage bucket. The bucket's own lifecycle rule deletes old files (deploy/setup-call-audio.sh),
    so purge has nothing to do; the app also refuses to play a recording past its expiry."""

    def __init__(self, bucket: str, client=None) -> None:
        if client is None:
            from google.cloud import storage  # imported here so local runs without a bucket never need it
            client = storage.Client()
        self.bucket = client.bucket(bucket)

    def _blob(self, call_id: str):
        safe = "".join(ch for ch in call_id if ch.isalnum() or ch in "-_")
        return self.bucket.blob(f"{safe}.mp3")

    def save(self, call_id: str, data: bytes) -> str:
        blob = self._blob(call_id)
        blob.upload_from_string(data, content_type="audio/mpeg")
        return blob.name

    def read(self, call_id: str) -> bytes | None:
        blob = self._blob(call_id)
        return blob.download_as_bytes() if blob.exists() else None

    def delete(self, call_id: str) -> bool:
        blob = self._blob(call_id)
        if not blob.exists():
            return False
        blob.delete()
        return True

    def purge(self, older_than_days: int) -> int:
        return 0


def recording_enabled(settings) -> bool:
    return bool(getattr(settings, "call_audio_bucket", None) or getattr(settings, "call_audio_dir", None))


def make_audio_store(settings) -> CallAudioStore | None:
    if getattr(settings, "call_audio_bucket", None):
        return GcsAudioStore(settings.call_audio_bucket)
    return LocalAudioStore(settings.call_audio_dir) if getattr(settings, "call_audio_dir", None) else None
