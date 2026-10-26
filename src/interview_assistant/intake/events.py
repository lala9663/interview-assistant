"""Site events: accept at the door (`accept_site_event`), apply in the background (`apply_event`).

Accepting is quick and synchronous: idempotency by event_id, refused items, schema, then the
event is stored (payload encrypted, attachments in the raw zone) and queued; the API answers 202.
Applying happens in the worker (worker.py), one application at a time per application number:

- revision order: an event applies only if its revision is above every revision already applied
  for that application, so events may arrive in any order. An update arriving before its
  submission creates the application (events carry the whole application); the late submission
  is then skipped as stale. A withdrawal arriving first is recorded, and anything older that
  comes later is skipped.
- after a withdrawal nothing newer applies to the same application number (`application_withdrawn`):
  applying again is a new application number on the site.
- a withdrawal also skips the queued events of that application and cancels one being applied.

Applied and skipped events drop their payload and attachments; failed ones keep them so they can
be processed again (`retry_event`) once the cause is fixed, e.g. the posting number is linked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.gateway import AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.deid.service import DeidService
from interview_assistant.intake.service import (
    LOCKS,
    IntakeRefused,
    process_application,
    withdraw_application,
)
from interview_assistant.intake.site import (
    EVENT_TYPES,
    SiteEvent,
    application_input,
    drop_unknown,
    fingerprint,
    forbidden_items,
    forbidden_message,
    validation_failure,
)
from interview_assistant.models import (
    ActorType,
    Application,
    ApplicationChannel,
    AuditLog,
    IntakeEvent,
    IntakeEventType,
    IntakeStatus,
    Interviewer,
)
from interview_assistant.models.base import iso_z, utcnow
from interview_assistant.providers.base import ProviderUnavailable

log = logging.getLogger(__name__)

# Failure codes whose cause can go away on our side (link the posting, reopen it, OCR arrives,
# the model recovers): worth "다시 처리". Others need the site to send something else.
RETRIABLE = frozenset({"unknown_posting", "posting_closed", "ocr_required", "ai_failed", "internal_error"})


@dataclass
class Accepted:
    status_code: int
    body: dict[str, Any]
    enqueue: str | None = None  # intake_events.id to queue
    cancel: list[str] = field(default_factory=list)  # ids being applied that a withdrawal stops


def staging_dir(uploads_dir: Path, row_id: str) -> Path:
    return uploads_dir / "intake" / row_id


def status_body(event: IntakeEvent, *, duplicate: bool = False) -> dict[str, Any]:
    """What the site sees about one event: no pseudonym, no internal ids."""
    body: dict[str, Any] = {
        "event_id": event.event_id,
        "status": event.status.value,
        "event_type": f"application.{event.event_type.value}" if event.event_type else None,
        "revision": event.revision,
        "received_at": iso_z(event.received_at),
        "finished_at": iso_z(event.finished_at) if event.finished_at else None,
        "dropped_fields": event.dropped_fields or [],
        "duplicate": duplicate,
    }
    if event.failure_code:
        body |= {
            "code": event.failure_code,
            "detail": event.failure_message,
            "fields": event.failure_fields or [],
        }
    return body


def _audit(db: Session, action: str, event: IntakeEvent | None, actor: Interviewer | None = None, **details: Any) -> None:
    db.add(
        AuditLog(
            actor_type=ActorType.user if actor else ActorType.system,
            actor_id=actor.id if actor else None,
            action=action,
            target_type="intake_event" if event is not None else None,
            target_id=event.id if event is not None else None,
            details=details or None,
        )
    )


def _peek(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) and 0 < len(value) <= 64 else None


def accept_site_event(
    db: Session, deid: DeidService, uploads_dir: Path, raw: Any, files: dict[str, bytes]
) -> Accepted:
    """The door: decide 202 / 4xx for one authenticated request and store what may be stored."""
    if not isinstance(raw, dict) or not isinstance(raw.get("event_id"), str) or not raw["event_id"]:
        return Accepted(400, {"code": "malformed", "detail": "event_id가 있는 이벤트 JSON이 필요합니다."})
    event_id = raw["event_id"][:64]
    digest = fingerprint(raw, files)
    existing = db.scalar(
        select(IntakeEvent).where(
            IntakeEvent.channel == ApplicationChannel.site, IntakeEvent.event_id == event_id
        )
    )
    if existing is not None:
        if existing.fingerprint != digest:
            return Accepted(
                409,
                {
                    "code": "event_id_conflict",
                    "detail": "같은 event_id로 다른 내용이 이미 왔습니다. 내용을 바꿨다면 새 event_id로 보내 주세요.",
                    "event_id": event_id,
                },
            )
        code = 422 if existing.status is IntakeStatus.rejected else 202
        return Accepted(code, status_body(existing, duplicate=True))

    kind = EVENT_TYPES.get(raw.get("event_type")) if isinstance(raw.get("event_type"), str) else None
    revision = raw.get("revision") if isinstance(raw.get("revision"), int) else None
    row = IntakeEvent(
        channel=ApplicationChannel.site,
        event_id=event_id,
        event_type=IntakeEventType(kind) if kind else None,
        revision=revision,
        posting_no=_peek(raw, "posting_no"),
        application_no=_peek(raw, "application_no"),
        fingerprint=digest,
        attachment_count=0,
    )

    def reject(code: str, message: str, fields: list[str]) -> Accepted:
        row.status = IntakeStatus.rejected
        row.failure_code, row.failure_message, row.failure_fields = code, message, fields
        row.finished_at = utcnow()
        db.add(row)
        db.flush()
        _audit(db, "intake.rejected", row, code=code, fields=fields)
        db.commit()
        return Accepted(422, status_body(row))

    found = forbidden_items(raw)
    if found:
        return reject("forbidden_field", forbidden_message(found), [path for path, _ in found])
    try:
        event = SiteEvent.model_validate(raw)
    except ValidationError as exc:
        return reject(*validation_failure(exc))

    dropped = drop_unknown(event)
    if event.kind == "withdrawn":
        dropped += [n for n in ("applicant", "consent", "form", "attachments") if raw.get(n)]
        payload: dict[str, Any] = event.envelope()
        attachments = {}
    else:
        referenced = {a.part for a in event.attachments}
        missing = [f"attachments[{i}].part" for i, a in enumerate(event.attachments) if a.part not in files]
        if missing:
            return reject("missing_field", "첨부 파일 부분(part)이 요청에 없습니다.", missing)
        too_big = [f"attachments[{i}]" for i, a in enumerate(event.attachments) if len(files[a.part]) > 10 * 1024 * 1024]
        if too_big:
            return reject("invalid_field", "첨부 파일이 너무 큽니다 (최대 10MB).", too_big)
        dropped += [f"parts.{name}" for name in files if name not in referenced]
        payload = event.model_dump(mode="json")
        attachments = {a.part: files[a.part] for a in event.attachments}

    row.occurred_at = event.occurred_at
    row.encrypted_payload = deid.seal_payload(json.dumps(payload, ensure_ascii=False))
    row.dropped_fields = dropped or None
    row.attachment_count = len(attachments)
    row.status = IntakeStatus.queued
    db.add(row)
    db.flush()
    folder = staging_dir(uploads_dir, row.id)
    if attachments:
        folder.mkdir(parents=True, exist_ok=True)
        for part, data in attachments.items():
            (folder / part).write_bytes(data)

    cancel: list[str] = []
    if event.kind == "withdrawn":
        # 진행 중 작업 취소: older events of this application that wait are skipped now; one being
        # applied is cancelled by the worker and skipped when it stops.
        older = select(IntakeEvent).where(
            IntakeEvent.channel == ApplicationChannel.site,
            IntakeEvent.application_no == event.application_no,
            IntakeEvent.revision < event.revision,
            IntakeEvent.status.in_((IntakeStatus.queued, IntakeStatus.processing)),
            IntakeEvent.id != row.id,
        )
        for other in db.scalars(older).all():
            if other.status is IntakeStatus.processing:
                cancel.append(other.id)
            else:
                _finish(other, IntakeStatus.skipped, "withdrawn", "지원자가 철회해 처리하지 않았습니다.")
                _drop_payload(other, uploads_dir)
    _audit(db, "intake.received", row, event_type=event.kind, revision=event.revision, dropped=len(dropped))
    try:
        db.commit()
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    body = status_body(row)
    body["status_url"] = f"/api/intake/site/events/{row.event_id}"
    return Accepted(202, body, enqueue=row.id, cancel=cancel)


# --- applying -------------------------------------------------------------------------------


def _finish(
    event: IntakeEvent,
    status: IntakeStatus,
    code: str | None = None,
    message: str | None = None,
    fields: list[str] | None = None,
) -> None:
    event.status = status
    event.failure_code, event.failure_message = code, message
    event.failure_fields = fields or None
    event.finished_at = utcnow()


def _drop_payload(event: IntakeEvent, uploads_dir: Path) -> None:
    event.encrypted_payload = None
    shutil.rmtree(staging_dir(uploads_dir, event.id), ignore_errors=True)


@dataclass
class IntakeContext:
    """What applying needs from the running app. `ai` is read per event: the active models."""

    session_factory: sessionmaker[Session]
    deid: DeidService
    uploads_dir: Path
    ai: Callable[[], AiGateway]


async def apply_event(ctx: IntakeContext, row_id: str, *, withdrawn: Callable[[str], bool]) -> None:
    """Apply one queued event and leave it done, skipped or failed. Cancelled by a withdrawal
    (`withdrawn(row_id)` is true) it ends skipped; cancelled by a shutdown it stays processing
    and is queued again at the next start."""
    with ctx.session_factory() as db:
        event = db.get(IntakeEvent, row_id)
        if event is None or event.status is not IntakeStatus.queued:
            return
        event.status = IntakeStatus.processing
        event.started_at = utcnow()
        event.finished_at = None
        event.attempts += 1
        db.commit()
        try:
            async with LOCKS.hold(f"application:{event.application_no}"):
                await _apply_locked(db, ctx, event)
        except asyncio.CancelledError:
            db.rollback()
            if not withdrawn(row_id):
                raise
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            event = db.get(IntakeEvent, row_id)
            _finish(event, IntakeStatus.skipped, "withdrawn", "지원자가 철회해 처리를 멈췄습니다.")
            _drop_payload(event, ctx.uploads_dir)
            _audit(db, "intake.skipped", event, code="withdrawn")
            db.commit()
            return
        except Exception as exc:  # anything unexpected: failed, kept for another try
            log.exception("intake event %s failed", row_id)
            db.rollback()
            event = db.get(IntakeEvent, row_id)
            _finish(event, IntakeStatus.failed, "internal_error", f"처리 중 오류가 났습니다 ({type(exc).__name__}).")
        _audit(
            db,
            f"intake.{event.status.value}",
            event,
            code=event.failure_code,
            revision=event.revision,
        )
        db.commit()


async def _apply_locked(db: Session, ctx: IntakeContext, event: IntakeEvent) -> None:
    applied = (
        IntakeEvent.channel == ApplicationChannel.site,
        IntakeEvent.application_no == event.application_no,
        IntakeEvent.status == IntakeStatus.done,
    )
    newest = db.scalar(select(func.max(IntakeEvent.revision)).where(*applied))
    withdrawal = db.scalar(
        select(IntakeEvent).where(*applied, IntakeEvent.event_type == IntakeEventType.withdrawn).limit(1)
    )
    if newest is not None and event.revision is not None and event.revision <= newest:
        if withdrawal is not None and withdrawal.revision >= event.revision:
            _finish(event, IntakeStatus.skipped, "withdrawn", "이미 철회된 지원서라 반영하지 않았습니다.")
        else:
            _finish(
                event,
                IntakeStatus.skipped,
                "stale_revision",
                f"더 새 버전(revision {newest})이 이미 반영되어 이 버전은 반영하지 않았습니다.",
            )
        _drop_payload(event, ctx.uploads_dir)
        return
    if withdrawal is not None:
        _finish(
            event,
            IntakeStatus.failed,
            "application_withdrawn",
            "철회된 지원 번호입니다. 다시 지원한 것이면 새 지원 번호로 보내 주세요.",
            ["application_no"],
        )
        _drop_payload(event, ctx.uploads_dir)
        return

    if event.event_type is IntakeEventType.withdrawn:
        application = db.scalar(
            select(Application).where(Application.site_application_no == event.application_no)
        )
        if application is not None:
            event.result = withdraw_application(db, application)
            event.application_id, event.candidate_id = application.id, application.candidate_id
            event.posting_id = application.posting_id
        else:
            event.result = {"application_found": False}
        _finish(event, IntakeStatus.done)
        _drop_payload(event, ctx.uploads_dir)
        return

    payload = json.loads(ctx.deid.open_payload(event.encrypted_payload or "{}"))
    site_event = SiteEvent.model_validate(payload)
    folder = staging_dir(ctx.uploads_dir, event.id)
    files = {a.part: (folder / a.part).read_bytes() for a in site_event.attachments}
    try:
        outcome = await process_application(
            db,
            application_input(site_event, files),
            ai=ctx.ai(),
            deid=ctx.deid,
            uploads_dir=ctx.uploads_dir,
        )
    except IntakeRefused as exc:
        _finish(event, IntakeStatus.failed, exc.code, exc.message, [exc.field] if exc.field else None)
        return
    except (AiOutputInvalid, IdentifierInPrompt, ProviderUnavailable) as exc:
        message = {
            AiOutputInvalid: "AI 응답을 쓸 수 없어 선별하지 못했습니다.",
            IdentifierInPrompt: "식별 정보가 남아 있어 AI 호출을 막았습니다. 관리자에게 알려 주세요.",
        }.get(type(exc), "AI 모델을 쓸 수 없어 선별하지 못했습니다.")
        _finish(event, IntakeStatus.failed, "ai_failed", message)
        return
    event.application_id = outcome.application.id
    event.candidate_id = outcome.candidate.id
    event.posting_id = outcome.application.posting_id
    event.result = outcome.summary() | {"consent_version": site_event.consent.terms_version if site_event.consent else None}
    _finish(event, IntakeStatus.done)
    _drop_payload(event, ctx.uploads_dir)


# --- maintenance ----------------------------------------------------------------------------


def retry_event(db: Session, event: IntakeEvent, actor: Interviewer | None) -> bool:
    """Queue a failed event again (its payload was kept). False if there is nothing to retry."""
    if event.status is not IntakeStatus.failed or not event.encrypted_payload:
        return False
    previous = event.failure_code
    event.status = IntakeStatus.queued
    event.failure_code = event.failure_message = None
    event.failure_fields = None
    event.finished_at = None
    _audit(db, "intake.retried", event, actor, previous=previous)
    return True


def resume_queue(db: Session) -> list[str]:
    """At start: events interrupted mid-way are queued again; returns every queued id, oldest
    first."""
    db.execute(
        update(IntakeEvent)
        .where(IntakeEvent.status == IntakeStatus.processing)
        .values(status=IntakeStatus.queued)
    )
    db.commit()
    return list(
        db.scalars(
            select(IntakeEvent.id)
            .where(IntakeEvent.status == IntakeStatus.queued)
            .order_by(IntakeEvent.received_at)
        ).all()
    )
