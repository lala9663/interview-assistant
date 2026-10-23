"""평가 (FR-07, 08): AI and interviewer scores side by side, never combined.

Interviewer scores are one per competency for the whole session (Score.qa_item_id is null). A
resubmission replaces the interviewer's previous scores; comments are de-identified like any
other free text.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import delete

from interview_assistant.ai.gateway import model_name
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid
from interview_assistant.api.routes.sessions import get_session
from interview_assistant.interviews import session_competency_set
from interview_assistant.models import EvaluatorType, Score, SessionStatus
from interview_assistant.models.base import utcnow

router = APIRouter(tags=["evaluation"])


@router.get("/sessions/{session_id}/evaluation", response_model=s.Evaluation)
def evaluation(session_id: str, db: Db, runtime: RuntimeDep) -> s.Evaluation:
    found = get_session(db, session_id)
    return views.evaluation(db, found, model_name(runtime.ai.llm("primary")))


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
    return views.evaluation(db, get_session(db, session_id), model_name(runtime.ai.llm("primary")))
