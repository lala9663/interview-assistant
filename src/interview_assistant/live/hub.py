"""Live transcript (FR-05): candidate audio -> streaming STT -> de-identification -> SSE.

When the interviewer records a question in a session with recording consent, the hub publishes the
question as an interviewer segment and starts listening: audio from the `AudioSource` goes through
the streaming STT provider and every result is de-identified before it is published or stored.
Partial results replace each other and are never stored; final results become TranscriptSegment
rows. The answer closes when the STT stream ends (the candidate stopped talking) or when the next
question or the end of the session interrupts it: QAItem.answer_text keeps the raw text (raw zone),
answer_deidentified the tokenised one, and subscribers get `qa.answered`.

A partial result is published without its last word, and without trailing words holding digits
or "@": an identifier cut in half ("홍길", "010 1234") would slip past the detectors. The final
result replaces it whole.

State lives in this process (one channel per session). Several workers need a shared bus.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.deid.service import DeidService
from interview_assistant.live.audio import AudioSource, Turn
from interview_assistant.models import (
    InterviewSession,
    QAItem,
    SessionStatus,
    Speaker,
    TranscriptSegment,
)
from interview_assistant.models.base import as_utc, iso_z, new_id, utcnow
from interview_assistant.providers.base import STTProvider

log = logging.getLogger(__name__)

STATUS_INTERVAL_S = 5
_CLOSED = None  # queue sentinel: the session ended, close the stream
_QUESTION_MS_PER_CHAR = 110  # how long a typed question takes to say, for its segment end


@dataclass
class _Channel:
    subscribers: set[asyncio.Queue[tuple[str, dict[str, Any]] | None]] = field(default_factory=set)
    listener: asyncio.Task[None] | None = None
    listening_to: str | None = None  # QA item id
    stt: str = "ok"
    latency_ms: int | None = None


def stable_prefix(text: str) -> str:
    words = text.split(" ")[:-1]
    while words and re.search(r"[\d@]", words[-1]):
        words.pop()
    return " ".join(words).rstrip()


def segment_event(seg: TranscriptSegment) -> dict[str, Any]:
    return {
        "segment_id": seg.id,
        "qa_item_id": seg.qa_item_id,
        "speaker": seg.speaker.value,
        "text": seg.text_deidentified,
        "is_final": True,
        "start_ms": seg.start_ms,
        "end_ms": seg.end_ms,
    }


def _elapsed_ms(session: InterviewSession) -> int:
    if session.started_at is None:
        return 0
    return max(0, int((utcnow() - as_utc(session.started_at)).total_seconds() * 1000))


def close_answer(db: Session, qa: QAItem, raw: str, deidentified: str) -> dict[str, Any]:
    qa.answer_text = raw
    qa.answer_deidentified = deidentified
    qa.answered_at = utcnow()
    return {
        "qa_item_id": qa.id,
        "answer_deidentified": deidentified,
        "answered_at": iso_z(qa.answered_at),
    }


class LiveHub:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        stt: STTProvider,
        deid: DeidService,
        audio: AudioSource,
        *,
        language: str = "ko-KR",
    ) -> None:
        self.session_factory = session_factory
        self.stt = stt
        self.deid = deid
        self.audio = audio
        self.language = language
        self._channels: dict[str, _Channel] = {}

    def _channel(self, session_id: str) -> _Channel:
        return self._channels.setdefault(session_id, _Channel())

    # --- subscribers ------------------------------------------------------------------------

    def subscribe(self, session_id: str) -> asyncio.Queue[tuple[str, dict[str, Any]] | None]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self._channel(session_id).subscribers.add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[Any]) -> None:
        self._channel(session_id).subscribers.discard(queue)

    def publish(self, session_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in self._channel(session_id).subscribers:
            queue.put_nowait((event, data))

    def status(self, session_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            session = db.get(InterviewSession, session_id)
            live = session is not None and session.status is SessionStatus.in_progress
            recording = live and session.recording_uri is not None
        if not live:
            return {"recording": "stopped", "stt": "off", "latency_ms": None}
        if not recording:
            return {"recording": "off", "stt": "off", "latency_ms": None}
        channel = self._channel(session_id)
        return {"recording": "recording", "stt": channel.stt, "latency_ms": channel.latency_ms}

    async def events(self, session_id: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """The transcript stream of one subscriber: status first and every few seconds, then
        segments and answers as they happen, until the session ends or the client leaves."""
        queue = self.subscribe(session_id)
        try:
            status = self.status(session_id)
            yield "status", status
            if status["recording"] == "stopped":
                return
            self.resume(session_id)
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=STATUS_INTERVAL_S)
                except TimeoutError:
                    yield "status", self.status(session_id)
                    continue
                if item is _CLOSED:
                    yield "status", self.status(session_id)
                    return
                yield item
        finally:
            self.unsubscribe(session_id, queue)

    # --- listening --------------------------------------------------------------------------

    def is_listening(self, session_id: str) -> bool:
        listener = self._channel(session_id).listener
        return listener is not None and not listener.done()

    def listen(self, session_id: str, qa_item_id: str, *, announce: bool = True) -> None:
        """Start transcribing the answer to a question. Callers `interrupt` first so the previous
        answer is closed before the next question is stored; a listener still running here is
        cancelled (its answer closes with what it heard)."""
        channel = self._channel(session_id)
        if channel.listener is not None and not channel.listener.done():
            if channel.listening_to == qa_item_id:
                return
            channel.listener.cancel()
        channel.stt = "ok"
        channel.listening_to = qa_item_id
        channel.listener = asyncio.create_task(self._listen(session_id, qa_item_id, announce))

    def resume(self, session_id: str) -> None:
        """After a restart or reconnect: keep listening to a question that is still unanswered."""
        if self.is_listening(session_id):
            return
        with self.session_factory() as db:
            session = db.get(InterviewSession, session_id)
            if session is None or session.status is not SessionStatus.in_progress:
                return
            if session.recording_uri is None or not session.qa_items:
                return
            last = session.qa_items[-1]
            if last.answered_at is not None:
                return
        self.listen(session_id, last.id, announce=False)

    async def interrupt(self, session_id: str) -> None:
        """Stop listening; whatever was heard so far becomes the answer."""
        listener = self._channel(session_id).listener
        if listener is not None and not listener.done():
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass

    async def end(self, session_id: str) -> None:
        await self.interrupt(session_id)
        channel = self._channel(session_id)
        for queue in channel.subscribers:
            queue.put_nowait(_CLOSED)
        self._channels.pop(session_id, None)

    async def _listen(self, session_id: str, qa_item_id: str, announce: bool) -> None:
        channel = self._channel(session_id)
        with self.session_factory() as db:
            qa = db.get(QAItem, qa_item_id)
            if qa is None:
                return
            session = qa.session
            candidate = session.application.candidate
            candidate_id = candidate.id
            known = self.deid.identity(candidate)
            turn = Turn(session_id, session.application.posting_id, qa.question)
            if announce:
                start = _elapsed_ms(session)
                seg = TranscriptSegment(
                    id=new_id(),
                    session_id=session_id,
                    qa_item_id=qa.id,
                    speaker=Speaker.interviewer,
                    text_deidentified=qa.question,
                    start_ms=start,
                    end_ms=start + max(1500, len(qa.question) * _QUESTION_MS_PER_CHAR),
                )
                db.add(seg)
                db.commit()
                self.publish(session_id, "segment.final", segment_event(seg))
            origin = _elapsed_ms(session)

        heard: list[str] = []
        segment_id: str | None = None
        closed = False

        def deidentify(db: Session, text: str) -> str:
            deid = self.deid.deidentifier(db)
            return deid.deidentify(text, candidate_id=candidate_id, known=known).text

        try:
            async for result in self.stt.stream(self.audio.open(turn), language=self.language):
                received = time.monotonic()
                if not result.is_final:
                    visible = stable_prefix(result.text)
                    if not visible:
                        continue
                    with self.session_factory() as db:
                        text = deidentify(db, visible)
                        db.commit()
                    segment_id = segment_id or new_id()
                    data = {
                        "segment_id": segment_id,
                        "qa_item_id": qa_item_id,
                        "speaker": Speaker.candidate.value,
                        "text": text,
                        "is_final": False,
                        "start_ms": origin + result.start_ms,
                        "end_ms": None,
                    }
                    self.publish(session_id, "segment.partial", data)
                else:
                    heard.append(result.text)
                    with self.session_factory() as db:
                        seg = TranscriptSegment(
                            id=segment_id or new_id(),
                            session_id=session_id,
                            qa_item_id=qa_item_id,
                            speaker=Speaker.candidate,
                            text_deidentified=deidentify(db, result.text),
                            start_ms=origin + result.start_ms,
                            end_ms=origin + result.end_ms,
                        )
                        db.add(seg)
                        db.commit()
                    segment_id = None
                    self.publish(session_id, "segment.final", segment_event(seg))
                channel.latency_ms = round((time.monotonic() - received) * 1000)
            self._close(session_id, qa_item_id, heard)
            closed = True
        except asyncio.CancelledError:
            if not closed:
                self._close(session_id, qa_item_id, heard)
            raise
        except Exception:
            log.exception("streaming STT failed for session %s", session_id)
            channel.stt = "down"
            self.publish(session_id, "status", self.status(session_id))

    def _close(self, session_id: str, qa_item_id: str, heard: list[str]) -> None:
        if not heard:
            return
        with self.session_factory() as db:
            qa = db.get(QAItem, qa_item_id)
            if qa is None or qa.answered_at is not None:
                return
            raw = " ".join(heard)
            deid = self.deid.deidentifier(db)
            candidate_id = qa.session.application.candidate_id
            known = self.deid.identity(qa.session.application.candidate)
            text = deid.deidentify(raw, candidate_id=candidate_id, known=known).text
            data = close_answer(db, qa, raw, text)
            db.commit()
        self.publish(session_id, "qa.answered", data)
