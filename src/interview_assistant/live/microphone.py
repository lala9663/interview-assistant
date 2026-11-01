"""The interview room's microphone as an `AudioSource` (docs/audio-input.md).

The browser converts its microphone (or, for development and diagnosis, a sample WAV) to 16 kHz
mono 16-bit PCM and sends it over a WebSocket, or in HTTP chunks where WebSockets are blocked
(api/routes/audio.py). Every chunk goes through `feed`:

1. With consent, the raw chunk is appended to the session's WAV in the raw zone (live/recording.py).
2. Noise suppression (off by default, `audio.denoise`): the microphone's own stream of the model,
   same length out, `delay_samples` late (RNNoise about 35 ms, DeepFilterNet about 45 ms), so the
   VAD, STT and end-of-answer detector all hear the same, slightly later audio.
3. Silero VAD marks each 32 ms frame speech or not (`audio.vad`, with hysteresis).
4. Only speech goes to STT: frames that are not speech, or within `speech_pad_ms` after it, or
   the `PREROLL_MS` before it, are replaced by digital silence of the same length. The stream
   keeps its timing, and Whisper never decodes room noise (where it would invent words).
   The pre-roll delays what STT receives by `PREROLL_MS`.
5. While the candidate answers, the end-of-answer tracker (`audio.turn`: silence or Smart Turn)
   sees every frame; when it decides the answer is over, the part ends: `open` returns, the STT
   stream flushes and the hub closes the answer. If the candidate goes on, `more` returns and the
   hub appends the next part to the same answer.

The role decides whose speech it is: `candidate` (answers, with end-of-answer detection) or
`interviewer` (a question asked aloud into the same microphone, no end-of-answer detection).
Switching ends the part in progress. Audio stays in memory and the raw zone; nothing here sends it
anywhere else.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import math
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from interview_assistant.live.audio import AudioSource, Turn
from interview_assistant.live.recording import WavRecorder
from interview_assistant.providers.base import (
    PCM16_16K,
    DenoiseProvider,
    TurnProvider,
    TurnTracker,
    VADProvider,
)

log = logging.getLogger(__name__)

FRAME = 512  # samples, Silero's frame at 16 kHz
FRAME_MS = 32
PREROLL_MS = 128  # audio before the VAD's first speech frame that goes to STT with it
BACKLOG_MS = 320  # audio kept while no part is open and nobody speaks, for the next part's start
HOLD_MS = 60_000  # speech kept while no part is open (the hub is still closing the last one)
NEW_QUESTION_MS = 1500  # of what was held, what a new question's answer starts with

CANDIDATE = "candidate"
INTERVIEWER = "interviewer"


class SpeechState:
    """Speech probability -> speech, with hysteresis: on from `threshold`, off below it - 0.15."""

    def __init__(self, threshold: float) -> None:
        self.on = threshold
        self.off = max(threshold - 0.15, 0.01)
        self.speaking = False

    def update(self, probability: float) -> bool:
        if probability >= self.on:
            self.speaking = True
        elif probability < self.off:
            self.speaking = False
        return self.speaking


def speech_flags(vad: VADProvider, audio: Any) -> Any:
    """Speech or not for every whole frame of `audio` (float32, 16 kHz), as the microphone path
    decides it (tests, the admin connection test, scripts/bench_turns.py)."""
    import numpy as np

    n = len(audio) // FRAME
    probabilities = vad.stream().probabilities(np.asarray(audio[: n * FRAME]).reshape(-1, FRAME))
    state = SpeechState(vad.threshold)
    return np.array([state.update(float(p)) for p in probabilities], dtype=bool)


class MicrophoneSource(AudioSource):
    format = PCM16_16K

    def __init__(
        self,
        *,
        vad: VADProvider | None,
        turn: TurnProvider | None,
        denoise: DenoiseProvider | None = None,
        recorder: WavRecorder | None = None,
        on_change: Callable[[], None] | None = None,
        notices: tuple[str, ...] = (),
    ) -> None:
        self.vad = vad
        self.turn = turn
        self.denoise = denoise
        self._denoise = denoise.stream() if denoise is not None and denoise.enabled else None
        self.recorder = recorder
        self.on_change = on_change or (lambda: None)
        self.notices: list[str] = list(notices)  # codes shown on screen (TURN-MISSING ...)
        self.role = CANDIDATE
        self.closed = False
        self.connected = False
        self.transport: str | None = None
        self.stream_id: str | None = None
        self.last_seen = 0.0  # monotonic time of the last chunk
        self.last_seq = -1  # HTTP chunks: the last sequence number fed
        self.speaking = False
        self.received_ms = 0
        self.last_end: dict[str, Any] | None = None  # how the last answer part ended
        self.timeline: list[tuple[int, str]] = []  # (position in the recording ms, role) per change
        self.ended_at: float | None = None  # monotonic time of that end
        self._rest = b""
        self._voice = vad.stream() if vad is not None else None
        self._state = SpeechState(vad.threshold if vad is not None else 0.5)
        self._preroll = math.ceil(PREROLL_MS / FRAME_MS)
        self._pad = math.ceil(vad.speech_pad_ms / FRAME_MS) if vad is not None else 0
        self._hangover = 0
        self._delay: collections.deque[list[Any]] = collections.deque()  # [frame bytes, keep]
        self._backlog: collections.deque[bytes] = collections.deque(maxlen=HOLD_MS // FRAME_MS)
        self._holding = False  # speech came while no part was open: keep all of it for the next
        self._replay: collections.deque[tuple[bool, Any]] = collections.deque(maxlen=HOLD_MS // FRAME_MS)
        self._consumer: asyncio.Queue[bytes | None] | None = None
        self._tracker: TurnTracker | None = None
        self._onset = asyncio.Event()

    @property
    def transcribable(self) -> bool:
        """Without a VAD nothing is transcribed (the recording still runs)."""
        return self._voice is not None

    # --- connection -------------------------------------------------------------------------

    def attach(self, transport: str, stream_id: str) -> None:
        self.connected = True
        self.transport = transport
        self.stream_id = stream_id
        self.last_seen = time.monotonic()
        self.last_seq = -1
        self._mark()
        self.on_change()

    def detach(self) -> None:
        """The browser stopped sending: the part in progress ends with what was heard."""
        self.connected = False
        self.transport = None
        self.stream_id = None
        self._state.speaking = self.speaking = False
        self._flush()
        self._end_part()
        self._backlog.clear()
        self._replay.clear()
        self._holding = False
        if self.recorder is not None:
            self.recorder.close()
        self.on_change()

    def _mark(self) -> None:
        if self.recorder is not None:
            self.timeline.append((round(self.recorder.seconds * 1000), self.role))

    def close(self) -> None:
        """The session ended: the connection is told to stop (`closed`), the recording closes."""
        self.closed = True
        self.detach()

    def set_role(self, role: str) -> None:
        if role == self.role:
            return
        self.role = role
        self._mark()
        self._flush()
        self._end_part()
        self._backlog.clear()
        self._replay.clear()
        self._holding = False
        self._onset.clear()
        self.on_change()

    # --- audio in ---------------------------------------------------------------------------

    async def feed(self, pcm: bytes) -> None:
        """One chunk from the browser (any length, PCM16 little-endian)."""
        self.last_seen = time.monotonic()
        if self.recorder is not None:
            self.recorder.write(pcm)
        if self._denoise is not None:
            pcm = self._denoise.process(pcm)
        data = self._rest + pcm
        usable = len(data) - len(data) % (FRAME * 2)
        self._rest = data[usable:]
        if not usable:
            return
        import numpy as np

        frames = np.frombuffer(data[:usable], dtype="<i2").reshape(-1, FRAME)
        if self._voice is None:
            self.received_ms += len(frames) * FRAME_MS
            return
        floats = frames.astype(np.float32) / 32768.0
        probabilities = self._voice.probabilities(floats)
        was = self.speaking
        for raw, samples, probability in zip(frames, floats, probabilities, strict=True):
            self.received_ms += FRAME_MS
            speech = self._state.update(float(probability))
            self._gate(raw.tobytes(), speech)
            if speech and self._consumer is None:
                self._holding = True
                if self.role == CANDIDATE:
                    self._onset.set()
            if self._consumer is None and self._holding:
                self._replay.append((speech, samples))  # for the next part's end-of-answer tracker
            tracker = self._tracker
            if tracker is not None and await tracker.push(speech, samples):
                self._ended(tracker)
                self._flush()
                self._end_part()
        self.speaking = self._state.speaking
        if self.speaking != was:
            self.on_change()

    def keep_recent(self, ms: int = NEW_QUESTION_MS) -> None:
        """A new question is being listened to: what was said before it (held while no part was
        open) is not its answer, except the last moment (the candidate starting right away)."""
        frames = max(1, ms // FRAME_MS)
        while len(self._backlog) > frames:
            self._backlog.popleft()
        while len(self._replay) > frames:
            self._replay.popleft()

    def _ended(self, tracker: TurnTracker) -> None:
        probability = None if tracker.probability is None else round(tracker.probability, 3)
        self.last_end = {"reason": tracker.reason, "probability": probability, "at_ms": self.received_ms}
        self.ended_at = time.monotonic()

    def _gate(self, frame: bytes, speech: bool) -> None:
        """Delay line of `_preroll` frames: speech marks the frames before it to keep, then
        `_pad` frames after it; everything else leaves as silence."""
        if speech:
            for entry in self._delay:
                entry[1] = True
            self._hangover = self._pad
            keep = True
        else:
            keep = self._hangover > 0
            self._hangover = max(0, self._hangover - 1)
        self._delay.append([frame, keep])
        if len(self._delay) > self._preroll:
            self._emit(*self._delay.popleft())

    def _flush(self) -> None:
        while self._delay:
            self._emit(*self._delay.popleft())

    def _emit(self, frame: bytes, keep: bool) -> None:
        out = frame if keep else bytes(len(frame))
        if self._consumer is not None:
            self._consumer.put_nowait(out)
        else:
            self._backlog.append(out)
            if not self._holding:
                while len(self._backlog) > BACKLOG_MS // FRAME_MS:
                    self._backlog.popleft()

    def _end_part(self) -> None:
        if self._consumer is not None:
            self._consumer.put_nowait(None)
            self._consumer = None
        self._tracker = None
        self._onset.clear()

    # --- audio out (AudioSource) ------------------------------------------------------------

    async def open(self, turn: Turn) -> AsyncIterator[bytes]:
        """The gated audio from now until the answer part ends (end of answer, role switch,
        microphone off). One reader at a time: a new `open` ends the previous one."""
        self._end_part()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._consumer = queue
        tracker = self.turn.tracker(FRAME_MS) if turn.speaker == CANDIDATE and self.turn is not None else None
        held, self._replay = list(self._replay), collections.deque(maxlen=HOLD_MS // FRAME_MS)
        if self._backlog:
            queue.put_nowait(b"".join(self._backlog))
            self._backlog.clear()
        self._holding = False
        ended = False
        for speech, samples in held if tracker is not None else ():
            if await tracker.push(speech, samples):  # what was said before this part opened
                self._ended(tracker)
                ended = True
                break
        if ended or self._consumer is not queue:
            queue.put_nowait(None)
        else:
            self._tracker = tracker
        try:
            while (chunk := await queue.get()) is not None:
                yield chunk
        finally:
            if self._consumer is queue:
                self._consumer = None
                self._tracker = None

    async def more(self, turn: Turn) -> bool:
        """After an answer part ended: wait for the candidate's next speech (the hub cancels this
        when the next question is recorded or the role switches)."""
        if turn.speaker != CANDIDATE:
            return False
        while True:
            await self._onset.wait()
            self._onset.clear()
            if self.role == CANDIDATE:
                return True

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "transport": self.transport,
            "role": self.role,
            "speaking": self.speaking,
            "turn": getattr(self.turn, "model", None),
            "notices": list(self.notices),
            "last_end": self.last_end,
        }
