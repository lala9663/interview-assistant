"""Silero VAD (MIT) for the microphone path: which 32 ms frames hold speech.

The model is the v6 ONNX file that ships inside faster-whisper (faster_whisper/assets), so nothing
is downloaded; its size and sha256 are pinned below and checked when it is loaded. A different
file (another faster-whisper release) refuses to load until the pin is reviewed and updated.

faster-whisper's export takes a batch of frames as one sequence: each row is 64 samples of the
previous frame followed by 512 new ones, and the LSTM state (h, c) runs through the rows in order.
`SileroStream` keeps that state and the last frame's tail between calls, so feeding a stream chunk
by chunk gives the same probabilities as feeding it whole.
"""

from __future__ import annotations

import hashlib
import importlib.util
import threading
from pathlib import Path
from typing import Any

from interview_assistant.providers.base import ProviderUnavailable, VADProvider, VoiceStream

MODEL_FILE = "silero_vad_v6.onnx"
MODEL_SIZE = 1245151
MODEL_SHA256 = "4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2"  # faster-whisper 1.2.1
CONTEXT = 64


def model_path() -> Path | None:
    spec = importlib.util.find_spec("faster_whisper")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).parent / "assets" / MODEL_FILE


def _check_file(path: Path | None) -> Path:
    if path is None:
        raise ProviderUnavailable("faster-whisper가 설치되어 있지 않아 VAD 모델이 없습니다 (uv sync --extra whisper).")
    if not path.is_file():
        raise ProviderUnavailable(f"VAD 모델 파일이 없습니다: {path}")
    if path.stat().st_size != MODEL_SIZE:
        raise ProviderUnavailable("VAD 모델 파일 크기가 검토한 것과 다릅니다 (faster-whisper 버전 확인).")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise ProviderUnavailable("VAD 모델 파일의 sha256이 검토한 것과 다릅니다 (faster-whisper 버전 확인).")
    return path


class SileroStream(VoiceStream):
    def __init__(self, session: Any) -> None:
        import numpy as np

        self._session = session
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._tail = np.zeros(CONTEXT, dtype=np.float32)

    def probabilities(self, frames: Any) -> Any:
        import numpy as np

        frames = np.asarray(frames, dtype=np.float32).reshape(-1, 512)
        if not len(frames):
            return np.zeros(0, dtype=np.float32)
        context = np.concatenate([self._tail[None, :], frames[:-1, -CONTEXT:]])
        batch = np.concatenate([context, frames], axis=1)
        out, self._h, self._c = self._session.run(None, {"input": batch, "h": self._h, "c": self._c})
        self._tail = frames[-1, -CONTEXT:].copy()
        return np.asarray(out, dtype=np.float32).reshape(-1)


class SileroVAD(VADProvider):
    def __init__(
        self,
        threshold: float = 0.5,
        speech_pad_ms: int = 300,
        min_speech_ms: int = 250,
        **_: Any,
    ) -> None:
        self.threshold = threshold
        self.speech_pad_ms = speech_pad_ms
        self.min_speech_ms = min_speech_ms
        self.model = "silero-vad-v6"
        self._session: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._session is None:
                path = _check_file(model_path())
                try:
                    import onnxruntime
                except ImportError as exc:
                    raise ProviderUnavailable("onnxruntime이 설치되어 있지 않습니다 (uv sync --extra whisper).") from exc
                options = onnxruntime.SessionOptions()
                options.inter_op_num_threads = 1
                options.intra_op_num_threads = 1
                options.log_severity_level = 4
                self._session = onnxruntime.InferenceSession(
                    str(path), providers=["CPUExecutionProvider"], sess_options=options
                )
            return self._session

    async def warm_up(self) -> None:
        self._load()

    def stream(self) -> SileroStream:
        return SileroStream(self._load())
