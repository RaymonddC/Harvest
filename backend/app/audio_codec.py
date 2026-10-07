"""G.711 mu-law <-> PCM16 codec, and simple linear resampling.

Twilio Media Streams carries 8 kHz mono mu-law; Gemini Live speaks 16 kHz PCM16
in, 24 kHz PCM16 out (see live_session.py). TwilioChannel converts at its own
edge so run_call() never has to know mu-law exists.

Written from scratch rather than stdlib `audioop`, which is deprecated since
3.11 and gone in 3.13 - this has no expiry date and no dependency.
"""

from __future__ import annotations

import bisect
import struct

_EXP_LUT = (0, 132, 396, 924, 1980, 4092, 8316, 16764)


def _decode_byte(ulaw_byte: int) -> int:
    ulaw_byte = ~ulaw_byte & 0xFF
    sign = ulaw_byte & 0x80
    exponent = (ulaw_byte >> 4) & 0x07
    mantissa = ulaw_byte & 0x0F
    sample = _EXP_LUT[exponent] + (mantissa << (exponent + 3))
    return -sample if sign else sample


_DECODE_TABLE = tuple(_decode_byte(b) for b in range(256))

# Encode by nearest-neighbour lookup against the decode table above, instead of
# re-deriving the segment/mantissa bit-packing by hand - that's easy to get
# subtly wrong, and this is exact relative to _DECODE_TABLE by construction.
_BYTES_BY_VALUE = tuple(sorted(range(256), key=lambda b: _DECODE_TABLE[b]))
_SORTED_VALUES = tuple(_DECODE_TABLE[b] for b in _BYTES_BY_VALUE)


def _encode_sample(sample: int) -> int:
    sample = max(-32768, min(32767, sample))
    i = bisect.bisect_left(_SORTED_VALUES, sample)
    if i <= 0:
        return _BYTES_BY_VALUE[0]
    if i >= len(_SORTED_VALUES):
        return _BYTES_BY_VALUE[-1]
    before, after = _SORTED_VALUES[i - 1], _SORTED_VALUES[i]
    closer = i - 1 if (sample - before) <= (after - sample) else i
    return _BYTES_BY_VALUE[closer]


def mulaw_to_pcm16(data: bytes) -> bytes:
    """8-bit mu-law -> little-endian 16-bit signed PCM, same length in samples."""
    if not data:
        return b""
    return struct.pack(f"<{len(data)}h", *(_DECODE_TABLE[b] for b in data))


def pcm16_to_mulaw(data: bytes) -> bytes:
    """Little-endian 16-bit signed PCM -> 8-bit mu-law."""
    if not data:
        return b""
    samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    return bytes(_encode_sample(s) for s in samples)


def resample_pcm16(data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Linear-interpolation resample of mono 16-bit PCM. Fine for speech, not hi-fi."""
    if from_rate == to_rate or not data:
        return data
    src = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
    ratio = from_rate / to_rate
    out_len = max(1, round(len(src) / ratio))
    out = bytearray(out_len * 2)
    last = len(src) - 1
    for i in range(out_len):
        pos = i * ratio
        j = min(int(pos), last)
        frac = pos - j
        a = src[j]
        b = src[j + 1] if j < last else a
        struct.pack_into("<h", out, i * 2, int(a + (b - a) * frac))
    return bytes(out)
