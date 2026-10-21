"""Provider interfaces. Business logic depends only on these ABCs.

Which implementation is used is decided by config/providers.yaml (see registry.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResult:
    text: str
    structured: dict[str, Any] | None
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    """Text generation. `schema` requests a JSON object validated against that JSON Schema."""

    @abstractmethod
    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult: ...

    @abstractmethod
    def stream(
        self,
        system: str,
        prompt: str,
        *,
        max_tokens: int = 16000,
    ) -> AsyncIterator[str]: ...


@dataclass
class TranscriptSegment:
    text: str
    start_ms: int
    end_ms: int
    speaker: str | None = None
    is_final: bool = True


class STTProvider(ABC):
    """Speech to text. `stream` yields partial and final segments; `transcribe` is the batch path."""

    @abstractmethod
    def stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptSegment]: ...

    @abstractmethod
    async def transcribe(
        self,
        audio_uri: str,
        *,
        language: str | None = None,
        diarization: bool | None = None,
    ) -> list[TranscriptSegment]: ...


class EmbeddingProvider(ABC):
    dimensions: int

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass
class SpeakerTurn:
    speaker: str
    start_ms: int
    end_ms: int


class DiarizationProvider(ABC):
    @abstractmethod
    async def diarize(self, audio_uri: str) -> list[SpeakerTurn]: ...
