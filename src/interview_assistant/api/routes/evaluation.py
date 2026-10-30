"""평가 (FR-07, 08): AI and interviewer scores side by side, never combined; the round's decision
(N차 결정) and the points a later round should check.

Interviewer scores are one per competency for the whole session (Score.qa_item_id is null). A
resubmission replaces the interviewer's previous scores; comments, decision reasons and points to
check are de-identified like any other free text. Decisions are people's: AI scores are reference
only, and the official result of a final candidate is recorded on the recruiting site.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete

from interview_assistant.ai.gateway import model_name
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.api.routes.sessions import get_session
from interview_assistant.interviews import current_decision, is_last_round, session_competency_set
from interview_assistant.models import (
    AiScoringStatus,
    Application,
    CheckPoint,
    CheckPointSource,
    EvaluatorType,
    InterviewSession,
    RoundDecision,
    Score,
    SessionStatus,
)
from interview_assistant.models.base import utcnow

router = APIRouter(tags=["evaluation"])

MAX_REASON = 1000


def _view(db: Db, found: InterviewSession, runtime: RuntimeDep, me: Me) -> s.Evaluation:
    return views.evaluation(db, found, model_name(runtime.pinned(found).ai.llm("primary")), me)


@router.get("/sessions/{session_id}/evaluation", response_model=s.Evaluation)
def evaluation(session_id: str, db: Db, me: Me, runtime: RuntimeDep) -> s.Evaluation:
    """AI scores are left out (`ai.hidden`) for an interviewer of the session who has not
    submitted their own scores yet, so their judgement is made before seeing the AI's."""
    return _view(db, get_session(db, session_id), runtime, me)


@router.post("/sessions/{session_id}/ai-scores/reveal", response_model=s.Evaluation)
def reveal_ai_scores(session_id: str, db: Db, me: Me, runtime: RuntimeDep) -> s.Evaluation:
    """그래도 보기: an interviewer chooses to see the AI scores before submitting their own. The
    choice is kept (they keep seeing them) and audited as evaluation.ai_revealed."""
    found = get_session(db, session_id)
    if found.ai_scoring_status is not AiScoringStatus.completed:
        raise conflict("AI 채점이 끝난 뒤에 볼 수 있습니다.")
    link = next((x for x in found.interviewers if x.interviewer_id == me.id), None)
    if link is not None and link.submitted_at is None and link.ai_revealed_at is None:
        link.ai_revealed_at = utcnow()
        audit(db, me, "evaluation.ai_revealed", "interview_session", found.id, before_submitting=True)
        db.commit()
        db.expire_all()
        found = get_session(db, session_id)
    return _view(db, found, runtime, me)


@router.put("/sessions/{session_id}/scores/{interviewer_id}", response_model=s.Evaluation)
def submit_scores(
    session_id: str,
    interviewer_id: str,
    body: s.SubmitInterviewerScoresRequest,
    db: Db,
    me: Me,
    runtime: RuntimeDep,
) -> s.Evaluation:
    found = get_session(db, session_id)
    if found.status is not SessionStatus.completed:
        raise conflict("종료된 면접만 평가할 수 있습니다.")
    link = next((x for x in found.interviewers if x.interviewer_id == interviewer_id), None)
    if link is None:
        raise conflict("이 면접의 면접관이 아닙니다.")
    competency_set = session_competency_set(db, found)
    names = [c["name"] for c in competency_set.competencies] if competency_set else []
    given = {row.competency: row for row in body.scores}
    for name in names:
        if name not in given:
            raise invalid("scores", f"'{name}' 점수가 없습니다.")
    for row in body.scores:
        if row.competency not in names:
            raise invalid("scores", f"'{row.competency}'은(는) 이 면접의 역량이 아닙니다.")
        if not 1 <= row.score <= 5:
            raise invalid("scores", "점수는 1~5 정수여야 합니다.")

    candidate = found.application.candidate
    db.execute(
        delete(Score).where(
            Score.session_id == found.id,
            Score.evaluator_type == EvaluatorType.interviewer,
            Score.evaluator_id == interviewer_id,
        )
    )
    for name in names:
        comment = given[name].comment.strip()
        db.add(
            Score(
                session_id=found.id,
                qa_item_id=None,
                competency=name,
                score=given[name].score,
                evidence=runtime.deid.deidentify(db, comment, candidate) if comment else None,
                evaluator_type=EvaluatorType.interviewer,
                evaluator_id=interviewer_id,
            )
        )
    link.submitted_at = utcnow()
    audit(
        db,
        me,
        "score.interviewer_submitted",
        "interview_session",
        found.id,
        interviewer_id=interviewer_id,
    )
    db.commit()
    db.expire_all()
    return _view(db, get_session(db, session_id), runtime, me)


