"""Server-side noise suppression (audio.denoise): the 16/48 kHz filters, streams that keep their
length and a fixed delay whatever the chunk sizes, RNNoise and DeepFilterNet3 (docs/audio-input.md 7장)."""

from __future__ import annotations

import asyncio
import importlib.util
import math
import os
from pathlib import Path

import numpy as np
import pytest

from interview_assistant.live.audio import Turn
from interview_assistant.live.microphone import MicrophoneSource
from interview_assistant.live.recording import WavRecorder
from interview_assistant.providers.audio import SAMPLE, decode_pcm16
from interview_assistant.providers.base import DenoiseProvider, ProviderUnavailable
from interview_assistant.providers.denoise import NoDenoise
from interview_assistant.providers.denoise import deepfilternet as dfn
from interview_assistant.providers.denoise import rnnoise
from interview_assistant.providers.denoise.resample import FIR_DELAY_48K, At48k, Downsampler, Upsampler
from interview_assistant.providers.weights import DEEPFILTERNET, is_complete
from tests.test_audio_input import LoudnessVAD, drain, silence, tone

RATE = 16000
WEIGHTS = Path(os.environ.get("IA_WEIGHTS_DIR") or Path(__file__).resolve().parents[1] / "weights")
has_rnnoise = importlib.util.find_spec("pyrnnoise") is not None
has_dfn = is_complete(DEEPFILTERNET["deepfilternet3"], WEIGHTS) and importlib.util.find_spec("onnxruntime") is not None


def speech_pcm(seconds: float = 11.5) -> bytes:
    """The Korean sample (speech from 2.3 s) with a little room noise, so a suppressor has
    something to do."""
    x = np.frombuffer(decode_pcm16(SAMPLE), dtype="<i2").astype(np.float32)[: int(seconds * RATE)]
    x += np.random.default_rng(0).normal(0, 300, len(x)).astype(np.float32)
    return np.clip(x, -32768, 32767).astype("<i2").tobytes()


def through(stream, pcm: bytes, sizes) -> bytes:
    """`pcm` fed in chunks of the given byte sizes (cycled), every output checked for length."""
    out, i, k = [], 0, 0
    while i < len(pcm):
        piece = pcm[i : i + sizes[k % len(sizes)]]
        got = stream.process(piece)
        assert len(got) == len(piece)
        out.append(got)
        i += len(piece)
        k += 1
    return b"".join(out)


def samples(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float64)


def snr_db(reference: np.ndarray, other: np.ndarray) -> float:
    return 10 * math.log10((reference**2).sum() / max(((reference - other) ** 2).sum(), 1e-9))


RANDOM_SIZES = [int(n) for n in np.random.default_rng(3).integers(1, 4000, 50)]  # odd ones too


# --- 16 kHz <-> 48 kHz -------------------------------------------------------------------------


def test_the_filters_give_the_same_samples_whatever_the_chunks():
    x = np.random.default_rng(0).standard_normal(16000).astype(np.float32)
    whole_up = Upsampler().process(x)
    up = Upsampler()
    parts = np.concatenate([up.process(x[i : i + 333]) for i in range(0, len(x), 333)])
    assert len(whole_up) == 3 * len(x) and np.abs(parts - whole_up).max() < 1e-5
    whole_down = Downsampler().process(whole_up)
    down = Downsampler()
    parts = np.concatenate([down.process(whole_up[i : i + 1001]) for i in range(0, len(whole_up), 1001)])
    assert len(whole_down) == len(x) and np.abs(parts - whole_down).max() < 1e-5


