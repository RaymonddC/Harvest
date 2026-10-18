import struct

from app.audio_codec import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16


def pcm16(*samples):
    return struct.pack(f"<{len(samples)}h", *samples)


def test_mulaw_round_trip_is_close():
    # mu-law is lossy (8-bit log encoding of a 16-bit range); close, not exact.
    original = pcm16(0, 1000, -1000, 16000, -16000, 32000, -32000)
    back = pcm16_to_mulaw(original)
    assert len(back) == 7
    restored = struct.unpack("<7h", mulaw_to_pcm16(back))
    for a, b in zip(struct.unpack("<7h", original), restored):
        assert abs(a - b) <= abs(a) * 0.025 + 50


def test_decode_matches_stdlib_audioop_exactly():
    # audioop is deprecated/gone in newer Pythons, which is why this codec exists -
    # but while it's still around in the dev/test environment, it's the ground
    # truth to check the from-scratch decode table against, byte for byte. Python 3.13 removed it: skip there
    # (CI and the Docker image run 3.12, so the check still runs on every push).
    import warnings

    import pytest

    audioop = pytest.importorskip("audioop")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for b in range(256):
            assert mulaw_to_pcm16(bytes([b])) == audioop.ulaw2lin(bytes([b]), 2)


def test_encode_round_trip_error_is_bounded_across_full_range():
    for s in range(-32768, 32768, 101):
        enc = pcm16_to_mulaw(struct.pack("<h", s))
        dec = struct.unpack("<h", mulaw_to_pcm16(enc))[0]
        assert abs(s - dec) <= abs(s) * 0.025 + 50


def test_mulaw_empty_input():
    assert mulaw_to_pcm16(b"") == b""
    assert pcm16_to_mulaw(b"") == b""


def test_resample_same_rate_is_passthrough():
    data = pcm16(1, 2, 3, 4)
    assert resample_pcm16(data, 8000, 8000) is data


def test_resample_upsample_doubles_length():
    data = pcm16(0, 100, 200, 300)
    out = resample_pcm16(data, 8000, 16000)
    assert len(out) == 8 * 2  # 4 samples at 8k -> ~8 samples at 16k
    samples = struct.unpack(f"<{len(out) // 2}h", out)
    assert samples[0] == 0 and samples[-1] in (300, 299)


def test_resample_downsample_halves_length():
    data = pcm16(*range(0, 2400, 100))  # 24 samples
    out = resample_pcm16(data, 24000, 8000)
    assert len(out) == 8 * 2  # 24 samples at 24k -> 8 samples at 8k


# ---------- StreamResampler: filtered, and seamless across chunks ----------

def _tone(freq, rate, secs=0.5, amp=10000):
    import math
    import struct
    n = int(rate * secs)
    return struct.pack(f"<{n}h", *(int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))


def _rms(data):
    import math
    import struct
    s = struct.unpack(f"<{len(data) // 2}h", data)
    return math.sqrt(sum(x * x for x in s) / len(s))


def test_downsampling_keeps_speech_and_removes_what_would_fold_back():
    from app.audio_codec import StreamResampler, resample_pcm16

    speech = _tone(1000, 24000)
    assert abs(_rms(StreamResampler(24000, 8000).process(speech)) - _rms(speech)) < 0.05 * _rms(speech)
    above_nyquist = _tone(6000, 24000)  # folds back to 2 kHz at 8 kHz if not filtered
    assert _rms(resample_pcm16(above_nyquist, 24000, 8000)) > 5000  # the old path lets it through
    assert _rms(StreamResampler(24000, 8000).process(above_nyquist)) < 100


def test_stream_resampler_is_seamless_across_chunks():
    from app.audio_codec import StreamResampler

    for src, dst in ((24000, 8000), (8000, 16000)):
        audio = _tone(700, src)
        whole = StreamResampler(src, dst).process(audio)
        r = StreamResampler(src, dst)
        chunked = b"".join(r.process(audio[i:i + 962]) for i in range(0, len(audio), 962))
        assert chunked == whole
        assert len(whole) == len(audio) * dst // src
