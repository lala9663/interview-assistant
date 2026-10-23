"""서류 선별 (FR-01, 03): applications, screening decisions, the candidate index, uploads.

Upload: the original file goes to the raw zone on disk (uploads/, never served), its text is
extracted and de-identified, hidden text is kept out of the prompt, and the `screening` model
structures a profile and assesses it. The identity typed into the form is sealed into
Candidate.encrypted_identity; the API only ever shows the pseudonym.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.ai.prompts import SCREENING_PROMPT
from interview_assistant.ai.screening import screen_document
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import ai_failed, conflict, invalid, not_found
from interview_assistant.deid.documents import OcrRequired, deidentify_document
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.documents import (
    BlockKind,
    ExtractionError,
    extract_document,
    render_blocks,
)
from interview_assistant.interviews import approved_set
from interview_assistant.models import (
    ActorType,
    Application,
    AuditLog,
    Candidate,
    JobPosting,
    PostingStatus,
    Screening,
    ScreeningStatus,
)
from interview_assistant.models.base import new_id

router = APIRouter(tags=["screening"])
log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_EXTENSIONS = {"pdf": ".pdf", "docx": ".docx", "pptx": ".pptx", "html": ".html"}


def _application(db: Db, application_id: str) -> Application:
    found = db.get(Application, application_id)
    if found is None or found.deleted_at is not None:
        raise not_found("지원서")
    return found


def _live_applications(db: Db) -> list[Application]:
    return list(
        db.scalars(
            select(Application)
            .where(Application.deleted_at.is_(None))
            .order_by(Application.created_at)
        ).all()
    )


@router.get("/postings/{posting_id}/applications", response_model=list[s.ApplicationRow])
def applications(posting_id: str, db: Db) -> list[s.ApplicationRow]:
    if db.get(JobPosting, posting_id) is None:
        raise not_found("공고")
    rows = db.scalars(
        select(Application)
        .where(Application.posting_id == posting_id, Application.deleted_at.is_(None))
        .order_by(Application.created_at)
    ).all()
    return [views.application_row(a) for a in rows]


@router.get("/applications/schedulable", response_model=list[s.SchedulableApplication])
def schedulable(db: Db) -> list[s.SchedulableApplication]:
    return views.schedulable(_live_applications(db))


@router.get("/applications/{application_id}", response_model=s.ApplicationDetail)
def application(application_id: str, db: Db) -> s.ApplicationDetail:
    return views.application_detail(_application(db, application_id))


@router.patch("/screenings/{screening_id}", response_model=s.Screening)
def update_screening(screening_id: str, body: s.ScreeningUpdate, db: Db, me: Me) -> s.Screening:
    found = db.get(Screening, screening_id)
    if found is None:
        raise not_found("선별 결과")
    before = found.status
    found.status = body.status
    if before is not body.status:
        audit(
            db,
            me,
            "screening.status_changed",
            "screening",
            found.id,
            **{"from": before.value, "to": body.status.value},
        )
    db.commit()
    return s.Screening.model_validate(found)


@router.get("/candidates", response_model=list[s.CandidateIndexItem])
def candidates(db: Db) -> list[s.CandidateIndexItem]:
    return views.candidate_index(_live_applications(db))


def _lines(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.splitlines() if v.strip())


def next_pseudonym(db: Db) -> str:
    taken = db.scalars(select(Candidate.pseudonym).where(Candidate.pseudonym.like("CAND-%"))).all()
    numbers = [int(m.group(1)) for p in taken if (m := re.fullmatch(r"CAND-(\d+)", p))]
    return f"CAND-{max(numbers, default=0) + 1:04d}"


@router.post("/postings/{posting_id}/applications", response_model=s.UploadResult, status_code=201)
async def upload_application(
    posting_id: str,
    db: Db,
    me: Me,
    runtime: RuntimeDep,
    file: UploadFile = File(...),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    birthdate: str = Form(""),
    aliases: str = Form(""),
    addresses: str = Form(""),
    schools: str = Form(""),
    companies: str = Form(""),
) -> s.UploadResult:
    """Form fields are what the application form already says about the candidate. Only `name`
    is required; the rest (one value per line) helps de-identification catch more."""
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        raise not_found("공고")
    if posting.status is PostingStatus.closed:
        raise conflict("마감된 공고에는 지원서를 올릴 수 없습니다.")
    if not name.strip():
        raise invalid("name", "지원자 이름을 입력하세요. 비식별화에만 쓰입니다.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise invalid("file", "파일이 너무 큽니다 (최대 10MB).")
    if not data:
        raise invalid("file", "빈 파일입니다.")

    try:
        document = await run_in_threadpool(extract_document, data, file.filename or "upload")
    except ExtractionError as exc:
        raise invalid("file", str(exc)) from exc
    if document.needs_ocr:
        pages = ", ".join(map(str, document.ocr_pages))
        raise invalid(
            "file",
            f"스캔본이라 글자를 읽을 수 없습니다 (OCR 필요, {pages}쪽). 텍스트가 있는 PDF·DOCX로 올려 주세요.",
        )

    identity = KnownIdentity(
        name=name.strip(),
        aliases=_lines(aliases),
        phones=_lines(phone),
        emails=_lines(email),
        birthdate=birthdate.strip() or None,
        addresses=_lines(addresses),
        schools=_lines(schools),
        companies=_lines(companies),
    )
    candidate = Candidate(
        pseudonym=next_pseudonym(db), encrypted_identity=runtime.deid.seal(identity)
    )
    db.add(candidate)
    db.flush()
    application_id = new_id()
    deidentifier = runtime.deid.deidentifier(db)
    try:
        deidentified = await run_in_threadpool(
            deidentify_document, deidentifier, document, candidate_id=candidate.id, known=identity
        )
    except OcrRequired as exc:  # extract_document already caught scans; kept for safety
        raise invalid("file", str(exc)) from exc
    visible = [b for b in deidentified.blocks if b.kind is not BlockKind.hidden]
    info = s.DocumentInfo(
        format=deidentified.format,
        blocks=len(deidentified.blocks),
        hidden_blocks=len(deidentified.blocks) - len(visible),
        images_dropped=deidentified.images_dropped,
        replacements=deidentified.replacements,
    )
    approved = approved_set(posting)
    try:
        outcome = await screen_document(
            db,
            runtime.ai,
            posting=posting,
            competencies=approved.competencies if approved else [],
            application_id=application_id,
            document_text=render_blocks(visible),
            known=identity,
        )
    except (AiOutputInvalid, IdentifierInPrompt) as exc:
        _failed(db, application_id, posting_id, type(exc).__name__)
        raise
    except Exception as exc:
        log.exception("screening failed")
        _failed(db, application_id, posting_id, type(exc).__name__)
        raise ai_failed("AI 선별에 실패했습니다. 잠시 후 다시 올려 주세요.") from exc

    folder = runtime.uploads_dir / candidate.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{application_id}{_EXTENSIONS.get(document.format, '')}"
    path.write_bytes(data)
    created = Application(
        id=application_id,
        candidate=candidate,
        posting=posting,
        source_file_uri=path.resolve().as_uri(),
        profile=outcome.profile.model_dump(),
        document_info=info.model_dump(),
    )
    created.screening = Screening(
        fit_score=outcome.assessment.fit_score,
        rationale=outcome.assessment.rationale(),
        status=ScreeningStatus.hold,
        model=outcome.model,
        prompt_version=SCREENING_PROMPT,
    )
    db.add(created)
    db.flush()
    audit(db, me, "application.uploaded", "application", created.id, format=info.format)
    db.add(
        AuditLog(
            actor_type=ActorType.ai,
            action="screening.batch_completed",
            target_type="job_posting",
            target_id=posting.id,
            model=outcome.model,
            prompt_version=SCREENING_PROMPT,
            details={"count": 1},
        )
    )
    try:
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return s.UploadResult(
        application_id=created.id,
        candidate=views.candidate_ref(candidate),
        screening=s.Screening.model_validate(created.screening),
        document=info,
    )


def _failed(db: Db, application_id: str, posting_id: str, error: str) -> None:
    """Nothing of the upload is kept; the failure itself is audited."""
    db.rollback()
    db.add(
        AuditLog(
            actor_type=ActorType.ai,
            action="screening.failed",
            target_type="job_posting",
            target_id=posting_id,
            prompt_version=SCREENING_PROMPT,
            details={"application_id": application_id, "error": error},
        )
    )
    db.commit()