@pytest.mark.parametrize("hz", [300, 1000, 4000, 7000])
def test_speech_frequencies_come_back_unchanged_after_the_round_trip(hz):
    t = np.arange(RATE) / RATE
    x = (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    y = Downsampler().process(Upsampler().process(x))
    delay = 2 * FIR_DELAY_48K // 3
    assert snr_db(x[1000 : -1000 - delay], y[1000 + delay : -1000]) > 35


def test_nothing_above_8_khz_folds_back_into_the_speech_band():
    t = np.arange(48000) / 48000
    y = Downsampler().process(np.sin(2 * np.pi * 12000 * t).astype(np.float32))
    assert np.sqrt((y[500:] ** 2).mean()) < 1e-3  # -60 dB


class Copy(At48k):
    """A model that returns its blocks unchanged, a frame late."""

    block = 480
    holdback = 479
    inner_delay = 480

    def __init__(self) -> None:
        super().__init__()
        self._last = np.zeros(480, dtype=np.float32)

    def _run(self, x):
        out = np.concatenate([self._last, x])
        self._last = out[-480:]
        return out[:-480]


def test_the_output_keeps_the_length_and_lags_by_exactly_the_stated_delay():
    pcm = speech_pcm()
    stream = Copy()
    out = samples(through(stream, pcm, RANDOM_SIZES))
    d = stream.delay_samples
    assert not out[: d - 240].any()  # the silence it starts with (the filters ring 80 samples early)
    assert snr_db(samples(pcm)[1000 : -d - 1000], out[1000 + d : -1000]) > 25  # the white noise loses 7.5-8 kHz


# --- RNNoise -----------------------------------------------------------------------------------


@pytest.mark.skipif(not has_rnnoise, reason="pyrnnoise not installed (uv sync --extra denoise)")
def test_rnnoise_streams_the_same_audio_whatever_the_chunks_and_about_35_ms_late():
    provider = rnnoise.RNNoise()
    pcm = speech_pcm(5)
    whole = provider.stream().process(pcm)
    assert len(whole) == len(pcm)
    for sizes in ([3200], [480, 2, 7001], RANDOM_SIZES):
        assert through(provider.stream(), pcm, sizes) == whole
    assert through(provider.stream(), pcm[:9600], [1]) == whole[:9600]  # byte by byte
    stream = provider.stream()
    assert 30 * 16 <= stream.delay_samples <= 40 * 16
    x, y = samples(pcm), samples(whole)
    lag = max(range(0, 1200), key=lambda k: float(np.dot(y[40000 + k : 72000 + k], x[40000:72000])))
    assert lag == stream.delay_samples


@pytest.mark.skipif(not has_rnnoise, reason="pyrnnoise not installed (uv sync --extra denoise)")
def test_rnnoise_turns_down_a_steady_hum_and_the_limit_keeps_some_of_it():
    t = np.arange(4 * RATE) / RATE
    noise = np.random.default_rng(1).normal(0, 0.03, len(t)) + 0.03 * np.sin(2 * np.pi * 120 * t)
    pcm = (noise * 32767).astype("<i2").tobytes()
    full = samples(rnnoise.RNNoise().stream().process(pcm))[RATE:]
    limited = samples(rnnoise.RNNoise(atten_lim_db=6).stream().process(pcm))[RATE:]
    before = (samples(pcm)[RATE:] ** 2).mean()
    assert (full**2).mean() < before / 30  # more than 15 dB down
    assert before / 8 < (limited**2).mean() < before  # about 6 dB: the noisy signal mixed back


def test_rnnoise_refuses_a_library_nobody_reviewed(tmp_path):
    fake = tmp_path / ("rnnoise.dll" if rnnoise.sys.platform == "win32" else "librnnoise.so")
    fake.write_bytes(b"not the reviewed build")
    with pytest.raises(ProviderUnavailable, match="검토한 것과 다릅니다"):
        rnnoise._check_file(fake)
    with pytest.raises(ProviderUnavailable, match="pyrnnoise"):
        rnnoise._check_file(None)


# --- DeepFilterNet3 ----------------------------------------------------------------------------


def test_deepfilternet_dsp_matches_libdf():
    assert dfn.WIDTHS.sum() == dfn.BINS and dfn.WIDTHS.min() >= 2
    assert dfn.WIDTHS[:13].tolist() == [2] * 13 and dfn.WIDTHS[-3:].tolist() == [50, 56, 67]
    w = dfn.WINDOW
    assert np.allclose(w[:480] ** 2 + w[480:] ** 2, 1, atol=1e-6)  # Princen-Bradley: perfect reconstruction
    x = np.random.default_rng(0).standard_normal(48000).astype(np.float32)
    analysis, synthesis = dfn.Features(), dfn.Synthesis()
    y = np.concatenate([synthesis.frame(analysis.frame(x[i : i + 480])[0]) for i in range(0, len(x), 480)])
    assert np.abs(y[480:] - x[:-480]).max() < 1e-4  # STFT and back: the input, one hop late


def test_deepfilternet_without_its_downloaded_file_refuses_to_load(tmp_path, no_network):
    with pytest.raises(ProviderUnavailable, match="내려받"):
        dfn.DeepFilterNet(weights_dir=tmp_path).stream()


@pytest.mark.skipif(not has_dfn, reason="DeepFilterNet3 file not downloaded")
def test_deepfilternet_stream_with_all_its_past_equals_the_whole_recording_at_once():
    provider = dfn.DeepFilterNet(weights_dir=WEIGHTS, context_ms=100_000)
    pcm = speech_pcm(4)
    stream = provider.stream()
    streamed = samples(through(stream, pcm, RANDOM_SIZES))
    x = samples(pcm).astype(np.float32) / 32768
    whole = Downsampler().process(dfn.enhance(provider._load(), Upsampler().process(x))) * 32768
    fir = 2 * FIR_DELAY_48K // 3
    d = stream.delay_samples
    assert 40 * 16 <= d <= 50 * 16
    a, b = streamed[d:], whole[fir : fir + len(streamed) - d]
    assert np.abs(a - b).max() <= 3  # int16 rounding


@pytest.mark.skipif(not has_dfn, reason="DeepFilterNet3 file not downloaded")
def test_deepfilternet_with_a_short_context_stays_close_and_keeps_the_length():
    provider = dfn.DeepFilterNet(weights_dir=WEIGHTS)
    pcm = speech_pcm(5)
    reference = samples(dfn.DeepFilterNet(weights_dir=WEIGHTS, context_ms=100_000).stream().process(pcm))
    for sizes in ([3200], [1, 9601], RANDOM_SIZES):
        out = samples(through(provider.stream(), pcm, sizes))
        assert snr_db(reference[RATE:], out[RATE:]) > 15


# --- the microphone path -----------------------------------------------------------------------


class Mute(DenoiseProvider):
    """Suppresses everything; counts the streams it hands out."""

    enabled = True
    model = "mute"

    def __init__(self) -> None:
        self.streams = 0

    def stream(self):
        self.streams += 1
        return MuteStream()


class MuteStream:
    delay_samples = 0

    def process(self, pcm: bytes) -> bytes:
        return bytes(len(pcm))


async def test_suppression_sits_after_the_recording_and_before_the_vad(tmp_path):
    denoise = Mute()
    recorder = WavRecorder(tmp_path / "s.wav")
    mic = MicrophoneSource(vad=LoudnessVAD(), turn=None, denoise=denoise, recorder=recorder)
    other = MicrophoneSource(vad=LoudnessVAD(), turn=None, denoise=denoise)
    assert denoise.streams == 2  # one stream per microphone: no state shared between interviews
    mic.attach("websocket", "a")
    reader = asyncio.create_task(drain(mic, Turn("s", "p", "q")))
    await asyncio.sleep(0)
    pcm = tone(1.0) + silence(0.5)
    await mic.feed(pcm)
    assert not mic.speaking  # the VAD heard the suppressed audio
    mic.set_role("interviewer")
    assert not any(await reader)
    recorder.close()
    assert decode_pcm16(tmp_path / "s.wav") == pcm  # the recording is the raw audio
    other.close()


def test_off_and_an_enabled_provider_differ_only_in_the_stream():
    assert NoDenoise().stream().process(b"\x01\x02") == b"\x01\x02"
    assert not NoDenoise().enabled
