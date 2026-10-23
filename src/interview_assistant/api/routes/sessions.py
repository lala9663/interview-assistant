"""면접 세션 (FR-04, 05, 06, 08): scheduling, consent, start/end, questions, answers, notes.

Every free text a person sends here (typed questions, manual answers, notes) is de-identified
before it is stored where the API can return it; a manual answer's raw text stays in
QAItem.answer_text. Questions start the live transcript when the candidate consented to
recording; ending the session closes the open answer and starts AI scoring in the background.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from interview_assistant.ai.gateway import model_name
from interview_assistant.ai.scoring import score_session
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.interviews import approved_set, session_competency_set
from interview_assistant.live.hub import close_answer
from interview_assistant.models import (
    ActorType,
    AiScoringStatus,
    Application,
    AuditLog,
    CandidateNote,
    FollowUpSuggestion,
    Interviewer,
    InterviewerRole,
    InterviewSession,
    PresetQuestion,
    QAItem,
    QuestionSource,
    SessionInterviewer,
    SessionStatus,
    Speaker,
)
from interview_assistant.models.base import as_utc, iso_z, utcnow

router = APIRouter(tags=["sessions"])


def get_session(db: Db, session_id: str) -> InterviewSession:
    found = db.get(InterviewSession, session_id)
    if found is None:
        raise not_found("면접")
    return found


@router.get("/sessions", response_model=list[s.SessionSummary])
def sessions(db: Db, status: SessionStatus | None = Query(None)) -> list[s.SessionSummary]:
    query = select(InterviewSession)
    if status is not None:
        query = query.where(InterviewSession.status == status)
    rows = views.sort_sessions(db.scalars(query).all(), newest_first=True)
    return [views.session_summary(x) for x in rows]


@router.post("/sessions", response_model=s.SessionSummary, status_code=201)
def create_session(body: s.CreateSessionRequest, db: Db, me: Me) -> s.SessionSummary:
    application = db.get(Application, body.application_id)
    if application is None or application.deleted_at is not None:
        raise not_found("지원서")
    if not body.interviewers:
        raise invalid("interviewers", "면접관을 한 명 이상 지정하세요.")
    if sum(p.role is InterviewerRole.lead for p in body.interviewers) != 1:
        raise invalid("interviewers", "주관 면접관은 한 명이어야 합니다.")
    ids = [p.interviewer_id for p in body.interviewers]
    if len(set(ids)) != len(ids):
        raise invalid("interviewers", "같은 면접관을 두 번 지정할 수 없습니다.")
    if any(db.get(Interviewer, i) is None for i in ids):
        raise not_found("면접관")
    if any(
        x.status in (SessionStatus.scheduled, SessionStatus.in_progress)
        for x in application.sessions
    ):
        raise conflict("이미 예정된 면접이 있습니다.")
    created = InterviewSession(
        application=application,
        mode=body.mode,
        status=SessionStatus.scheduled,
        scheduled_at=as_utc(body.scheduled_at),
    )
    for p in body.interviewers:
        created.interviewers.append(
            SessionInterviewer(interviewer_id=p.interviewer_id, role=p.role)
        )
    db.add(created)
    db.flush()
    audit(
        db,
        me,
        "session.scheduled",
        "interview_session",
        created.id,
        scheduled_at=iso_z(created.scheduled_at),
    )
    db.commit()
    return views.session_summary(created)


@router.get("/sessions/{session_id}", response_model=s.SessionDetail)
def session_detail(session_id: str, db: Db) -> s.SessionDetail:
    return views.session_detail(db, get_session(db, session_id))


@router.post("/sessions/{session_id}/consent", response_model=s.SessionDetail)
def record_consent(session_id: str, body: s.ConsentRequest, db: Db, me: Me) -> s.SessionDetail:
    found = get_session(db, session_id)
    if found.status is not SessionStatus.scheduled:
        raise conflict("면접 시작 전에만 동의를 기록할 수 있습니다.")
    candidate = found.application.candidate
    candidate.consent_recording = body.consent_recording
    candidate.consent_at = utcnow() if body.consent_recording else None
    audit(
        db,
        me,
        "consent.recorded",
        "interview_session",
        found.id,
        consent_recording=body.consent_recording,
    )
    db.commit()
    return views.session_detail(db, found)


@router.post("/sessions/{session_id}/start", response_model=s.SessionDetail)
def start_session(session_id: str, db: Db, me: Me, runtime: RuntimeDep) -> s.SessionDetail:
    found = get_session(db, session_id)
    if found.status is not SessionStatus.scheduled:
        raise conflict("예정된 면접만 시작할 수 있습니다.")
    found.status = SessionStatus.in_progress
    found.started_at = utcnow()
    pinned = approved_set(found.application.posting)
    found.competency_set_id = pinned.id if pinned else None
    if found.application.candidate.consent_recording:
        # Where the recording will live (raw zone). Nothing writes it until step 11 (audio).
        found.recording_uri = (runtime.recordings_dir / f"{found.id}.webm").resolve().as_uri()
    audit(
        db,
        me,
        "session.started",
        "interview_session",
        found.id,
        recording=found.recording_uri is not None,
    )
    db.commit()
    return views.session_detail(db, found)


def close_unanswered(db: Db, session: InterviewSession) -> None:
    """Questions still open (no live listener, e.g. after a restart) are closed with the
    transcript stored for them, if any."""
    for qa in session.qa_items:
        if qa.answered_at is not None or qa.asked_at is None:
            continue
        heard = [
            seg.text_deidentified
            for seg in session.transcript
            if seg.qa_item_id == qa.id and seg.speaker is Speaker.candidate
        ]
        if heard:
            text = " ".join(heard)
            close_answer(db, qa, text, text)


@router.post("/sessions/{session_id}/end", response_model=s.SessionDetail)
async def end_session(session_id: str, db: Db, me: Me, runtime: RuntimeDep) -> s.SessionDetail:
    found = get_session(db, session_id)
    if found.status is not SessionStatus.in_progress:
        raise conflict("진행 중인 면접만 종료할 수 있습니다.")
    await runtime.hub.interrupt(session_id)
    db.expire_all()
    close_unanswered(db, found)
    found.status = SessionStatus.completed
    found.ended_at = utcnow()
    found.ai_scoring_status = AiScoringStatus.running
    found.ai_scoring_started_at = utcnow()
    audit(db, me, "session.completed", "interview_session", found.id)
    db.add(
        AuditLog(
            actor_type=ActorType.ai,
            action="score.ai_started",
            target_type="interview_session",
            target_id=found.id,
            model=model_name(runtime.ai.llm("primary")),
        )
    )
    db.commit()
    await runtime.hub.end(session_id)
    runtime.spawn(score_session(runtime.session_factory, runtime.ai, runtime.deid, session_id))
    return views.session_detail(db, found)


@router.post("/sessions/{session_id}/qa-items", response_model=s.QAItem, status_code=201)
async def create_qa(
    session_id: str, body: s.CreateQARequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.QAItem:
    found = get_session(db, session_id)
    if found.status is not SessionStatus.in_progress:
        raise conflict("진행 중인 면접에서만 질문을 기록할 수 있습니다.")
    question = body.question.strip()
    if not question:
        raise invalid("question", "질문을 입력하세요.")

    preset: PresetQuestion | None = None
    suggestion: FollowUpSuggestion | None = None
    target: str | None = None
    if body.question_source is QuestionSource.preset and body.preset_question_id:
        preset = db.get(PresetQuestion, body.preset_question_id)
        pinned = session_competency_set(db, found)
        if preset is None or pinned is None or preset.competency_set_id != pinned.id:
            raise invalid("preset_question_id", "이 면접의 사전 질문이 아닙니다.")
        target = preset.competency
    elif body.question_source is QuestionSource.ai_suggested:
        if body.suggestion is None:
            raise invalid("suggestion", "사용한 제안 정보가 필요합니다.")
        suggestion = db.get(FollowUpSuggestion, body.suggestion.suggestion_id)
        if (
            suggestion is None
            or suggestion.batch_id != body.suggestion.batch_id
            or suggestion.qa_item.session_id != found.id
        ):
            raise invalid("suggestion", "알 수 없는 제안입니다.")
        if suggestion.used_qa_item_id is not None:
            raise conflict("이미 질문으로 쓴 제안입니다.")
        target = suggestion.competency

    # A new question ends the answer in progress.
    await runtime.hub.interrupt(session_id)
    db.expire_all()
    close_unanswered(db, found)

    candidate = found.application.candidate
    last = db.scalar(select(func.max(QAItem.seq)).where(QAItem.session_id == found.id)) or 0
    now = utcnow()
    qa = QAItem(
        session_id=found.id,
        seq=last + 1,
        question=runtime.deid.deidentify(db, question, candidate),
        question_source=body.question_source,
        preset_question_id=preset.id if preset else None,
        target_competency=target,
        asked_at=now,
    )
    db.add(qa)
    db.flush()
    details: dict[str, object] = {"question_source": body.question_source.value}
    if suggestion is not None and body.suggestion is not None:
        suggestion.used_qa_item_id = qa.id
        suggestion.edited = body.suggestion.edited or question != suggestion.question
        suggestion.used_at = now
        details |= {"suggestion_id": suggestion.id, "edited": suggestion.edited}
    audit(db, me, "qa.created", "interview_session", found.id, **details)
    db.commit()
    if found.recording_uri is not None:
        runtime.hub.listen(found.id, qa.id)
    return s.QAItem.model_validate(qa)


@router.patch("/qa-items/{qa_item_id}", response_model=s.QAItem)
async def answer_qa(
    qa_item_id: str, body: s.UpdateQARequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.QAItem:
    qa = db.get(QAItem, qa_item_id)
    if qa is None:
        raise not_found("질문")
    if qa.session.status is not SessionStatus.in_progress:
        raise conflict("진행 중인 면접에서만 답변을 기록할 수 있습니다.")
    text = body.answer_text.strip()
    if not text:
        raise invalid("answer_text", "답변을 입력하세요.")
    # STT failed mid-answer: the typed answer replaces whatever the listener had.
    if runtime.hub.is_listening(qa.session_id):
        await runtime.hub.interrupt(qa.session_id)
        db.expire_all()
    close_answer(db, qa, text, runtime.deid.deidentify(db, text, qa.session.application.candidate))
    audit(db, me, "qa.answered", "interview_session", qa.session_id, qa_item_id=qa.id, manual=True)
    db.commit()
    return s.QAItem.model_validate(qa)


@router.post("/sessions/{session_id}/notes", response_model=s.CandidateNote, status_code=201)
def create_note(
    session_id: str, body: s.CreateNoteRequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.CandidateNote:
    found = get_session(db, session_id)
    content = body.content.strip()
    if not content:
        raise invalid("content", "메모를 입력하세요.")
    note = CandidateNote(
        session_id=found.id,
        author_id=me.id,
        content=runtime.deid.deidentify(db, content, found.application.candidate),
    )
    db.add(note)
    db.flush()
    audit(db, me, "note.created", "interview_session", found.id)
    db.commit()
    return s.CandidateNote.model_validate(note)
