"""Where the candidate's audio comes from while a question is being answered.

Step 11 plugs in the remote participant's WebRTC track (LiveKit) or the room microphone. Until then
`ScriptedCandidate` simulates the candidate for demos and tests.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from interview_assistant.demo.script import DemoScript, split_sentences


@dataclass(frozen=True)
class Turn:
    session_id: str
    posting_id: str
    question: str


class AudioSource(ABC):
    @abstractmethod
    def open(self, turn: Turn) -> AsyncIterator[bytes]:
        """Audio of the candidate answering `turn`; ends when they stop talking."""


class ScriptedCandidate(AudioSource):
    """Answers with the demo dataset's script: UTF-8 text, one sentence per chunk, with a pause
    before the answer and between sentences. Only FakeSTT can transcribe this "audio"; a real STT
    provider needs a real AudioSource. `speed` 1 matches the frontend mock, 0 is instant."""

    def __init__(self, script: DemoScript | None = None, speed: float = 1.0) -> None:
        self.script = script or DemoScript()
        self.speed = speed

    async def _pause(self, ms: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(ms * self.speed / 1000)

    async def open(self, turn: Turn) -> AsyncIterator[bytes]:
        await self._pause(900)
        for sentence in split_sentences(self.script.answer_for(turn.posting_id, turn.question)):
            yield sentence.encode("utf-8")
            await self._pause(380)
