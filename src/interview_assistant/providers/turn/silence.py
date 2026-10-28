"""End of answer by silence alone: once the candidate has spoken, `silence_ms` without speech ends
the answer. Simple and predictable; a thinking pause longer than that cuts the answer in two (the
second part is appended when they go on, live/hub.py)."""

from __future__ import annotations

from typing import Any

from interview_assistant.providers.base import TurnProvider, TurnTracker


class SilenceTracker(TurnTracker):
    def __init__(self, frame_ms: int, silence_ms: int, min_speech_ms: int) -> None:
        self.frame_ms = frame_ms
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.speech_ms = 0
        self.silent_ms = 0

    async def push(self, speech: bool, frame: Any) -> bool:
        if speech:
            self.speech_ms += self.frame_ms
            self.silent_ms = 0
            return False
        self.silent_ms += self.frame_ms
        if self.speech_ms >= self.min_speech_ms and self.silent_ms >= self.silence_ms:
            self.reason = "silence"
            return True
        return False


class SilenceTurn(TurnProvider):
    def __init__(self, silence_ms: int = 2000, min_speech_ms: int = 250, **_: Any) -> None:
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.model = f"silence-{silence_ms}ms"

    def tracker(self, frame_ms: int) -> SilenceTracker:
        return SilenceTracker(frame_ms, self.silence_ms, self.min_speech_ms)
