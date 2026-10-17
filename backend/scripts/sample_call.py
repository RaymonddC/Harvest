"""Record a real gap-fill call and build the sample call from it (TODO item 12).

  python scripts/sample_call.py clips    # farmer lines -> speech (Gemini TTS), web/samples/clips/*.wav (16 kHz); --all redoes every line
  python scripts/sample_call.py record   # run_call against the live model with a scripted farmer; writes OUT/recording.json
  python scripts/sample_call.py build    # recording -> web/samples/gap-fill.json + audio clips (one translation request)
  python scripts/sample_call.py bundle   # clips -> web/samples/clips.json (what the page loads; build and clips do it too)

OUT defaults to $SAMPLE_WORK_DIR or ./sample_work. Needs GOOGLE_GENAI_USE_VERTEXAI, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION and either VERTEX_ACCESS_TOKEN (local) or application default credentials.
The farmer lines live in web/samples/farmer-lines.json; the page's "Play the farmer for me" uses the same clips.
"""

from __future__ import annotations

import array
import asyncio
import dataclasses
import json
import os
import struct
import sys
import time
import wave
from pathlib import Path

os.environ.setdefault("HARVEST_NO_DOTENV", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import types  # noqa: E402

from app import live_session, seed_data, services  # noqa: E402
from app.audio_codec import resample_pcm16  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.store import MemoryStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "web" / "samples"
LINES = SAMPLES / "farmer-lines.json"
# The order a scripted recording plays the farmer's lines in (the page picks lines from what the agent says instead).
RECORD_ORDER = ["identity", "volume", "readback", "counter", "agree", "closing"]


def record_lines() -> list[dict]:
    by_id = {line["id"]: line for line in json.loads(LINES.read_text())}
    return [by_id[i] for i in RECORD_ORDER]
WORK = Path(os.environ.get("SAMPLE_WORK_DIR", "sample_work"))
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-tts")
FARMER_VOICE = os.environ.get("FARMER_VOICE", "Charon")
FARMER_ID, GAP_WEEK = "b001", 3  # Pak Wahyu F., Air Molek: 1,600 kg ready in week 4, the shortlist's first farmer
CHUNK_MS = 100
IN_RATE, OUT_RATE = 16000, 24000


def pcm_peak_trim(pcm: bytes, rate: int, pad_ms: int = 60, floor: int = 600) -> bytes:
    """Cut leading and trailing silence so the measured delay starts at the last word, not at TTS padding."""
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    idx = [i for i, v in enumerate(a) if abs(v) > floor]
    if not idx:
        return pcm
    pad = rate * pad_ms // 1000
    return a[max(0, idx[0] - pad): idx[-1] + pad].tobytes()


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


# ---------- clips ----------

def make_clips() -> None:
    lines = json.loads(LINES.read_text())
    client = live_session.genai_client()
    (SAMPLES / "clips").mkdir(exist_ok=True)
    done: set[str] = set()
    for line in lines:
        path = ROOT / "web" / line["audio"]
        if line["audio"] in done or (path.exists() and "--all" not in sys.argv):
            continue  # keep clips a recording already used; pass --all to regenerate every line
        done.add(line["audio"])
        resp = client.models.generate_content(
            model=TTS_MODEL, contents=f"Say in Indonesian, in a calm, friendly voice: {line['text']}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=FARMER_VOICE)))))
        pcm24 = resp.candidates[0].content.parts[0].inline_data.data
        pcm16 = pcm_peak_trim(resample_pcm16(pcm24, OUT_RATE, IN_RATE), IN_RATE)
        write_wav(path, pcm16, IN_RATE)
        print(f"{line['audio']}: {len(pcm16) / 2 / IN_RATE:.1f}s  {line['text']}")


# ---------- recording ----------

class ScriptedChannel:
    """A Channel whose far end is a scripted farmer. After the agent has finished speaking (estimated from the
    audio it sent, as the browser would play it) the next clip is streamed in real time in 100 ms chunks;
    silence chunks fill the gaps like a live microphone, so the model's voice-activity detection can end the turn."""

    def __init__(self, clips: list[bytes], idle_s: float = 1.0, pause_s: float = 0.4) -> None:
        self.clips, self.idle_s, self.pause_s = clips, idle_s, pause_s
        self.t0 = time.monotonic()
        self.events: list[dict] = []      # controls, with t in seconds
        self.agent_audio: list[tuple[float, bytes]] = []
        self.farmer_turns: list[dict] = []  # {index, start, end}: end = when the last speech chunk was handed over
        self.done = asyncio.Event()
        self._next = 0
        self._play_end = 0.0              # when the agent's audio would finish playing
        self._last_audio = -99.0
        self._last_tool = -99.0
        self._speaking: tuple[bytes, int] | None = None
        self._due = None

    def now(self) -> float:
        return time.monotonic() - self.t0

    async def accept(self) -> None:
        self.t0 = time.monotonic()
        self._due = self.t0

    async def close(self) -> None:
        self.done.set()

    async def send_audio(self, pcm16: bytes) -> None:
        t = self.now()
        self.agent_audio.append((t, pcm16))
        self._play_end = max(self._play_end, t) + len(pcm16) / 2 / OUT_RATE
        self._last_audio = t

    async def send_control(self, payload: dict) -> None:
        t = self.now()
        self.events.append({"t": t, "msg": payload})
        if payload.get("type") == "tool":
            self._last_tool = t
        if payload.get("type") in ("ended", "error"):
            self.done.set()

    def _agent_idle(self, t: float) -> bool:
        answered = not self.farmer_turns or self._last_audio > (self.farmer_turns[-1]["end"] or 1e9)
        return (answered and self._last_audio > 0 and t >= self._play_end + self.pause_s and t - self._last_audio >= self.idle_s
                and t - self._last_tool >= 2.5)

    async def recv(self):
        if self.done.is_set():
            return None
        self._due += CHUNK_MS / 1000
        await asyncio.sleep(max(0.0, self._due - time.monotonic()))
        t = self.now()
        if t > float(os.environ.get("MAX_CALL_WALL_S", "300")):
            return {"type": "hangup"}
        size = IN_RATE * CHUNK_MS // 1000 * 2
        if self._speaking is None and self._next < len(self.clips) and self._agent_idle(t):
            self._speaking = (self.clips[self._next], 0)
            self.farmer_turns.append({"index": self._next, "start": t - CHUNK_MS / 1000, "end": None})
            self._next += 1
        if self._speaking is not None:
            clip, pos = self._speaking
            chunk = clip[pos: pos + size].ljust(size, b"\0")
            pos += size
            if pos >= len(clip):
                self.farmer_turns[-1]["end"] = t
                self._speaking = None
            else:
                self._speaking = (clip, pos)
            return chunk
        return b"\0" * size


def measure(ch: ScriptedChannel, vad_ms: int) -> dict:
    first = next((t for t, _ in ch.agent_audio), None)
    turns = []
    for tr in ch.farmer_turns:
        nxt = next((t for t, _ in ch.agent_audio if tr["end"] and t > tr["end"]), None)
        d = None if nxt is None or tr["end"] is None else nxt - tr["end"]
        tools = [e["msg"]["name"] for e in ch.events if e["msg"].get("type") == "tool"
                 and tr["end"] and tr["end"] < e["t"] < (nxt or 1e9) + 5]
        turns.append({"turn": tr["index"] + 1, "tools_before_reply": tools, "farmer_ends": round(tr["end"], 2) if tr["end"] else None,
                      "agent_first_audio": round(nxt, 2) if nxt else None,
                      "delay_s": round(d, 2) if d is not None else None,
                      "delay_without_vad_s": round(d - vad_ms / 1000, 2) if d is not None else None})
    return {"connect_to_first_audio_s": round(first, 2) if first else None, "vad_silence_ms": vad_ms, "turns": turns}


async def record() -> None:
    settings = dataclasses.replace(get_settings(), auth_required=False)
    store = MemoryStore()
    seed_data.load_seed(store, settings)
    farmer = store.get("farmers", FARMER_ID)
    call_id = services.queue_call(store, {**farmer, "id": FARMER_ID}, "gap_fill", gap_week=GAP_WEEK)
    lines = record_lines()
    clips = [read_wav(ROOT / "web" / line["audio"]) for line in lines]
    ch = ScriptedChannel(clips)
    client = live_session.genai_client()

    async def no_translate(text: str, target: str):  # captions are translated once, afterwards, in one request
        return None

    await live_session.run_call(ch, store, settings, call_id,
                                connect=lambda m, c: client.aio.live.connect(model=m, config=c),
                                translate=no_translate)
    call = store.get("calls", call_id)
    WORK.mkdir(parents=True, exist_ok=True)
    raw = b"".join(a for _, a in ch.agent_audio)
    write_wav(WORK / "agent-all.wav", raw, OUT_RATE)
    stats = measure(ch, settings.vad_silence_ms)
    rec = {"farmer": farmer, "call": {k: call.get(k) for k in ("status", "outcome", "summary", "consent", "transcript")},
           "events": ch.events, "agent_chunks": [(round(t, 3), len(a)) for t, a in ch.agent_audio],
           "farmer_turns": ch.farmer_turns, "stats": stats, "lines": lines}
    (WORK / "recording.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1))
    with open(WORK / "agent-chunks.bin", "wb") as f:  # every chunk, with its arrival time
        for t, a in ch.agent_audio:
            f.write(struct.pack("<dI", t, len(a)) + a)
    print(json.dumps(stats, indent=1))
    print("status:", call.get("status"), "| outcome:", call.get("outcome"), "| consent:", call.get("consent"))
    for ln in call.get("transcript") or []:
        print(f"  {ln['who']:>6}: {ln['text']}")
    print("tools:", [(e["msg"]["name"], e["msg"]["args"]) for e in ch.events if e["msg"].get("type") == "tool"])


# ---------- build the sample ----------

CAPTION_LEAD_S = 0.5   # a caption shows slightly before its words are spoken, as subtitles do
TRANSLATE_TO = "English"


def read_chunks(path: Path) -> list[tuple[float, bytes]]:
    data, pos, out = path.read_bytes(), 0, []
    while pos < len(data):
        t, n = struct.unpack_from("<dI", data, pos)
        out.append((t, data[pos + 12: pos + 12 + n]))
        pos += 12 + n
    return out


def translate_batch(texts: list[str]) -> list[str]:
    """All caption translations in ONE request (the free tier allows few; this also keeps the sample cheap to rebuild)."""
    if not texts:
        return []
    prompt = (f"Translate each phone-call line below into {TRANSLATE_TO}. If a line is already in {TRANSLATE_TO}, "
              f"return it unchanged. Reply with a JSON array of strings: same order, same length ({len(texts)}).\n\n"
              + json.dumps(texts, ensure_ascii=False))
    client = live_session.genai_client()  # keep a reference: a client that is garbage-collected closes its connection
    resp = client.models.generate_content(
        model=get_settings().text_model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"))
    out = json.loads(resp.text)
    if not isinstance(out, list) or len(out) != len(texts):
        raise SystemExit(f"translation reply had the wrong shape: {resp.text[:200]}")
    return [str(x).strip() for x in out]


def build(work: Path) -> None:
    import subprocess

    rec = json.loads((work / "recording.json").read_text())
    chunks = read_chunks(work / "agent-chunks.bin")
    turns = rec["farmer_turns"]
    events = [(e["t"], dict(e["msg"])) for e in rec["events"]]
    dur = lambda b: len(b) / 2 / OUT_RATE  # noqa: E731

    # Agent speech: one clip per agent turn = the chunks that arrived between two farmer turns.
    groups: list[list[tuple[float, bytes]]] = [[] for _ in range(len(turns) + 1)]
    for t, b in chunks:
        groups[sum(1 for tr in turns if tr["end"] is not None and tr["end"] < t)].append((t, b))
    groups = [g for g in groups if g]
    # The farmer's turn that precedes each agent group ends before its first chunk; an agent turn k spans [a0, next farmer start).
    bounds = []
    for g in groups:
        a0 = g[0][0]
        nxt = next((tr["start"] for tr in turns if tr["start"] > a0), 1e9)
        bounds.append((a0, nxt, g))

    def retime(t: float, who: str | None) -> float:
        for a0, nxt, g in bounds:
            if a0 <= t < nxt:
                if who == "farmer":
                    return min(t, a0 - 0.05)
                played = sum(dur(b) for ct, b in g if ct <= t)  # audio generated so far = where playback must be
                return a0 + max(0.0, played - CAPTION_LEAD_S)
        return t

    lines: dict[int, str] = {}
    last_frag: dict[int, float] = {}
    out: list[dict] = []
    for t, msg in events:
        if msg["type"] == "caption":
            lines[msg["index"]] = lines.get(msg["index"], "") + msg["text"]
            t2 = retime(t, msg["who"])
            last_frag[msg["index"]] = max(last_frag.get(msg["index"], 0), t2)
            out.append({"t": t2, "msg": msg})
        elif msg["type"] in ("tool", "connected"):
            out.append({"t": retime(t, None), "msg": msg})
    end_audio = max((a0 + sum(dur(b) for _, b in g) for a0, _, g in bounds), default=0)
    ended = next((m for t, m in events if m["type"] == "ended"), None)
    texts = [" ".join(lines[i].split()) for i in sorted(lines)]
    translations = translate_batch(texts)
    for i, (src, tr) in enumerate(zip(texts, translations)):
        if tr and tr.strip().lower() != src.lower():
            out.append({"t": last_frag[i] + 0.5, "msg": {"type": "translation", "index": i, "text": tr}})

    # Clips: the agent's real audio (24 kHz mp3) and the farmer's TTS clips (16 kHz wav, shared with the page's button).
    clips = SAMPLES / "clips"
    clips.mkdir(exist_ok=True)
    for old in clips.glob("agent-*.mp3"):
        old.unlink()
    for n, (a0, _, g) in enumerate(bounds, start=1):
        wav = work / f"agent-{n}.wav"
        write_wav(wav, b"".join(b for _, b in g), OUT_RATE)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-b:a", "56k",
                        str(clips / f"agent-{n}.mp3")], check=True)
        out.append({"t": a0, "who": "agent", "audio": f"samples/clips/agent-{n}.mp3", "ms": round(sum(dur(b) for _, b in g) * 1000)})
    flines = record_lines()
    for tr in turns:
        out.append({"t": tr["start"], "who": "farmer", "audio": flines[tr["index"]]["audio"],
                    "ms": round((tr["end"] - tr["start"]) * 1000)})
    if ended:
        out.append({"t": max(end_audio + 1.0, retime(next(t for t, m in events if m["type"] == "ended"), None)), "msg": ended})
    out.sort(key=lambda e: e["t"])
    for e in out:
        e["t"] = round(e["t"] * 1000)
    f = rec["farmer"]
    sample = {"title": "Sample gap-fill call",
              "note": "A recorded call between the AI agent and a scripted farmer (spoken by Gemini). Not a live call.",
              "recorded": {"model": get_settings().live_model, "vad_silence_ms": rec["stats"]["vad_silence_ms"],
                           "date": time.strftime("%Y-%m-%d")},
              "audio": True, "farmer": f["name"], "village": f["village"], "language": f["language"],
              "kind": "gap_fill", "gap_week": GAP_WEEK, "events": out}
    events_json = ",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in out)  # one event per line
    head = json.dumps({k: v for k, v in sample.items() if k != "events"}, ensure_ascii=False, indent=1)[:-2]
    (SAMPLES / "gap-fill.json").write_text(f'{head},\n "events": [\n{events_json}\n ]\n}}\n')
    size = sum(p.stat().st_size for p in clips.iterdir())
    print(f"gap-fill.json: {len(out)} events, {len(texts)} lines translated in 1 request, clips {size / 1e6:.2f} MB")
    bundle_clips()


def bundle_clips() -> None:
    """All clips in one JSON file (base64), which the page decodes itself. Download managers such as IDM grab every
    audio file a page loads (and the sample then "downloads" instead of playing); a JSON file they leave alone."""
    import base64

    clips = SAMPLES / "clips"
    data = {f"samples/clips/{p.name}": base64.b64encode(p.read_bytes()).decode() for p in sorted(clips.iterdir())
            if p.suffix in (".mp3", ".wav")}
    (SAMPLES / "clips.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"clips.json: {len(data)} clips, {(SAMPLES / 'clips.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "bundle":
        bundle_clips()
    elif cmd == "clips":
        make_clips()
        bundle_clips()
    elif cmd == "record":
        asyncio.run(record())
    elif cmd == "build":
        build(Path(sys.argv[2]) if len(sys.argv) > 2 else WORK)
    else:
        print(__doc__)
