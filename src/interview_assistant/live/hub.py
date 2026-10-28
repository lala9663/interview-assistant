"""Live transcript (FR-05): candidate audio -> streaming STT -> de-identification -> SSE.

When the interviewer records a question in a session with recording consent, the hub publishes the
question as an interviewer segment and starts listening: audio from the `AudioSource` goes through
the streaming STT provider and every result is de-identified before it is published or stored.
Partial results replace each other and are never stored; final results become TranscriptSegment
rows. The answer closes when the STT stream ends (the candidate stopped talking) or when the next
question or the end of the session interrupts it: QAItem.answer_text keeps the raw text (raw zone),
answer_deidentified the tokenised one, and subscribers get `qa.answered`.

The audio source is the session's microphone once the browser attached one (live/microphone.py,
api/routes/audio.py), else the default source (the simulated candidate). With a microphone an
answer can come in parts: the end-of-answer detector ends a part, the answer closes
(`qa.answered`, follow-ups start), and if the candidate goes on, the next part is appended to the
same answer and `qa.answered` comes again with the longer text. The microphone's role switches
between the candidate and the interviewer (one microphone in a face-to-face interview): what the
interviewer says becomes interviewer segments, and the route turns a question asked aloud into
the next QAItem (`set_role` returns it).

The STT provider is the one the session pinned when it started (admin > 모델 설정 may switch the
active one meanwhile); its model name is stored on every candidate segment and in an audit row per
answer. If it cannot read what the audio source yields (a real STT and the simulated candidate's
text, or no VAD for the microphone), the hub reports `stt: down` with an error code
(live/codes.py) and the interviewer types the answer instead.

While the candidate talks, the de-identified answer so far is embedded in the background
(live/prefetch.py), so the follow-up search finds it ready when the answer closes.

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
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import model_name
from interview_assistant.deid.service import DeidService
from interview_assistant.live import codes
from interview_assistant.live.audio import AudioSource, Turn
from interview_assistant.live.microphone import CANDIDATE, INTERVIEWER, PREROLL_MS, MicrophoneSource
from interview_assistant.live.prefetch import AnswerPrefetch
from interview_assistant.models import (
    ActorType,
    AuditLog,
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
    error: str | None = None  # code shown on screen (live/codes.py)
    mic: MicrophoneSource | None = None
    asker: asyncio.Task[None] | None = None  # transcribes the interviewer asking aloud
    spoken: list[tuple[str, str]] = field(default_factory=list)  # (segment id, raw text), no question yet
    quiet: bool = False  # the listener moves to another source: do not close its answer
    prefetch: AnswerPrefetch | None = None


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
        stt_for: Callable[[InterviewSession], STTProvider],
        deid: DeidService,
        audio: AudioSource,
    ) -> None:
        self.session_factory = session_factory
        self.stt_for = stt_for  # the session's pinned streaming STT
        self.deid = deid
        self.audio = audio  # used while no microphone is attached
        self.retrieval: Any = None  # set by the runtime: answers are embedded ahead (prefetch)
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
        return {
            "recording": "recording",
            "stt": channel.stt,
            "latency_ms": channel.latency_ms,
            "error": codes.describe(channel.error) if channel.error else None,
            "mic": channel.mic.status() if channel.mic is not None else None,
        }

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

    # --- sources ----------------------------------------------------------------------------

    def source_for(self, session_id: str) -> AudioSource:
        """The session's microphone once one was attached (also while it is off), else the
        default source."""
        mic = self._channel(session_id).mic
        return mic if mic is not None else self.audio

    def microphone(self, session_id: str) -> MicrophoneSource | None:
        return self._channel(session_id).mic

    async def attach_microphone(self, session_id: str, mic: MicrophoneSource) -> None:
        """Use `mic` for this session from now on. An answer being heard from another source
        moves to the microphone without being closed."""
        channel = self._channel(session_id)
        mic.on_change = lambda: self.publish(session_id, "status", self.status(session_id))
        if channel.mic is mic:
            return
        channel.mic = mic
        listener = channel.listener
        if listener is not None and not listener.done():
            channel.quiet = True
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            channel.quiet = False
        self.resume(session_id)
        self.publish(session_id, "status", self.status(session_id))

    def microphone_attached(self, session_id: str) -> None:
        """The browser (re)connected the session's microphone: go on with whoever has the turn."""
        channel = self._channel(session_id)
        mic = channel.mic
        if mic is None:
            return
        if mic.role == INTERVIEWER:
            if channel.asker is None or channel.asker.done():
                channel.asker = asyncio.create_task(self._ask(session_id))
        else:
            self.resume(session_id)

    # --- listening --------------------------------------------------------------------------

    def is_listening(self, session_id: str) -> bool:
        listener = self._channel(session_id).listener
        return listener is not None and not listener.done()

    def listen(self, session_id: str, qa_item_id: str, *, announce: bool = True) -> None:
        """Start transcribing the answer to a question. Callers `interrupt` first so the previous
        answer is closed before the next question is stored; a listener still running here is
        cancelled (its answer closes with what it heard). Interviewer segments of a question
        asked aloud and not attached to a question yet are attached to this one."""
        channel = self._channel(session_id)
        if channel.listener is not None and not channel.listener.done():
            if channel.listening_to == qa_item_id:
                return
            channel.listener.cancel()
        channel.stt = "ok"
        channel.error = None
        channel.listening_to = qa_item_id
        if channel.mic is not None:
            channel.mic.set_role(CANDIDATE)
        channel.listener = asyncio.create_task(self._listen(session_id, qa_item_id, announce))

    def resume(self, session_id: str) -> None:
        """After a restart or reconnect: keep listening to a question that is still unanswered."""
        if self.is_listening(session_id):
            return
        mic = self._channel(session_id).mic
        if mic is not None and mic.role != CANDIDATE:
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
        """Stop listening; whatever was heard so far becomes the answer. A question being asked
        aloud is transcribed to its end, and the microphone goes back to the candidate."""
        channel = self._channel(session_id)
        listener = channel.listener
        if listener is not None and not listener.done():
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass
        if channel.mic is not None and channel.mic.role != CANDIDATE:
            channel.mic.set_role(CANDIDATE)
        await self._stop_asking(channel)

    async def end(self, session_id: str) -> list[tuple[int, str]]:
        """The session ended. Returns the microphone's role timeline (for retranscription)."""
        await self.interrupt(session_id)
        channel = self._channel(session_id)
        if channel.prefetch is not None:
            channel.prefetch.cancel()
        timeline: list[tuple[int, str]] = []
        if channel.mic is not None:
            channel.mic.close()
            timeline = channel.mic.timeline
        for queue in channel.subscribers:
            queue.put_nowait(_CLOSED)
        self._channels.pop(session_id, None)
        return timeline

    @staticmethod
    def _unreadable(source: AudioSource, stt: Any) -> str | None:
        """Why `stt` cannot transcribe `source` (an error code), or None when it can."""
        if isinstance(source, MicrophoneSource) and not source.transcribable:
            return codes.VAD_MISSING
        accepts = getattr(stt, "accepts", ())
        if source.format in accepts:
            return None
        return codes.STT_FORMAT if accepts else codes.STT_MISSING  # empty: could not be built

    def _prefetch(self, session_id: str) -> AnswerPrefetch:
        channel = self._channel(session_id)
        if channel.prefetch is None or channel.prefetch.retrieval is not self.retrieval:
            channel.prefetch = AnswerPrefetch(self.retrieval)
        return channel.prefetch

    def prefetch(self, session_id: str, texts: list[str], known: Any) -> None:
        """Embed a question just asked ahead of its follow-ups, also when nothing is recorded
        (answers typed in): the follow-up search compares candidates with it."""
        self._prefetch(session_id).push(texts, known)

    async def _listen(self, session_id: str, qa_item_id: str, announce: bool) -> None:
        channel = self._channel(session_id)
        source = self.source_for(session_id)
        with self.session_factory() as db:
            qa = db.get(QAItem, qa_item_id)
            if qa is None:
                return
            session = qa.session
            candidate = session.application.candidate
            candidate_id = candidate.id
            known = self.deid.identity(candidate)
            turn = Turn(session_id, session.application.posting_id, qa.question)
            stt = self.stt_for(session)
            model = model_name(stt)
            unreadable = self._unreadable(source, stt)
            db.add(
                AuditLog(
                    actor_type=ActorType.ai,
                    action="transcript.listened" if unreadable is None else "transcript.unsupported_audio",
                    target_type="interview_session",
                    target_id=session_id,
                    model=model,
                    details={"qa_item_id": qa.id, "audio": source.format, "error": unreadable},
                )
            )
            if channel.spoken:  # the question was asked aloud before it was recorded
                for seg_id, _ in channel.spoken:
                    spoken = db.get(TranscriptSegment, seg_id)
                    if spoken is not None:
                        spoken.qa_item_id = qa.id
                channel.spoken = []
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
            asked = [q.question for q in session.qa_items]
            db.commit()
            floor = 0  # the answer does not start before its question
            if announce:
                floor = seg.start_ms
                self.publish(session_id, "segment.final", segment_event(seg))

        if unreadable is not None:
            log.warning(
                "streaming STT %s cannot read %s audio (session %s, %s): manual answers",
                model,
                source.format,
                session_id,
                unreadable,
            )
            channel.stt = "down"
            channel.error = unreadable
            self.publish(session_id, "status", self.status(session_id))
            return

        prefetch = self._prefetch(session_id)
        prefetch.push(asked, known)
        preroll = PREROLL_MS if isinstance(source, MicrophoneSource) else 0
        if isinstance(source, MicrophoneSource):
            source.keep_recent()  # talk before this question is not its answer
        heard: list[str] = []
        answer = ""  # the de-identified answer so far, exactly as it will be stored
        stored: str | None = None  # the raw answer this listener stored last

        def deidentify(db: Session, text: str) -> str:
            deid = self.deid.deidentifier(db)
            return deid.deidentify(text, candidate_id=candidate_id, known=known).text

        try:
            while True:
                segment_id: str | None = None
                origin = max(_elapsed_ms(session) - preroll, floor)
                language = str(getattr(stt, "language", "ko-KR"))
                async for result in stt.stream(source.open(turn), language=language):
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
                                model=model,
                            )
                            db.add(seg)
                            answer = deidentify(db, " ".join(heard))
                            db.commit()
                        segment_id = None
                        self.publish(session_id, "segment.final", segment_event(seg))
                        prefetch.push([answer], known)
                    channel.latency_ms = round((time.monotonic() - received) * 1000)
                stored = self._close(session_id, qa_item_id, heard, answer, stored)
                if not await source.more(turn):
                    break
        except asyncio.CancelledError:
            if not channel.quiet:
                self._close(session_id, qa_item_id, heard, answer, stored)
            raise
        except Exception:
            log.exception("streaming STT failed for session %s", session_id)
            channel.stt = "down"
            channel.error = codes.STT_FAILED
            self.publish(session_id, "status", self.status(session_id))

    def _close(
        self,
        session_id: str,
        qa_item_id: str,
        heard: list[str],
        answer: str,
        stored: str | None,
    ) -> str | None:
        """Store what was heard as the answer and publish `qa.answered`. A later part of the same
        answer stores the longer text, unless someone else (a typed answer) wrote the answer
        meanwhile. Returns the raw answer this listener has stored."""
        if not heard:
            return stored
        raw = " ".join(heard)
        if raw == stored:
            return stored
        with self.session_factory() as db:
            qa = db.get(QAItem, qa_item_id)
            if qa is None:
                return stored
            if qa.answered_at is not None and (stored is None or qa.answer_text != stored):
                return stored
            if not answer:
                deid = self.deid.deidentifier(db)
                candidate_id = qa.session.application.candidate_id
                known = self.deid.identity(qa.session.application.candidate)
                answer = deid.deidentify(raw, candidate_id=candidate_id, known=known).text
            data = close_answer(db, qa, raw, answer)
            db.commit()
        self.publish(session_id, "qa.answered", data)
        return raw

    # --- the interviewer asking aloud -------------------------------------------------------

    async def set_role(self, session_id: str, role: str) -> list[tuple[str, str]]:
        """Switch the microphone between the candidate and the interviewer. To the interviewer:
        the answer in progress closes and what is said becomes interviewer segments. Back to the
        candidate: returns the question asked aloud meanwhile (segment ids, raw text), which the
        caller turns into the next question or not; it is attached by the next `listen`."""
        channel = self._channel(session_id)
        mic = channel.mic
        if mic is None:
            raise LookupError("no microphone attached")
        if role == INTERVIEWER:
            if mic.role != INTERVIEWER:
                await self.interrupt(session_id)
                channel.spoken = []
                mic.set_role(INTERVIEWER)
                channel.asker = asyncio.create_task(self._ask(session_id))
            return []
        mic.set_role(CANDIDATE)
        await self._stop_asking(channel)
        return list(channel.spoken)

    @staticmethod
    async def _stop_asking(channel: _Channel) -> None:
        """Wait for the interviewer's last words to be transcribed (the part already ended)."""
        asker, channel.asker = channel.asker, None
        if asker is None or asker.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(asker), timeout=30)
        except TimeoutError:
            asker.cancel()
            await asyncio.gather(asker, return_exceptions=True)

    async def _ask(self, session_id: str) -> None:
        """Transcribe the interviewer until the microphone goes back to the candidate."""
        channel = self._channel(session_id)
        mic = channel.mic
        if mic is None:
            return
        with self.session_factory() as db:
            session = db.get(InterviewSession, session_id)
            if session is None:
                return
            candidate = session.application.candidate
            candidate_id = candidate.id
            known = self.deid.identity(candidate)
            stt = self.stt_for(session)
            model = model_name(stt)
            turn = Turn(session_id, session.application.posting_id, "", speaker=INTERVIEWER)
            origin = _elapsed_ms(session) - PREROLL_MS
        if self._unreadable(mic, stt) is not None:
            return

        def deidentify(db: Session, text: str) -> str:
            deid = self.deid.deidentifier(db)
            return deid.deidentify(text, candidate_id=candidate_id, known=known).text

        segment_id: str | None = None
        try:
            language = str(getattr(stt, "language", "ko-KR"))
            async for result in stt.stream(mic.open(turn), language=language):
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
                        "qa_item_id": None,
                        "speaker": Speaker.interviewer.value,
                        "text": text,
                        "is_final": False,
                        "start_ms": origin + result.start_ms,
                        "end_ms": None,
                    }
                    self.publish(session_id, "segment.partial", data)
                    continue
                with self.session_factory() as db:
                    seg = TranscriptSegment(
                        id=segment_id or new_id(),
                        session_id=session_id,
                        qa_item_id=None,
                        speaker=Speaker.interviewer,
                        text_deidentified=deidentify(db, result.text),
                        start_ms=origin + result.start_ms,
                        end_ms=origin + result.end_ms,
                        model=model,
                    )
                    db.add(seg)
                    db.commit()
                segment_id = None
                channel.spoken.append((seg.id, result.text))
                self.publish(session_id, "segment.final", segment_event(seg))
        except Exception:
            log.exception("transcribing the interviewer failed for session %s", session_id)
