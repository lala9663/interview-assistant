"""DeepFilterNet3 (Hendrik Schröter et al., MIT or Apache-2.0): a network that predicts a gain per
ERB band and, below 4.8 kHz, a 5-tap complex filter over neighbouring frames ("deep filtering"),
on 48 kHz audio in 10 ms frames (960-point STFT, 480 hop) with 20 ms of lookahead.

The upstream Python package needs PyTorch and numpy < 2, and its DSP library (deepfilterlib) has no
wheels past Python 3.11, so neither is used. The network is the official v0.5.6 checkpoint exported
to ONNX (soniqo/DeepFilterNet3-ONNX, MIT; its manifest records the source archive's sha256 and the
PyTorch parity), downloaded from the admin screen with its sha256 pinned (providers/weights.py)
and run on ONNX Runtime. Everything around it is here, as libDF does it: the Vorbis-window STFT,
the ERB and complex features with their running normalisation, the band gains, the deep filter on
the noisy spectrum and the overlap-add synthesis. `enhance` runs a whole recording at once, like
upstream's `enhance`; tests check the stream against it.

Streaming: the exported graph keeps no state between calls (its GRUs start from zero), so each
call re-runs `context_ms` of past frames before the new ones and keeps only the new frames'
output. With context the result approaches the whole-recording one (docs/audio-input.md 7장 has
the measured difference); the cost grows with it. The network runs whenever at least one new
frame has its lookahead, so with the browser's 100 ms chunks once per chunk. The stream is about
45 ms late: 30 ms of model (STFT 10 ms, lookahead 20 ms), a frame of waiting and the filters.
"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

import numpy as np

from interview_assistant.providers.base import DenoiseProvider, ProviderUnavailable
from interview_assistant.providers.denoise.resample import At48k, mix_dry
from interview_assistant.providers.weights import DEEPFILTERNET, is_complete

SR = 48000
FFT = 960
HOP = 480
BINS = FFT // 2 + 1
NB_ERB = 32
NB_DF = 96
ORDER = 5
LOOKAHEAD = 2  # frames, of the features (inside the graph) and of the deep filter
ALPHA = 0.99  # exp(-hop / sr / tau) for tau = 1 s, rounded as libDF does
MEAN_INIT = (-60.0, -90.0)
UNIT_INIT = (0.001, 0.0001)
MIN_BAND_BINS = 2


def vorbis_window() -> np.ndarray:
    s = np.sin(0.5 * np.pi * (np.arange(FFT) + 0.5) / (FFT // 2))
    return np.sin(0.5 * np.pi * s * s).astype(np.float32)


def erb_widths() -> np.ndarray:
    """FFT bins per ERB band (libDF `erb_fb`): equal steps on the ERB scale, at least two bins."""

    def freq2erb(f: float) -> float:
        return 9.265 * math.log1p(f / (24.7 * 9.265))

    def erb2freq(e: float) -> float:
        return 24.7 * 9.265 * (math.exp(e / 9.265) - 1)

    low, high = freq2erb(0.0), freq2erb(SR / 2)
    step = (high - low) / NB_ERB
    widths = []
    prev = over = 0
    for i in range(1, NB_ERB + 1):
        fb = round(erb2freq(low + i * step) / (SR / FFT))
        n = fb - prev - over
        if n < MIN_BAND_BINS:
            over, n = MIN_BAND_BINS - n, MIN_BAND_BINS
        else:
            over = 0
        widths.append(n)
        prev = fb
    widths[-1] += 1
    widths[-1] -= sum(widths) - BINS
    return np.array(widths)


WINDOW = vorbis_window()
WNORM = 1.0 / (FFT * FFT / (2 * HOP))
WIDTHS = erb_widths()
_BAND = np.repeat(np.arange(NB_ERB), WIDTHS)  # bin -> band


class Features:
    """Analysis and features, frame by frame, with the running normalisation states."""

    def __init__(self) -> None:
        self.memory = np.zeros(FFT - HOP, dtype=np.float32)
        self.mean = np.linspace(*MEAN_INIT, NB_ERB, dtype=np.float32)
        self.unit = np.linspace(*UNIT_INIT, NB_DF, dtype=np.float32)

    def frame(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """480 new samples -> (spectrum (481,), ERB features (32,), complex features (2, 96))."""
        buf = np.concatenate([self.memory, samples])
        self.memory = buf[HOP:]
        spec = (np.fft.rfft(buf * WINDOW) * WNORM).astype(np.complex64)
        power = np.bincount(_BAND, weights=spec.real**2 + spec.imag**2, minlength=NB_ERB) / WIDTHS
        erb = (10 * np.log10(power + 1e-10)).astype(np.float32)
        self.mean = erb * (1 - ALPHA) + self.mean * ALPHA
        low = spec[:NB_DF]
        self.unit = np.abs(low) * (1 - ALPHA) + self.unit * ALPHA
        unit = low / np.sqrt(self.unit)
        return spec, (erb - self.mean) / 40, np.stack([unit.real, unit.imag]).astype(np.float32)


class Synthesis:
    def __init__(self) -> None:
        self.memory = np.zeros(FFT - HOP, dtype=np.float32)

    def frame(self, spec: np.ndarray) -> np.ndarray:
        x = np.fft.irfft(spec, FFT).astype(np.float32) * FFT * WINDOW
        out = x[:HOP] + self.memory
        self.memory = x[HOP:]
        return out


def apply(
    frames: range,
    specs: np.ndarray,
    specs_first: int,
    mask: np.ndarray,
    coefs: np.ndarray,
    net_first: int,
    limit_db: float,
) -> np.ndarray:
    """Enhanced spectra of `frames`: band gains on the noisy spectrum, and below `NB_DF` bins the
    deep filter over the noisy frames t-2 .. t+2 instead.
    `specs` (frames from `specs_first` on, through two past the last of `frames`); `mask` (T, 32)
    and `coefs` (5, T, 96, 2): the network's outputs for frames from `net_first` on."""
    t = np.arange(frames.start, frames.stop)
    noisy = specs[t - specs_first]
    enhanced = noisy * mask[t - net_first][:, _BAND]
    taps = t[None, :] - LOOKAHEAD + np.arange(ORDER)[:, None] - specs_first  # (5, F) into specs
    inside = (taps + specs_first >= 0) & (taps < len(specs))  # zeros beyond a recording's ends
    low = specs[np.clip(taps, 0, len(specs) - 1), :NB_DF] * inside[..., None]
    weights = coefs[:, t - net_first]
    enhanced[:, :NB_DF] = (low * (weights[..., 0] + 1j * weights[..., 1])).sum(axis=0)
    return mix_dry(enhanced, noisy, limit_db).astype(np.complex64)


