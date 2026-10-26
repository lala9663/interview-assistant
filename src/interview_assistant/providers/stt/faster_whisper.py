"""Local Whisper STT on CPU (faster-whisper / CTranslate2, MIT). Audio never leaves the machine.

Korean only, int8 on CPU. Weights come from the admin screen's download (providers/weights.py)
and are loaded once per provider, on `warm_up` or first use; no network at run time.

`transcribe` (batch) reads a whole file and lets the built-in Silero VAD skip silence. Files are
decoded by `providers.audio` (PyAV), not faster-whisper's decoder, which passes an argument PyAV 19
no longer takes.

`stream` reads 16 kHz PCM chunks and cuts them into utterances with the same VAD: once an
utterance is followed by `vad_min_silence_ms` of silence it is transcribed and yielded as a final
segment; while it is still going, the audio so far is re-transcribed and yielded as a partial
(greedy). Utterances longer than `max_utterance_s` are cut there.

Every Whisper call encodes a full 30-second window, so a call costs the same for 2 s of speech as
for 20 s (on a laptop CPU on battery: medium ~5 s, large-v3/turbo ~8 s, docs/whisper-benchmark.md).
Partials therefore come at most every `partial_every_s` and never more often than twice the
measured cost of a call; on a slow CPU that means finals only. When decoding falls behind,
utterances that closed meanwhile are transcribed together in one call, which pays the window cost
once, so the lag stays bounded instead of growing.

`initial_prompt` (technical terms, spellings) is sent as the prompt of every 30-second window
(faster-whisper `hotwords`), so it holds over long recordings too.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from interview_assistant.providers.audio import decode_pcm16, uri_to_path
from interview_assistant.providers.base import (
    PCM16_16K,
    SAMPLE_RATE,
    ProviderUnavailable,
    STTProvider,
    TranscriptSegment,
)
from interview_assistant.providers.weights import WHISPER, is_complete

SIZES = tuple(WHISPER)


def auto_threads() -> int:
    """CTranslate2 uses 4 threads unless told otherwise; on a laptop CPU with 12+ cores, using
    all but 4 of them cut medium's time by 30% (docs/whisper-benchmark.md)."""
    return max(4, (os.cpu_count() or 8) - 4)


