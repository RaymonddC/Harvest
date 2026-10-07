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
    # truth to check the from-scratch decode table against, byte for byte.
    import audioop
    import warnings

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