def run_network(session: Any, erb: np.ndarray, unit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(T, 32) and (T, 2, 96) features -> mask (T, 32), coefs (5, T, 96, 2)."""
    mask, coefs = session.run(
        None,
        {
            "feat_erb": erb[None, None].astype(np.float32),
            "feat_spec": np.ascontiguousarray(unit.transpose(1, 0, 2)[None]),
        },
    )
    return mask[0, 0], coefs[0]


def enhance(session: Any, audio: np.ndarray, limit_db: float = 0) -> np.ndarray:
    """A whole 48 kHz recording at once (upstream `df.enhance`): same length, no delay."""
    n = len(audio)
    padded = np.concatenate([audio, np.zeros(FFT + (-n) % HOP, dtype=np.float32)])
    features = Features()
    frames = [features.frame(padded[i : i + HOP]) for i in range(0, len(padded), HOP)]
    specs = np.array([f[0] for f in frames])
    mask, coefs = run_network(session, np.array([f[1] for f in frames]), np.array([f[2] for f in frames]))
    enhanced = apply(range(len(frames)), specs, 0, mask, coefs, 0, limit_db)
    synthesis = Synthesis()
    out = np.concatenate([synthesis.frame(s) for s in enhanced])
    return out[FFT - HOP : FFT - HOP + n]


class DeepFilterStream(At48k):
    block = HOP
    holdback = HOP * (LOOKAHEAD + 1) - 1  # the lookahead frames and a partial one
    inner_delay = FFT - HOP

    def __init__(self, session: Any, context_frames: int, limit_db: float) -> None:
        super().__init__()
        self._session = session
        self._context = context_frames
        self._limit = limit_db
        self._features = Features()
        self._synthesis = Synthesis()
        self._first = 0  # frame number of the oldest kept frame
        self._specs: list[np.ndarray] = []
        self._erb: list[np.ndarray] = []
        self._unit: list[np.ndarray] = []
        self._done = 0  # frames synthesised

    def _run(self, x: np.ndarray) -> np.ndarray:
        for i in range(0, len(x), HOP):
            spec, erb, unit = self._features.frame(x[i : i + HOP])
            self._specs.append(spec)
            self._erb.append(erb)
            self._unit.append(unit)
        analysed = self._first + len(self._specs)
        ready = analysed - LOOKAHEAD  # frames whose lookahead has arrived
        if ready <= self._done:
            return np.zeros(0, dtype=np.float32)
        start = max(self._first, self._done - self._context)
        k = start - self._first
        mask, coefs = run_network(self._session, np.array(self._erb[k:]), np.array(self._unit[k:]))
        frames = range(self._done, ready)
        enhanced = apply(frames, np.array(self._specs), self._first, mask, coefs, start, self._limit)
        out = np.concatenate([self._synthesis.frame(s) for s in enhanced])
        self._done = ready
        # The next call needs its context and the deep filter's two past frames.
        drop = self._done - max(self._context, LOOKAHEAD) - self._first
        if drop > 0:
            del self._specs[:drop], self._erb[:drop], self._unit[:drop]
            self._first += drop
        return out


class DeepFilterNet(DenoiseProvider):
    enabled = True
    context_keys = ("weights_dir",)

    def __init__(
        self,
        model: str = "deepfilternet3",
        context_ms: int = 300,
        atten_lim_db: float = 0,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in DEEPFILTERNET:
            raise ValueError(f"unknown DeepFilterNet model '{model}' (known: {', '.join(DEEPFILTERNET)})")
        self.size = model
        self.model = model
        self.context_frames = max(0, round(context_ms / 10))
        self.atten_lim_db = float(atten_lim_db)
        self.weights_dir = Path(weights_dir)
        self._session: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._session is None:
                weights = DEEPFILTERNET[self.size]
                if not is_complete(weights, self.weights_dir):
                    raise ProviderUnavailable(
                        f"DeepFilterNet 모델 파일({self.size})이 없습니다. 관리자 > 모델 설정에서 내려받으세요."
                    )
                try:
                    import onnxruntime
                except ImportError as exc:
                    raise ProviderUnavailable("DeepFilterNet에는 onnxruntime이 필요합니다 (uv sync --extra denoise).") from exc
                options = onnxruntime.SessionOptions()
                options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
                options.intra_op_num_threads = 1
                options.inter_op_num_threads = 1
                options.log_severity_level = 4
                path = weights.path(self.weights_dir) / weights.files[0].name
                self._session = onnxruntime.InferenceSession(
                    str(path), providers=["CPUExecutionProvider"], sess_options=options
                )
            return self._session

    async def warm_up(self) -> None:
        self._load()

    def stream(self) -> DeepFilterStream:
        return DeepFilterStream(self._load(), self.context_frames, self.atten_lim_db)
