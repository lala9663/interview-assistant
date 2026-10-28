"""에이전트 제안 기록: what an agent proposed (book an interview, pass or reject a screening,
decide a round), kept in the audit log. Nothing else changes; a person confirms the proposal on
the web screen, where the usual rules and audit apply. Agent calls only (api/agent_access.py)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from interview_assistant.api import schemas as s
from interview_assistant.api.agent_access import agent_call, agent_may_call
from interview_assistant.api.deps import Db, Me
from interview_assistant.api.errors import invalid, not_found
from interview_assistant.models import (
    ActorType,
    Application,
    AuditLog,
    InterviewRound,
    InterviewSession,
    Interviewer,
)

router = APIRouter(tags=["agent"])


@router.post("/agent/proposals", response_model=s.AgentProposalRecorded, status_code=201)
@agent_may_call
def record_proposal(
    body: s.AgentProposalRequest, request: Request, db: Db, me: Me
) -> s.AgentProposalRecorded:
    call = agent_call(request)
    if call is None:
        raise HTTPException(403, "에이전트 호출에서만 쓰는 기록입니다.")
    application = db.get(Application, body.application_id)
    if application is None or application.deleted_at is not None:
        raise not_found("지원서")
    if body.round_id is not None:
        found = db.get(InterviewRound, body.round_id)
        if found is None or found.posting_id != application.posting_id:
            raise not_found("차수")
    if body.session_id is not None:
        session = db.get(InterviewSession, body.session_id)
        if session is None or session.application_id != application.id:
            raise not_found("면접")
    for interviewer_id in body.interviewer_ids:
        if db.get(Interviewer, interviewer_id) is None:
            raise not_found("면접관")
    if body.kind != "interview_booking" and body.decision is None:
        raise invalid("decision", "제안할 결정을 고르세요.")
    details = {
        "kind": body.kind,
        "agent": call.agent,
        "tool": call.tool,
        "round_id": body.round_id,
        "session_id": body.session_id,
        "decision": body.decision,
        "start_at": body.start_at.isoformat() if body.start_at else None,
        "interviewer_ids": body.interviewer_ids or None,
        "mode": body.mode.value if body.mode else None,
    }
    row = AuditLog(
        actor_type=ActorType.user,
        actor_id=me.id,
        action="agent.proposed",
        target_type="application",
        target_id=application.id,
        details={k: v for k, v in details.items() if v is not None},
    )
    db.add(row)
    db.commit()
    return s.AgentProposalRecorded(
        id=row.id, kind=body.kind, application_id=application.id, recorded_at=row.occurred_at
    )
