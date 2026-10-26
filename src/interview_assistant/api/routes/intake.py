"""채용 사이트 연동 (수신): the recruiting site's endpoints and 관리자 > 연동 현황.

The site's endpoints are not behind the interviewer login. Every request is signed with the
shared key (intake/signature.py) and refused before its content is looked at when the signature
or its timestamp is off. The event is then accepted or refused at once (202 / 4xx) and applied
in the background (intake/worker.py); the site can look up how it went. The full contract for
the recruiting-site team is docs/site-intake-spec.md.

연동 현황 (admins): every event received with its status and failure reason, counts per posting,
processing times, and 다시 처리 for failed events. Pseudonyms only: no name and no applicant
number is stored, so none can be shown.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.datastructures import UploadFile

from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Admin, Db, RuntimeDep
from interview_assistant.api.errors import conflict, not_found
from interview_assistant.intake.events import accept_site_event, retry_event, status_body
from interview_assistant.intake.signature import SignatureError, verify
from interview_assistant.intake.site import MAX_ATTACHMENTS
from interview_assistant.models import (
    ActorType,
    ApplicationChannel,
    AuditLog,
    IntakeEvent,
    IntakeStatus,
)
from interview_assistant.runtime import Runtime

router = APIRouter(tags=["intake"])

MAX_BODY_BYTES = MAX_ATTACHMENTS * 10 * 1024 * 1024 + 2 * 1024 * 1024
EVENTS_PATH = "/api/intake/site/events"


def _site_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": message}, status_code=status)


def _secrets(runtime: Runtime) -> list[str]:
    settings = runtime.settings
    keys = [settings.site_secret, settings.site_secret_previous]
    return [k.get_secret_value() for k in keys if k is not None and k.get_secret_value()]


def _check_signature(request: Request, runtime: Runtime, db: Db, body: bytes) -> JSONResponse | None:
    secrets = _secrets(runtime)
    if not secrets:
        return _site_error(503, "not_configured", "채용 사이트 연동 키(IA_SITE_SECRET)가 설정되지 않았습니다.")
    try:
        verify(
            secrets,
            request.headers,
            request.method,
            request.url.path,
            body,
            skew=runtime.settings.site_clock_skew,
        )
    except SignatureError as exc:
        db.add(
            AuditLog(
                actor_type=ActorType.system,
                action="intake.signature_rejected",
                details={"code": exc.code, "path": request.url.path},
            )
        )
        db.commit()
        return _site_error(401, exc.code, exc.message)
    return None


@router.post(
    "/intake/site/events",
    status_code=202,
    response_model=s.SiteEventStatus,
    responses={401: {}, 409: {}, 413: {}, 415: {}, 422: {}, 503: {}},
)
async def receive_site_event(request: Request, db: Db, runtime: RuntimeDep) -> JSONResponse:
    """지원서 이벤트 수신 (제출·수정·철회). multipart/form-data: `event` (JSON) and one part per
    attachment, or application/json for an event without attachments (a withdrawal)."""
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return _site_error(413, "too_large", "요청이 너무 큽니다 (첨부 5개, 개당 10MB 이하).")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _site_error(413, "too_large", "요청이 너무 큽니다 (첨부 5개, 개당 10MB 이하).")
    refused = _check_signature(request, runtime, db, body)
    if refused is not None:
        return refused
    if runtime.deid.cipher is None:
        return _site_error(503, "not_configured", "암호화 키가 없어 지원서를 받을 수 없습니다.")

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    files: dict[str, bytes] = {}
    try:
        if content_type == "application/json":
            raw = json.loads(body)
        elif content_type == "multipart/form-data":
            form = await request.form(max_files=MAX_ATTACHMENTS + 1, max_fields=MAX_ATTACHMENTS + 2, max_part_size=2 * 1024 * 1024)
            raw = None
            for name, value in form.multi_items():
                data = await value.read() if isinstance(value, UploadFile) else value.encode()
                if name == "event":
                    raw = json.loads(data)
                else:
                    files[name] = data
        else:
            return _site_error(415, "malformed", "multipart/form-data 또는 application/json으로 보내 주세요.")
    except (ValueError, UnicodeDecodeError):
        return _site_error(400, "malformed", "event JSON을 읽을 수 없습니다.")
    except Exception:  # the multipart parser refuses too many parts or a part that is too big
        return _site_error(400, "malformed", "multipart 본문을 읽을 수 없습니다.")

    accepted = accept_site_event(db, runtime.deid, runtime.uploads_dir, raw, files)
    if accepted.enqueue:
        runtime.intake.enqueue(accepted.enqueue)
    if accepted.cancel:
        runtime.intake.cancel(accepted.cancel)
    return JSONResponse(accepted.body, status_code=accepted.status_code)


@router.get(
    "/intake/site/events/{event_id}",
    response_model=s.SiteEventStatus,
    responses={401: {}, 404: {}, 503: {}},
)
async def site_event_status(event_id: str, request: Request, db: Db, runtime: RuntimeDep) -> JSONResponse:
    """처리 상태 조회: signed like the events, with an empty body."""
    refused = _check_signature(request, runtime, db, b"")
    if refused is not None:
        return refused
    row = db.scalar(
        select(IntakeEvent).where(
            IntakeEvent.channel == ApplicationChannel.site, IntakeEvent.event_id == event_id
        )
    )
    if row is None:
        return _site_error(404, "unknown_event", "받은 적 없는 event_id입니다.")
    return JSONResponse(status_body(row))


# --- 관리자 > 연동 현황 -----------------------------------------------------------------------


@router.get("/admin/intake/summary", response_model=s.IntakeSummary)
def intake_summary(db: Db, runtime: RuntimeDep, _: Admin) -> s.IntakeSummary:
    return views.intake_summary(
        db, configured=bool(_secrets(runtime)), workers=runtime.settings.intake_workers
    )


@router.get("/admin/intake/events", response_model=list[s.IntakeEvent])
def intake_events(
    db: Db,
    _: Admin,
    status: s.IntakeStatusValue | None = None,
    posting_no: str | None = None,
    failure_code: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list[s.IntakeEvent]:
    """Newest first. `posting_no=-` lists events whose posting number is missing."""
    query = select(IntakeEvent).where(IntakeEvent.channel == ApplicationChannel.site)
    if status is not None:
        query = query.where(IntakeEvent.status == IntakeStatus(status))
    if posting_no == "-":
        query = query.where(IntakeEvent.posting_no.is_(None))
    elif posting_no:
        query = query.where(IntakeEvent.posting_no == posting_no)
    if failure_code:
        query = query.where(IntakeEvent.failure_code == failure_code)
    rows = db.scalars(query.order_by(IntakeEvent.received_at.desc()).limit(limit)).all()
    linked = views.linked_postings(db)
    return [views.intake_event(r, linked) for r in rows]


@router.post("/admin/intake/events/{intake_id}/retry", response_model=s.IntakeEvent)
async def retry_intake_event(intake_id: str, db: Db, runtime: RuntimeDep, admin: Admin) -> s.IntakeEvent:
    row = db.get(IntakeEvent, intake_id)
    if row is None:
        raise not_found("연동 이벤트")
    if not retry_event(db, row, admin):
        raise conflict(
            "다시 처리할 수 없는 이벤트입니다. 실패했고 원문이 남아 있는 이벤트만 다시 처리합니다. "
            "거절된 이벤트는 채용 사이트에서 새 event_id로 보내야 합니다."
        )
    db.commit()
    runtime.intake.enqueue(row.id)
    return views.intake_event(row)


@router.post("/admin/intake/retry", response_model=s.IntakeRetried)
async def retry_intake_failures(
    body: s.RetryIntakeRequest, db: Db, runtime: RuntimeDep, admin: Admin
) -> s.IntakeRetried:
    """다시 처리, in bulk: every failed event that kept its payload (optionally one reason or
    one posting number), in the order they arrived."""
    query = select(IntakeEvent).where(
        IntakeEvent.channel == ApplicationChannel.site,
        IntakeEvent.status == IntakeStatus.failed,
        IntakeEvent.encrypted_payload.is_not(None),
    )
    if body.failure_code:
        query = query.where(IntakeEvent.failure_code == body.failure_code)
    if body.posting_no:
        query = query.where(IntakeEvent.posting_no == body.posting_no)
    rows = [r for r in db.scalars(query.order_by(IntakeEvent.received_at)).all() if retry_event(db, r, admin)]
    db.commit()
    for row in rows:
        runtime.intake.enqueue(row.id)
    return s.IntakeRetried(requeued=len(rows))
