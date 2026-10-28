"""Request dependencies: the runtime, a database session, the signed-in interviewer, audit. They
take an `HTTPConnection`, so WebSocket routes (the microphone audio) resolve them the same way."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from interview_assistant.models import ActorType, AuditLog, Interviewer
from interview_assistant.runtime import Runtime


def get_runtime(request: HTTPConnection) -> Runtime:
    return request.app.state.runtime


def get_db(request: HTTPConnection) -> Iterator[Session]:
    with get_runtime(request).session_factory() as db:
        yield db


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
Db = Annotated[Session, Depends(get_db)]


def current_interviewer(request: HTTPConnection, db: Db, runtime: RuntimeDep) -> Interviewer:
    """Login (IAP + SSO) is Phase 1. Until then IA_DEV_INTERVIEWER (employee number) is the
    signed-in interviewer, or else the first interviewer created. An agent call is the
    interviewer its token names (api/agent_access.py checked it before the route ran)."""
    call = getattr(request.state, "agent_call", None)
    if call is not None and call.interviewer_id is not None:
        found = db.get(Interviewer, call.interviewer_id)
        if found is not None:
            return found
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


def current_admin(me: Me) -> Interviewer:
    """Admin-only routes (model settings). The flag is `Interviewer.is_admin`; once SSO lands it is
    set from a group claim and these routes stay as they are."""
    if not me.is_admin:
        raise HTTPException(403, "관리자만 쓸 수 있습니다.")
    return me


Admin = Annotated[Interviewer, Depends(current_admin)]


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
