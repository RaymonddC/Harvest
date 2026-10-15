"""G.711 mu-law <-> PCM16 codec, and resampling (filtered and stateful for streams).

Twilio Media Streams carries 8 kHz mono mu-law; Gemini Live speaks 16 kHz PCM16
in, 24 kHz PCM16 out (see live_session.py). TwilioChannel converts at its own
edge so run_call() never has to know mu-law exists.

Written from scratch rather than stdlib `audioop`, which is deprecated since
3.11 and gone in 3.13 - this has no expiry date and no dependency.
"""

from __future__ import annotations

import bisect
import math
import operator
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


def _lowpass_taps(cutoff: float, count: int) -> tuple[float, ...]:
    """Windowed-sinc low-pass FIR. cutoff is a fraction of the sample rate (0 to 0.5)."""
    mid = (count - 1) / 2
    taps = []
    for n in range(count):
        x = n - mid
        sinc = 2 * cutoff if x == 0 else math.sin(2 * math.pi * cutoff * x) / (math.pi * x)
        window = 0.54 - 0.46 * math.cos(2 * math.pi * n / (count - 1))  # Hamming
        taps.append(sinc * window)
    total = sum(taps)
    return tuple(t / total for t in taps)


def _clip(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


class StreamResampler:
    """Resamples a stream of PCM16 chunks, keeping state between chunks.

    Converting each chunk on its own (resample_pcm16) puts a small step at every chunk
    boundary, heard as clicks. Going down (Gemini's 24 kHz to the phone's 8 kHz) it also
    filters first: dropping samples without a low-pass folds everything above 4 kHz back
    into the speech band, which is the harsh, metallic sound of a badly downsampled voice.
    Integer ratios only (24k to 8k, 8k to 16k); anything else falls back to resample_pcm16.
    """

    TAPS = 63  # sharp enough to keep 3 kHz (voice clarity) while cutting what folds back above 4 kHz

    def __init__(self, from_rate: int, to_rate: int) -> None:
        self.from_rate, self.to_rate = from_rate, to_rate
        self.down = from_rate // to_rate if from_rate > to_rate and from_rate % to_rate == 0 else 0
        self.up = to_rate // from_rate if to_rate > from_rate and to_rate % from_rate == 0 else 0
        if self.down:
            # Cut off a little below the new Nyquist (about 3.4 kHz for 8 kHz, the classic phone band).
            self._taps_rev = tuple(reversed(_lowpass_taps(0.425 / self.down, self.TAPS)))
        self.reset()

    def reset(self) -> None:
        """Forget the previous audio, e.g. after a barge-in cleared what was queued."""
        self._hist = [0] * (self.TAPS - 1)
        self._offset = 0
        self._prev = 0

    def process(self, data: bytes) -> bytes:
        if not data or self.from_rate == self.to_rate:
            return data
        samples = struct.unpack(f"<{len(data) // 2}h", data[: len(data) // 2 * 2])
        if self.down:
            return self._decimate(samples)
        if self.up:
            return self._interpolate(samples)
        return resample_pcm16(data, self.from_rate, self.to_rate)

    def _decimate(self, samples) -> bytes:
        buf = self._hist + list(samples)
        taps, n = self._taps_rev, self.TAPS
        i = len(self._hist) + self._offset
        out = []
        while i < len(buf):
            out.append(_clip(sum(map(operator.mul, taps, buf[i - n + 1:i + 1]))))
            i += self.down
        self._offset = i - len(buf)
        self._hist = buf[-(n - 1):]
        return struct.pack(f"<{len(out)}h", *out)

    def _interpolate(self, samples) -> bytes:
        out = []
        prev, k = self._prev, self.up
        for s in samples:
            for j in range(1, k):
                out.append(_clip(prev + (s - prev) * j / k))
            out.append(s)
            prev = s
        self._prev = prev
        return struct.pack(f"<{len(out)}h", *out)


def resample_pcm16(data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Linear-interpolation resample of mono 16-bit PCM, one chunk on its own. Fine for speech,
    not hi-fi; for a stream (a phone call) use StreamResampler."""
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