# --- N차 결정 and points to check ---------------------------------------------------------------


@router.post("/sessions/{session_id}/decision", response_model=s.Evaluation)
def decide(
    session_id: str, body: s.DecisionRequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.Evaluation:
    """A person's decision on the session's round: 합격 (the next round opens; in the last round,
    a final candidate), 보류 (stays on the pending list) or 불합격. Only once every interviewer
    submitted; a change is a new revision with the old ones kept, and both are audited."""
    found = get_session(db, session_id)
    if not me.is_admin and all(link.interviewer_id != me.id for link in found.interviewers):
        raise HTTPException(403, "이 면접의 면접관이나 관리자만 결정할 수 있습니다.")
    refusal = views.decision_refusal(found)
    if refusal is not None:
        raise conflict(refusal)
    reason = body.reason.strip()
    if not reason:
        raise invalid("reason", "결정 사유를 입력하세요.")
    if len(reason) > MAX_REASON:
        raise invalid("reason", f"결정 사유는 {MAX_REASON}자까지 쓸 수 있습니다.")
    application = found.application
    current = current_decision(application, found.round)
    row = RoundDecision(
        application=application,
        round=found.round,
        session=found,
        revision=(current.revision if current else 0) + 1,
        decision=body.decision,
        reason=runtime.deid.deidentify(db, reason, application.candidate),
        decided_by=me.id,
    )
    db.add(row)
    db.flush()
    details = {
        "round_id": found.round_id,
        "round": found.round.position,
        "session_id": found.id,
        "revision": row.revision,
        "final": body.decision.value == "passed" and is_last_round(found.round),
    }
    if current is None:
        audit(db, me, "round.decided", "application", application.id, decision=body.decision.value, **details)
    else:
        audit(
            db,
            me,
            "round.decision_changed",
            "application",
            application.id,
            **{"from": current.decision.value, "to": body.decision.value},
            **details,
        )
    db.commit()
    db.expire_all()
    return _view(db, get_session(db, session_id), runtime, me)


@router.get("/applications/{application_id}/decisions", response_model=list[s.RoundDecision])
def decisions(application_id: str, db: Db) -> list[s.RoundDecision]:
    """Every revision of every round, newest first."""
    application = db.get(Application, application_id)
    if application is None or application.deleted_at is not None:
        raise not_found("지원서")
    return views.application_detail(application).decisions


@router.post(
    "/sessions/{session_id}/check-points", response_model=s.CheckPoint, status_code=201
)
def create_check_point(
    session_id: str, body: s.CreateCheckPointRequest, db: Db, me: Me, runtime: RuntimeDep
) -> s.CheckPoint:
    """확인이 필요한 점 for later rounds, written by an interviewer (de-identified)."""
    found = get_session(db, session_id)
    if found.status is not SessionStatus.completed:
        raise conflict("종료된 면접에만 확인할 점을 남길 수 있습니다.")
    text = body.text.strip()
    if not text:
        raise invalid("text", "확인할 점을 입력하세요.")
    pinned = session_competency_set(db, found)
    names = [c["name"] for c in pinned.competencies] if pinned else []
    if body.competency is not None and body.competency not in names:
        raise invalid("competency", f"'{body.competency}'은(는) 이 면접의 역량이 아닙니다.")
    row = CheckPoint(
        session_id=found.id,
        source=CheckPointSource.interviewer,
        competency=body.competency,
        text=runtime.deid.deidentify(db, text, found.application.candidate),
        author_id=me.id,
    )
    db.add(row)
    db.flush()
    audit(db, me, "check_point.created", "interview_session", found.id, check_point_id=row.id)
    db.commit()
    db.refresh(row)
    return views.check_point_view(row)


@router.delete("/check-points/{check_point_id}", status_code=204)
def delete_check_point(check_point_id: str, db: Db, me: Me) -> Response:
    row = db.get(CheckPoint, check_point_id)
    if row is None:
        raise not_found("확인할 점")
    if row.source is not CheckPointSource.interviewer or row.author_id != me.id:
        raise HTTPException(403, "직접 남긴 확인할 점만 지울 수 있습니다.")
    audit(db, me, "check_point.deleted", "interview_session", row.session_id, check_point_id=row.id)
    db.delete(row)
    db.commit()
    return Response(status_code=204)
