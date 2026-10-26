"""In-memory providers for local runs and tests. No network, no credentials.

FakeLLM answers the app's own prompts with rule-based output (see fake_tasks.py) and anything
else with an echo. FakeSTT treats text chunks as one utterance each (the simulated candidate) and
answers real audio with a placeholder that only says how long it was. `speed` scales the simulated
latency: 1 is roughly the pace of the frontend mock (demo), 0 is instant (tests).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
import wave
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from interview_assistant.providers import fake_tasks
from interview_assistant.providers.base import (
    PCM16_16K,
    SAMPLE_RATE,
    SIMULATED_TEXT,
    DiarizationProvider,
    EmbeddingProvider,
    LLMProvider,
    LLMResult,
    SpeakerTurn,
    STTProvider,
    TranscriptSegment,
)

# Simulated latencies in ms at speed 1.
_GENERATE_MS = 900  # one structured call
_FIRST_TOKEN_MS = 550  # follow-up stream: request -> first suggestion
_TOKEN_MS = 24
_SUGGESTION_GAP_MS = 160
_CHAR_MS = 42  # speech: one or two characters per partial result


def _as_text(chunk: bytes) -> str | None:
    """A simulated-candidate utterance, or None when the chunk is audio (PCM is rarely valid
    UTF-8, and silence decodes to NUL characters)."""
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text if all(c.isprintable() or c.isspace() for c in text) else None


def _wav_seconds(audio_uri: str) -> float | None:
    try:
        with wave.open(str(Path(unquote(urlparse(audio_uri).path.lstrip("/")))), "rb") as w:
            return w.getnframes() / w.getframerate()
    except (OSError, EOFError, wave.Error):
        return None


def _rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class FakeLLM(LLMProvider):
    def __init__(self, model: str = "fake-llm", speed: float = 0.0, **_: Any) -> None:
        self.model = model
        self.speed = speed
        self._calls = 0  # varies repeated identical calls (scoring samples) deterministically

    async def _pause(self, ms: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms * self.speed / 1000)

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        self._calls += 1
        text = f"[fake:{self.model}] {prompt[:80]}"
        structured = None
        if schema is not None:
            structured = fake_tasks.respond(
                schema.get("title"), prompt, _rng(prompt, self._calls)
            )
            if structured is None:
                structured = {key: None for key in schema.get("properties", {})}
            else:
                await self._pause(_GENERATE_MS)
                text = json.dumps(structured, ensure_ascii=False)
        return LLMResult(
            text=text,
            structured=structured,
            model=self.model,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
        )

    async def stream(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 16000,
    ) -> AsyncIterator[str]:
        self._calls += 1
        rng = _rng(prompt, self._calls)
        text = fake_tasks.follow_up_text(prompt, rng)
        if text is None:
            result = await self.generate(system, prompt, max_tokens=max_tokens)
            for word in result.text.split(" "):
                yield word + " "
            return
        await self._pause(_FIRST_TOKEN_MS)
        for piece in fake_tasks.chunks(text, rng):
            yield piece
            await self._pause(_SUGGESTION_GAP_MS if "\n" in piece else _TOKEN_MS)


class FakeSTT(STTProvider):
    accepts = frozenset({SIMULATED_TEXT, PCM16_16K})

    def __init__(
        self,
        language: str = "ko-KR",
        diarization: bool = False,
        speed: float = 0.0,
        model: str = "fake-stt",
        **_: Any,
    ) -> None:
        self.model = model
        self.language = language
        self.diarization = diarization
        self.speed = speed

    async def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        """Simulated audio is UTF-8 text, one utterance per chunk (live.audio.ScriptedCandidate
        sends it): each comes back as growing partial results, then one final result. Real PCM
        audio is only measured; one placeholder segment covers it when the stream ends."""
        origin = time.monotonic()
        pcm_bytes = 0

        def now_ms() -> int:
            return int((time.monotonic() - origin) * 1000)

        async for chunk in audio_chunks:
            text = _as_text(chunk)
            if text is None:
                pcm_bytes += len(chunk)
                continue
            text = text.strip()
            if not text:
                continue
            rng = _rng(text)
            start = now_ms()
            i = 0
            while i < len(text):
                i = min(len(text), i + 1 + (rng.random() < 0.35))
                yield TranscriptSegment(text[:i], start, now_ms(), is_final=False)
                if self.speed > 0:
                    await asyncio.sleep(_CHAR_MS * self.speed / 1000)
            yield TranscriptSegment(text, start, max(now_ms(), start + 1), is_final=True)
        if pcm_bytes:
            seconds = pcm_bytes / 2 / SAMPLE_RATE
            text = f"[fake 전사] 오디오 {seconds:.1f}초 (fake STT는 음성을 알아듣지 않습니다)"
            yield TranscriptSegment(text, 0, int(seconds * 1000), is_final=True)

    async def transcribe(
        self,
        audio_uri: str,
        *,
        language: str | None = None,
        diarization: bool | None = None,
    ) -> list[TranscriptSegment]:
        use_diarization = self.diarization if diarization is None else diarization
        seconds = _wav_seconds(audio_uri)
        length = f"오디오 {seconds:.1f}초" if seconds is not None else "오디오 파일"
        return [
            TranscriptSegment(
                text=f"[fake 전사] {length} (fake STT는 음성을 알아듣지 않습니다)",
                start_ms=0,
                end_ms=int((seconds or 1) * 1000),
                speaker="SPEAKER_1" if use_diarization else None,
            )
        ]


class FakeEmbedding(EmbeddingProvider):
    def __init__(self, dimensions: int = 8, model: str = "fake-embedding", **_: Any) -> None:
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [b / 255.0 for b in digest[: self.dimensions]]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors


class FakeDiarization(DiarizationProvider):
    def __init__(self, model: str = "fake-diarization", **_: Any) -> None:
        self.model = model

    async def diarize(self, audio_uri: str) -> list[SpeakerTurn]:
        return [SpeakerTurn("SPEAKER_1", 0, 1000), SpeakerTurn("SPEAKER_2", 1000, 2000)]
