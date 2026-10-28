"""The interview recording in the raw zone: one 16 kHz mono 16-bit WAV per session
(`recordings_dir/<session id>.wav`, `InterviewSession.recording_uri`), written only when the
candidate consented. Audio is appended as it arrives; a reconnect appends to the same file, so the
recording is the microphone audio the server received, without the time the microphone was off.

The header's sizes are rewritten after every write, so a crash leaves a playable file with all
audio up to the last write. The file is never served by the API and never leaves the server.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

from interview_assistant.providers.base import SAMPLE_RATE

HEADER = 44


def _header(data_bytes: int) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 36 + data_bytes)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
        + b"data"
        + struct.pack("<I", data_bytes)
    )


class WavRecorder:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: BinaryIO | None = None
        size = self.path.stat().st_size if self.path.is_file() else 0
        self._data = max(0, size - HEADER) // 2 * 2  # audio already there (a reconnect appends)

    def _open(self) -> BinaryIO:
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= HEADER:
                self._file = self.path.open("r+b")
                self._data = self.path.stat().st_size - HEADER
                self._data -= self._data % 2
            else:
                self._file = self.path.open("w+b")
                self._file.write(_header(0))
                self._data = 0
        return self._file

    def write(self, pcm: bytes) -> None:
        f = self._open()
        f.seek(HEADER + self._data)
        f.write(pcm)
        self._data += len(pcm)
        f.seek(0)
        f.write(_header(self._data))
        f.flush()

    @property
    def seconds(self) -> float:
        return self._data / 2 / SAMPLE_RATE

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
