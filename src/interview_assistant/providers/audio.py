"""Audio plumbing shared by STT callers: file URIs, decoding to the streaming format, chunking.

`STTProvider.stream` reads 16 kHz mono 16-bit PCM (`base.PCM16_16K`). Files and browser
recordings (WAV, WebM/Opus, MP3, M4A ...) are decoded with PyAV, which comes with faster-whisper;
without it only 16 kHz mono 16-bit WAV can be read.

`SAMPLE` is a short Korean read-speech clip for connection tests: FLEURS ko_kr test #1894
(Google, CC BY 4.0, see samples/NOTICE.md).
"""

from __future__ import annotations

import asyncio
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from interview_assistant.providers.base import SAMPLE_RATE

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE = SAMPLES_DIR / "ko-fleurs-1894.wav"
SAMPLE_TEXT = "커리는 약용 식물과 향신료를 기본으로 하여 고기나 채소를 곁들이는 요리입니다."


class AudioDecodeError(ValueError):
    pass


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise AudioDecodeError(f"only file:// URIs are supported, not {parsed.scheme or 'a path'}")
    return Path(url2pathname(unquote(parsed.path)))


def _read_wav_pcm16(path: Path) -> bytes | None:
    try:
        with wave.open(str(path), "rb") as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, SAMPLE_RATE):
                return None
            return w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None


def decode_pcm16(path: Path) -> bytes:
    """The whole file as 16 kHz mono signed 16-bit little-endian PCM."""
    pcm = _read_wav_pcm16(path)
    if pcm is not None:
        return pcm
    try:
        import av
    except ImportError as exc:
        raise AudioDecodeError(
            "이 오디오 형식을 읽으려면 PyAV가 필요합니다 (uv sync --extra whisper). "
            "16kHz 모노 16비트 WAV는 그대로 읽습니다."
        ) from exc
    out = bytearray()
    try:
        with av.open(str(path)) as container:
            stream = next((s for s in container.streams if s.type == "audio"), None)
            if stream is None:
                raise AudioDecodeError("오디오 트랙이 없습니다.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(stream):
                for converted in resampler.resample(frame):
                    out += bytes(converted.planes[0])[: converted.samples * 2]
            for converted in resampler.resample(None):
                out += bytes(converted.planes[0])[: converted.samples * 2]
    except AudioDecodeError:
        raise
    except Exception as exc:  # PyAV raises its own error types per container/codec
        raise AudioDecodeError(f"오디오를 읽지 못했습니다: {type(exc).__name__}") from exc
    return bytes(out)


def pcm_seconds(pcm: bytes) -> float:
    return len(pcm) / 2 / SAMPLE_RATE


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


async def pcm_chunks(
    pcm: bytes, *, chunk_ms: int = 100, realtime: bool = False
) -> AsyncIterator[bytes]:
    """PCM in fixed-size chunks. Without `realtime` they come as fast as the consumer reads. With
    it they behave like a microphone track: produced on the wall clock whether or not the consumer
    is reading, and queued while it is busy (so a slow STT sees a backlog, not paused speech)."""
    size = SAMPLE_RATE * 2 * chunk_ms // 1000
    pieces = [pcm[i : i + size] for i in range(0, len(pcm), size)]
    if not realtime:
        for piece in pieces:
            yield piece
            await asyncio.sleep(0)
        return
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def produce() -> None:
        start = asyncio.get_running_loop().time()
        for i, piece in enumerate(pieces):
            delay = start + (i + 1) * chunk_ms / 1000 - asyncio.get_running_loop().time()
            await asyncio.sleep(max(0.0, delay))
            queue.put_nowait(piece)
        queue.put_nowait(None)

    producer = asyncio.create_task(produce())
    try:
        while (piece := await queue.get()) is not None:
            yield piece
    finally:
        producer.cancel()
