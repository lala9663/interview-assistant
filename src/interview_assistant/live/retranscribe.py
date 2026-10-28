"""After the interview: the recording transcribed again by the STT 사후 model (docs/audio-input.md 8장).

Without a GPU, a model that keeps up live is small and makes mistakes (Whisper small: CER 13% on
this laptop); a model that is accurate is too slow live (large-v3: 30 s of audio in ~36 s). With
"면접 뒤 녹음 재전사" on the STT 사후 role, the interview runs live on the small model and, once
it ends, the WAV in the raw zone (consent only) goes through the batch model; the result is stored
as `source = "batch"` segments next to the live ones (GET /sessions/{id}/transcript?source=batch).

Segments are de-identified like everything else stored. Times are positions in the recording (the
microphone audio as received, without the time it was off). Whose speech it is comes from the
microphone's role timeline (질문 중 / 답변 듣는 중) when this process still has it; otherwise every
segment counts as the candidate's. Not done yet: splitting the batch transcript per question and
scoring on it; the live answers stay what AI scoring reads.
"""

from __future__ import annotations

import bisect
import logging
import time
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import model_name
from interview_assistant.deid.service import DeidService
from interview_assistant.models import ActorType, AuditLog, InterviewSession, Speaker, TranscriptSegment
from interview_assistant.providers.audio import uri_to_path

log = logging.getLogger(__name__)

HEADER = 44


def speaker_at(timeline: list[tuple[int, str]], at_ms: int) -> Speaker:
    """The microphone's role at a position of the recording."""
    if not timeline:
        return Speaker.candidate
    index = bisect.bisect_right([ms for ms, _ in timeline], at_ms) - 1
    return Speaker(timeline[max(0, index)][1])


async def retranscribe(
    session_factory: sessionmaker[Session],
    stt: Any,
    deid: DeidService,
    session_id: str,
    timeline: list[tuple[int, str]] | None = None,
) -> int:
    """Transcribe the session's recording with `stt` and store it; returns the segments stored.
    A second run replaces the first."""
    model = model_name(stt)
    with session_factory() as db:
        session = db.get(InterviewSession, session_id)
        if session is None or session.recording_uri is None:
            return 0
        uri = session.recording_uri
        candidate = session.application.candidate
        candidate_id = candidate.id
        known = deid.identity(candidate)
    path = uri_to_path(uri)
    seconds = (path.stat().st_size - HEADER) / 32000 if path.is_file() else 0.0

    def record(action: str, **details: Any) -> None:
        with session_factory() as db:
            db.add(
                AuditLog(
                    actor_type=ActorType.ai,
                    action=action,
                    target_type="interview_session",
                    target_id=session_id,
                    model=model,
                    details=details,
                )
            )
            db.commit()

    if seconds <= 0:
        record("transcript.retranscribe_skipped", reason="no recording")
        return 0
    started = time.perf_counter()
    try:
        segments = await stt.transcribe(uri)
    except Exception as exc:
        log.exception("retranscribing session %s failed", session_id)
        record("transcript.retranscribe_failed", error=type(exc).__name__, audio_seconds=round(seconds, 1))
        return 0
    stored = 0
    with session_factory() as db:
        deidentifier = deid.deidentifier(db)
        db.execute(
            delete(TranscriptSegment).where(
                TranscriptSegment.session_id == session_id, TranscriptSegment.source == "batch"
            )
        )
        for segment in segments:
            if not segment.text.strip():
                continue
            text = deidentifier.deidentify(segment.text, candidate_id=candidate_id, known=known).text
            db.add(
                TranscriptSegment(
                    session_id=session_id,
                    qa_item_id=None,
                    speaker=speaker_at(timeline or [], segment.start_ms),
                    text_deidentified=text,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    model=model,
                    source="batch",
                )
            )
            stored += 1
        db.commit()
    record(
        "transcript.retranscribed",
        segments=stored,
        audio_seconds=round(seconds, 1),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
    return stored
