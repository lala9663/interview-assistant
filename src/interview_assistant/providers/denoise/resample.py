"""16 kHz <-> 48 kHz for the noise suppressors, which both work on 48 kHz audio, one stream at a time.

The microphone path is 16 kHz (the browser downsamples), so a 48 kHz model sees nothing above
8 kHz; the round trip only has to keep 0-7 kHz intact and add nothing. Both directions use one
linear-phase low-pass FIR (Kaiser window, 241 taps at 48 kHz, cut-off 7.5 kHz, about 80 dB down
from 8.2 kHz): 120 samples (2.5 ms) of delay each way, 5 ms for the round trip. They compute in
float64, so the samples do not depend on how the stream was cut into chunks (in float32 the matrix
product's rounding does, and RNNoise's pitch search can turn a last-bit difference into an audible one).

`At48k` turns a model that eats whole 48 kHz blocks into a `DenoiseStream`: PCM16 chunks of any
length in, exactly as many samples out, a fixed number of samples late (`delay_samples`). The
output starts with that many samples of digital silence, so a chunk is never short of output
while the model waits for a whole block.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from interview_assistant.providers.base import DenoiseStream

RATIO = 3  # 48 kHz / 16 kHz
TAPS = 241
CUTOFF_HZ = 7500.0
KAISER_BETA = 8.0
FIR_DELAY_48K = (TAPS - 1) // 2  # 120 samples, a multiple of RATIO: 40 samples at 16 kHz


def lowpass() -> np.ndarray:
    n = np.arange(TAPS) - FIR_DELAY_48K
    h = 2 * CUTOFF_HZ / 48000 * np.sinc(2 * CUTOFF_HZ / 48000 * n) * np.kaiser(TAPS, KAISER_BETA)
    return h / h.sum()


_H = lowpass()


class Upsampler:
    """16 kHz -> 48 kHz, polyphase: output sample 3i+p is sub-filter p over the input up to i."""

    def __init__(self) -> None:
        width = math.ceil(TAPS / RATIO)
        bank = np.zeros((width, RATIO))
        for p in range(RATIO):
            sub = _H[p::RATIO] * RATIO  # zero stuffing keeps a third of the energy
            bank[: len(sub), p] = sub
        self._bank = bank[::-1].copy()  # rows oldest -> newest input sample
        self._history = np.zeros(width - 1)

    def process(self, x: np.ndarray) -> np.ndarray:
        if not len(x):
            return np.zeros(0, dtype=np.float32)
        data = np.concatenate([self._history, x])
        self._history = data[len(data) - len(self._history) :]
        windows = np.lib.stride_tricks.sliding_window_view(data, len(self._bank))
        return (windows @ self._bank).reshape(-1).astype(np.float32)


class Downsampler:
    """48 kHz -> 16 kHz: low-pass, then every third sample. Any input length; the phase carries."""

    def __init__(self) -> None:
        self._taps = _H[::-1].copy()
        self._history = np.zeros(TAPS - 1)
        self._skip = 0  # input samples to pass before the next kept one

    def process(self, x: np.ndarray) -> np.ndarray:
        if not len(x):
            return np.zeros(0, dtype=np.float32)
        data = np.concatenate([self._history, x])
        self._history = data[len(data) - len(self._history) :]
        windows = np.lib.stride_tricks.sliding_window_view(data, TAPS)[self._skip :: RATIO]
        self._skip = (self._skip - len(x)) % RATIO
        return (windows @ self._taps).astype(np.float32)


class At48k(DenoiseStream):
    """A 48 kHz block model behind 16 kHz PCM16 in and out. Subclasses set `block` (48 kHz
    samples the model takes at once), `holdback` (most 48 kHz samples it may keep back after a
    call, a partial block included) and `inner_delay` (48 kHz samples its output lags its input),
    and implement `_run` on float32 samples scaled to -1..1."""

    block: int = 480
    holdback: int = 479
    inner_delay: int = 0

    def __init__(self) -> None:
        self._up = Upsampler()
        self._down = Downsampler()
        self._pending = np.zeros(0, dtype=np.float32)
        self._odd = b""  # half a sample from the last chunk (the browser never splits one)
        lead = math.ceil(self.holdback / RATIO) + 1  # + 1: room for that half sample
        self._out = bytearray(2 * lead)
        # The output lags by the silence it starts with and by what the filters and model add.
        self.delay_samples = lead + (2 * FIR_DELAY_48K + self.inner_delay) // RATIO

    def _run(self, x: np.ndarray) -> np.ndarray:
        """Whole blocks in (a multiple of `block` samples), whatever is finished out."""
        raise NotImplementedError

    def process(self, pcm: bytes) -> bytes:
        data = self._odd + pcm
        usable = len(data) - len(data) % 2
        self._odd = data[usable:]
        if usable:
            samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
            x = np.concatenate([self._pending, self._up.process(samples)])
            whole = len(x) - len(x) % self.block
            self._pending = x[whole:]
            if whole:
                y = self._down.process(self._run(x[:whole]))
                self._out += (np.clip(y, -1.0, 32767 / 32768) * 32768).astype("<i2").tobytes()
        out = bytes(self._out[: len(pcm)])
        del self._out[: len(pcm)]
        return bytes(len(pcm) - len(out)) + out  # short only if a model kept back more than it said


def mix_dry(enhanced: Any, dry: Any, limit_db: float) -> Any:
    """At most `limit_db` of suppression: the noisy signal comes back at that level below itself
    (DeepFilterNet's `atten_lim_db`); 0 means no limit."""
    if limit_db <= 0:
        return enhanced
    floor = 10 ** (-limit_db / 20)
    return enhanced * (1 - floor) + dry * floor
