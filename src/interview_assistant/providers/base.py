"""Provider interfaces. Business logic depends only on these ABCs.

Which implementation serves each role is an admin setting (admin > 모델 설정, `ai_models/`), seeded
from config/providers.yaml; registry.py maps `impl` names to classes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


# Audio formats an STT provider's `stream` can read. Real audio is 16 kHz mono signed 16-bit
# little-endian PCM in chunks of any size. The simulated candidate (live.audio.ScriptedCandidate)
# sends UTF-8 text, one utterance per chunk, which only FakeSTT understands.
PCM16_16K = "audio/pcm;rate=16000"
SIMULATED_TEXT = "text/plain"
SAMPLE_RATE = 16000


class Provider:
    """What every provider has. `model` names what produced a result: it goes into the audit log
    and next to stored AI output (scores, suggestions, screening, transcript segments)."""

    model: str = ""

    async def warm_up(self) -> None:
        """Load weights or open clients before the provider is put in service (the admin screen
        swaps providers only after this succeeds). Default: nothing to do."""


class ProviderUnavailable(RuntimeError):
    """The provider configured for a role cannot run (package missing, weights deleted ...)."""


@dataclass
class LLMResult:
    text: str
    structured: dict[str, Any] | None
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Provider, ABC):
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


class STTProvider(Provider, ABC):
    """Speech to text. `stream` yields partial and final segments; `transcribe` is the batch path
    (`audio_uri` is a file:// URI in the raw zone). `accepts` lists the `stream` input formats."""

    accepts: frozenset[str] = frozenset({PCM16_16K})

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


@dataclass(frozen=True)
class Embedding:
    """One text's vectors. `dense` has unit length. `sparse` (token id -> weight) is the lexical
    part some models have (BGE-M3): two texts score by the weights of the tokens they share, which
    keeps exact terms (FDC, RF, CVD) from being lost in the dense vector."""

    dense: list[float]
    sparse: dict[int, float] | None = None


class EmbeddingProvider(Provider, ABC):
    """Text to vectors, for retrieval (question bank, rubric anchors, competency dictionaries).

    The three retrieval settings depend on the model's score scale, so they are the provider's
    options (admin > 모델 설정): how much the sparse score counts in a hybrid score, the dense
    similarity from which two questions are the same question, and the lowest hybrid score a
    question-bank match needs to be suggested."""

    dimensions: int
    sparse_weight: float = 0.0
    duplicate_threshold: float = 0.9
    min_score: float = 0.5

    @property
    def index_key(self) -> str:
        """What stored vectors are compatible with: the model, its weights and the size. Vectors
        are saved with it; a provider with another key needs the stored vectors rebuilt."""
        return f"{self.model}/{self.dimensions}"

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def encode(self, texts: Sequence[str]) -> list[Embedding]:
        """Dense and (when the model has it) sparse vectors. Default: dense only."""
        return [Embedding(v) for v in await self.embed(texts)]


@dataclass
class SpeakerTurn:
    speaker: str
    start_ms: int
    end_ms: int


class DiarizationProvider(Provider, ABC):
    @abstractmethod
    async def diarize(self, audio_uri: str) -> list[SpeakerTurn]: ...


class VoiceStream(ABC):
    """One audio stream's voice activity state (an LSTM's memory, the last frame's tail)."""

    @abstractmethod
    def probabilities(self, frames: Any) -> Any:
        """Speech probability (0..1) of each frame: float32 array (n, frame_samples) in, (n,) out.
        Frames must be consecutive: the state carries over from one call to the next."""


class VADProvider(Provider, ABC):
    """Voice activity detection on 16 kHz PCM, frame by frame (32 ms at 512 samples). A frame is
    speech from `threshold` up; once speech started, it stays speech down to `threshold` - 0.15
    (hysteresis). `speech_pad_ms` of audio around speech goes to STT with it, `min_speech_ms`
    of speech starts an answer (shorter noises do not)."""

    frame_samples: int = 512
    threshold: float = 0.5
    speech_pad_ms: int = 300
    min_speech_ms: int = 250

    @abstractmethod
    def stream(self) -> VoiceStream: ...


class TurnTracker(ABC):
    """End-of-answer state for one answer part, fed every VAD frame. `reason` tells what ended it
    ("silence", "model", "max_silence") and `probability` the model's last score, if any."""

    reason: str | None = None
    probability: float | None = None

    @abstractmethod
    async def push(self, speech: bool, frame: Any) -> bool:
        """One frame: whether the VAD heard speech in it, and its samples (float32). True once the
        candidate finished answering."""


class TurnProvider(Provider, ABC):
    """Decides when the candidate finished answering (답변 끝 판정): after enough silence, or when
    a model hears that the sentence is complete."""

    @abstractmethod
    def tracker(self, frame_ms: int) -> TurnTracker: ...


class DenoiseProvider(Provider, ABC):
    """Noise suppression in front of STT (16 kHz PCM16 in, same length out). Off by default:
    suppression artifacts can raise STT errors (docs/reference/audio-quality.md 7장)."""

    enabled: bool = False

    @abstractmethod
    def process(self, pcm: bytes) -> bytes: ...


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float  # 0..1
    box: tuple[float, float, float, float]  # x0, top, x1, bottom in image pixels


@dataclass(frozen=True)
class OcrResult:
    lines: tuple[OcrLine, ...]
    model: str
    elapsed_ms: int

    @property
    def text(self) -> str:
        """Lines in the engine's reading order; a piece on the same row as the one before it (a
        label and its value, split by a gap) joins it with a space instead of a line break.
        Re-sorting by position instead breaks tilted photos, where one line's end sits as high
        as the next line's start."""
        out: list[str] = []
        previous: OcrLine | None = None
        for line in self.lines:
            middle = (line.box[1] + line.box[3]) / 2
            same_row = (
                previous is not None
                and previous.box[1] <= middle <= previous.box[3]
                and line.box[0] >= previous.box[2] - 2
            )
            if out:
                out.append(" " if same_row else "\n")
            out.append(line.text)
            previous = line
        return "".join(out)

    @property
    def confidence(self) -> float | None:
        """Mean line confidence weighted by length; None when nothing was read."""
        weights = [(len(line.text), line.confidence) for line in self.lines if line.text.strip()]
        total = sum(w for w, _ in weights)
        return sum(w * c for w, c in weights) / total if total else None


class OCRProvider(Provider, ABC):
    """Reads the text of one page image. Synchronous and CPU-bound: document reading runs in a
    worker thread and calls it page by page. `version` names the engine and its models for the
    record of how each application was read ("PaddleOCR 3.7.0 · PP-OCRv5 mobile 한국어")."""

    version: str = ""

    @abstractmethod
    def recognize(self, image: PILImage) -> OcrResult: ...
