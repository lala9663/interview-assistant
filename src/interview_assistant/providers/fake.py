"""In-memory providers for local runs and tests. No network, no credentials."""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator, Sequence
from typing import Any

from interview_assistant.providers.base import (
    DiarizationProvider,
    EmbeddingProvider,
    LLMProvider,
    LLMResult,
    SpeakerTurn,
    STTProvider,
    TranscriptSegment,
)


class FakeLLM(LLMProvider):
    def __init__(self, model: str = "fake-llm", **_: Any) -> None:
        self.model = model

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        text = f"[fake:{self.model}] {prompt[:80]}"
        structured = None
        if schema is not None:
            structured = {key: None for key in schema.get("properties", {})}
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
        result = await self.generate(system, prompt, max_tokens=max_tokens)
        for word in result.text.split(" "):
            yield word + " "


class FakeSTT(STTProvider):
    def __init__(self, language: str = "ko-KR", diarization: bool = False, **_: Any) -> None:
        self.language = language
        self.diarization = diarization

    async def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]:
        t = 0
        async for chunk in audio_chunks:
            yield TranscriptSegment(
                text=f"[fake audio {len(chunk)} bytes]", start_ms=t, end_ms=t + 1000
            )
            t += 1000

    async def transcribe(
        self,
        audio_uri: str,
        *,
        language: str | None = None,
        diarization: bool | None = None,
    ) -> list[TranscriptSegment]:
        use_diarization = self.diarization if diarization is None else diarization
        return [
            TranscriptSegment(
                text=f"[fake transcript of {audio_uri}]",
                start_ms=0,
                end_ms=1000,
                speaker="SPEAKER_1" if use_diarization else None,
            )
        ]


class FakeEmbedding(EmbeddingProvider):
    def __init__(self, dimensions: int = 8, **_: Any) -> None:
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
    def __init__(self, **_: Any) -> None:
        pass

    async def diarize(self, audio_uri: str) -> list[SpeakerTurn]:
        return [SpeakerTurn("SPEAKER_1", 0, 1000), SpeakerTurn("SPEAKER_2", 1000, 2000)]