class FasterWhisperSTT(STTProvider):
    accepts = frozenset({PCM16_16K})
    context_keys = ("weights_dir",)

    partial_every_s = 1.5
    max_utterance_s = 15.0
    step_s = 0.5  # how much new audio triggers a VAD pass while streaming

    def __init__(
        self,
        model: str = "medium",
        language: str = "ko-KR",
        initial_prompt: str = "",
        beam_size: int = 5,
        vad_min_silence_ms: int = 500,
        cpu_threads: int = 0,
        diarization: bool = False,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in WHISPER:
            raise ValueError(f"unknown faster-whisper model '{model}' (known: {', '.join(SIZES)})")
        self.size = model
        self.model = f"faster-whisper-{model}"
        self.language = language
        self.initial_prompt = initial_prompt.strip()
        self.beam_size = beam_size
        self.vad_min_silence_ms = vad_min_silence_ms
        self.cpu_threads = cpu_threads
        self.diarization = diarization  # not supported: segments come back without speakers
        self.path = WHISPER[model].path(Path(weights_dir))
        self.weights_dir = Path(weights_dir)
        self._whisper: Any = None
        self._lock = threading.Lock()
        self.call_seconds = 0.0  # running estimate of one streaming decode, wall time

    @property
    def _code(self) -> str:
        return self.language.split("-")[0].lower()

    def _load(self) -> Any:
        with self._lock:
            if self._whisper is None:
                if not is_complete(WHISPER[self.size], self.weights_dir):
                    raise ProviderUnavailable(
                        f"faster-whisper {self.size} 모델 파일이 없습니다. "
                        "관리자 > 모델 설정에서 내려받으세요."
                    )
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise ProviderUnavailable(
                        "faster-whisper가 설치되어 있지 않습니다 (uv sync --extra whisper)."
                    ) from exc
                self._whisper = WhisperModel(
                    str(self.path),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=self.cpu_threads or auto_threads(),
                    local_files_only=True,
                )
            return self._whisper

    async def warm_up(self) -> None:
        """Load the weights and time one call, so streaming knows from the first utterance
        whether partials can keep up on this machine."""
        await asyncio.to_thread(self._load)
        if not self.call_seconds:
            import numpy as np

            started = time.perf_counter()
            await asyncio.to_thread(
                self._decode, np.zeros(SAMPLE_RATE, dtype=np.float32), beam_size=1, vad=False
            )
            self.call_seconds = time.perf_counter() - started

    def _decode(
        self, audio: Any, *, beam_size: int, vad: bool, timestamps: bool = True
    ) -> list[Any]:
        segments, _info = self._load().transcribe(
            audio,
            language=self._code,
            task="transcribe",
            beam_size=beam_size,
            condition_on_previous_text=False,
            without_timestamps=not timestamps,
            hotwords=self.initial_prompt or None,
            vad_filter=vad,
            vad_parameters={"min_silence_duration_ms": self.vad_min_silence_ms} if vad else None,
        )
        return list(segments)

    # --- batch ------------------------------------------------------------------------------

    async def transcribe(
        self,
        audio_uri: str,
        *,
        language: str | None = None,
        diarization: bool | None = None,
    ) -> list[TranscriptSegment]:
        import numpy as np

        pcm = await asyncio.to_thread(decode_pcm16, uri_to_path(audio_uri))
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        segments = await asyncio.to_thread(self._decode, audio, beam_size=self.beam_size, vad=True)
        return [
            TranscriptSegment(s.text.strip(), int(s.start * 1000), int(s.end * 1000))
            for s in segments
            if s.text.strip()
        ]

    # --- streaming --------------------------------------------------------------------------

    def _speech(self, audio: Any) -> list[dict[str, int]]:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        options = VadOptions(
            min_silence_duration_ms=self.vad_min_silence_ms,
            min_speech_duration_ms=200,
            speech_pad_ms=200,
        )
        return get_speech_timestamps(audio, options)

    async def _text(self, audio: Any, *, final: bool) -> str:
        """One utterance (the caller already cut it with the VAD, and knows its times)."""
        started = time.perf_counter()
        segments = await asyncio.to_thread(
            self._decode,
            audio,
            beam_size=self.beam_size if final else 1,
            vad=False,
            timestamps=False,
        )
        cost = time.perf_counter() - started
        self.call_seconds = cost if not self.call_seconds else (self.call_seconds + cost) / 2
        return " ".join(s.text.strip() for s in segments if s.text.strip())

    async def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        import numpy as np

        await self.warm_up()
        rate = SAMPLE_RATE
        silence = self.vad_min_silence_ms * rate // 1000
        buf = np.zeros(0, dtype=np.float32)
        origin = 0  # absolute sample index of buf[0]
        pending = b""  # an odd trailing byte between chunks
        unseen = 0  # samples received since the last VAD pass
        last_partial = 0  # buffer length at the last partial

        def ms(samples: int) -> int:
            return int((origin + samples) * 1000 / rate)

        async def finish(start: int, end: int) -> TranscriptSegment | None:
            text = await self._text(buf[start:end], final=True)
            return TranscriptSegment(text, ms(start), ms(end), is_final=True) if text else None

        async for chunk in audio_chunks:
            data = pending + chunk
            usable = len(data) - len(data) % 2
            pending = data[usable:]
            if usable:
                samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
                buf = np.concatenate([buf, samples])
                unseen += len(samples)
            if unseen < self.step_s * rate:
                continue
            unseen = 0
            speech = await asyncio.to_thread(self._speech, buf)
            if not speech:
                keep = rate  # no speech: keep one second for the next onset
                if len(buf) > 2 * keep:
                    origin += len(buf) - keep
                    buf = buf[-keep:]
                    last_partial = 0
                continue
            start, end = speech[0]["start"], speech[-1]["end"]
            closed = [s for s in speech if len(buf) - s["end"] >= silence]
            if closed:
                cut = closed[-1]["end"]
                segment = await finish(start, cut)
                if segment is not None:
                    yield segment
                origin += cut
                buf = buf[cut:]
                last_partial = 0
            elif len(buf) - start >= self.max_utterance_s * rate:
                segment = await finish(start, len(buf))
                if segment is not None:
                    yield segment
                origin += len(buf)
                buf = buf[:0]
                last_partial = 0
            elif (
                len(buf) - last_partial >= max(self.partial_every_s, 2 * self.call_seconds) * rate
                and end - start >= rate
            ):
                text = await self._text(buf[start:], final=False)
                last_partial = len(buf)
                if text:
                    yield TranscriptSegment(text, ms(start), ms(len(buf)), is_final=False)

        if len(buf):
            speech = await asyncio.to_thread(self._speech, buf)
            if speech:
                segment = await finish(speech[0]["start"], speech[-1]["end"])
                if segment is not None:
                    yield segment
