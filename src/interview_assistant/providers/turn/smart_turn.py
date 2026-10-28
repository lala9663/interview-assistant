"""End of answer by Pipecat Smart Turn v3 (Daily, BSD-2-Clause): a small model that hears from the
sound itself (intonation, how the last words end) whether a sentence is finished. Korean is one of
its 23 languages.

As Pipecat runs it: when the VAD has heard `pause_ms` of silence after speech, the last 8 seconds
of audio go to the model once. "Finished" (score from `threshold` up) ends the answer then;
"not finished" waits, and `max_silence_ms` of silence ends it anyway. Speech in between starts
over.

Input like the reference code (pipecat-ai/smart-turn inference.py): the last 8 s, zero-padded at
the start, normalised to zero mean and unit variance, as Whisper's 80-bin log-mel spectrogram
(800 frames). faster-whisper's feature extractor computes the same spectrogram as Hugging Face's
WhisperFeatureExtractor without needing transformers. The int8 ONNX file (8.7 MB) comes from the
admin screen's download (providers/weights.py, sha256 pinned); nothing is fetched at run time.
"""

from __future__ import annotations

import asyncio
import collections
import threading
from pathlib import Path
from typing import Any

from interview_assistant.providers.base import ProviderUnavailable, TurnProvider, TurnTracker
from interview_assistant.providers.weights import SMART_TURN, is_complete

SECONDS = 8
RATE = 16000


class SmartTurnTracker(TurnTracker):
    def __init__(self, provider: SmartTurn, frame_ms: int) -> None:
        self.provider = provider
        self.frame_ms = frame_ms
        self.frames: collections.deque[Any] = collections.deque(maxlen=SECONDS * 1000 // frame_ms)
        self.speech_ms = 0
        self.silent_ms = 0
        self.checked = False  # the model already judged this pause

    async def push(self, speech: bool, frame: Any) -> bool:
        self.frames.append(frame)
        if speech:
            self.speech_ms += self.frame_ms
            self.silent_ms = 0
            self.checked = False
            return False
        self.silent_ms += self.frame_ms
        if self.speech_ms < self.provider.min_speech_ms:
            return False
        if not self.checked and self.silent_ms >= self.provider.pause_ms:
            self.checked = True
            import numpy as np

            audio = np.concatenate(list(self.frames))
            self.probability = await asyncio.to_thread(self.provider.probability, audio)
            if self.probability >= self.provider.threshold:
                self.reason = "model"
                return True
        if self.silent_ms >= self.provider.max_silence_ms:
            self.reason = "max_silence"
            return True
        return False


class SmartTurn(TurnProvider):
    context_keys = ("weights_dir",)

    def __init__(
        self,
        model: str = "smart-turn-v3.2-cpu",
        threshold: float = 0.5,
        pause_ms: int = 200,
        max_silence_ms: int = 3000,
        min_speech_ms: int = 250,
        weights_dir: str | Path = "weights",
        **_: Any,
    ) -> None:
        if model not in SMART_TURN:
            raise ValueError(f"unknown Smart Turn model '{model}' (known: {', '.join(SMART_TURN)})")
        self.size = model
        self.model = model
        self.threshold = threshold
        self.pause_ms = pause_ms
        self.max_silence_ms = max_silence_ms
        self.min_speech_ms = min_speech_ms
        self.weights_dir = Path(weights_dir)
        self._session: Any = None
        self._features: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._session is None:
                weights = SMART_TURN[self.size]
                if not is_complete(weights, self.weights_dir):
                    raise ProviderUnavailable(
                        f"Smart Turn 모델 파일({self.size})이 없습니다. 관리자 > 모델 설정에서 내려받으세요."
                    )
                try:
                    import onnxruntime
                    from faster_whisper.feature_extractor import FeatureExtractor
                except ImportError as exc:
                    raise ProviderUnavailable(
                        "Smart Turn에는 onnxruntime과 faster-whisper가 필요합니다 (uv sync --extra whisper)."
                    ) from exc
                options = onnxruntime.SessionOptions()
                options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
                options.inter_op_num_threads = 1
                options.log_severity_level = 4
                path = weights.path(self.weights_dir) / weights.files[0].name
                self._session = onnxruntime.InferenceSession(
                    str(path), providers=["CPUExecutionProvider"], sess_options=options
                )
                self._features = FeatureExtractor(chunk_length=SECONDS)
            return self._session

    async def warm_up(self) -> None:
        import numpy as np

        await asyncio.to_thread(self._load)
        await asyncio.to_thread(self.probability, np.zeros(RATE, dtype=np.float32))

    def probability(self, audio: Any) -> float:
        """How likely the speech in `audio` (float32, 16 kHz, ending now) is a finished turn."""
        import numpy as np

        session = self._load()
        audio = np.asarray(audio, dtype=np.float32)[-SECONDS * RATE :]
        audio = np.pad(audio, (SECONDS * RATE - len(audio), 0))
        audio = (audio - audio.mean()) / np.sqrt(audio.var() + 1e-7)
        features = self._features(audio, padding=0)[None].astype(np.float32)
        (out,) = session.run(None, {"input_features": features})[:1]
        return float(np.asarray(out).reshape(-1)[0])

    def tracker(self, frame_ms: int) -> SmartTurnTracker:
        return SmartTurnTracker(self, frame_ms)
