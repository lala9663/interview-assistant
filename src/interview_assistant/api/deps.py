"""Request dependencies: the runtime, a database session, the signed-in interviewer, audit."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.models import ActorType, AuditLog, Interviewer
from interview_assistant.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def get_db(request: Request) -> Iterator[Session]:
    with get_runtime(request).session_factory() as db:
        yield db


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
Db = Annotated[Session, Depends(get_db)]


def current_interviewer(db: Db, runtime: RuntimeDep) -> Interviewer:
    """Login (IAP + SSO) is Phase 1. Until then IA_DEV_INTERVIEWER (employee number) is the
    signed-in interviewer, or else the first interviewer created."""
    query = select(Interviewer)
    if runtime.settings.dev_interviewer:
        query = query.where(Interviewer.employee_no == runtime.settings.dev_interviewer)
    me = db.scalars(query.order_by(Interviewer.created_at, Interviewer.employee_no)).first()
    if me is None:
        raise HTTPException(
            503, "면접관 정보가 없습니다. 시드 데이터를 넣거나 IA_DEV_INTERVIEWER를 확인하세요."
        )
    return me


Me = Annotated[Interviewer, Depends(current_interviewer)]


def audit(
    db: Session,
    me: Interviewer | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    **details: Any,
) -> None:
    """A person's write. AI calls are logged by the AI gateway."""
    db.add(
        AuditLog(
            actor_type=ActorType.user if me else ActorType.system,
            actor_id=me.id if me else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or None,
        )
    )
