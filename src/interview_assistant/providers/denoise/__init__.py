"""Server-side noise suppression in front of STT (registry names: off; rnnoise and deepfilternet are
listed but not implemented, docs/audio-input.md 7장)."""

from __future__ import annotations

from typing import Any

from interview_assistant.providers.base import DenoiseProvider


class NoDenoise(DenoiseProvider):
    """The default: audio goes to VAD and STT as the browser sent it."""

    enabled = False

    def __init__(self, **_: Any) -> None:
        self.model = "off"

    def process(self, pcm: bytes) -> bytes:
        return pcm
