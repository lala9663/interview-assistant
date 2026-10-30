"""서류 선별 (FR-01, 03): applications, screening decisions (탈락 with a reason), the candidate
index, uploads.

Upload: one channel into intake/service.py, like the recruiting site. The original file goes to
the raw zone on disk (uploads/, never served), its text is extracted and de-identified, hidden
text is kept out of the prompt, and the `screening` model structures a profile and assesses it.
The identity typed into the form is sealed into Candidate.encrypted_identity; the API only ever
shows the pseudonym. Withdrawn applications (recruiting site) leave every list.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select

from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import ai_failed, conflict, invalid, not_found
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.intake.service import (
    MAX_ATTACHMENT_BYTES,
    ApplicationInput,
    Attachment,
    IntakeRefused,
    process_application,
)
from interview_assistant.models import (
    Application,
    ApplicationChannel,
    JobPosting,
    PostingStatus,
    Screening,
    ScreeningStatus,
)

router = APIRouter(tags=["screening"])


def _application(db: Db, application_id: str) -> Application:
    found = db.get(Application, application_id)
    if found is None or found.deleted_at is not None:
        raise not_found("지원서")
    return found


def _live_applications(db: Db) -> list[Application]:
    return list(
        db.scalars(
            select(Application)
            .where(Application.deleted_at.is_(None), Application.withdrawn_at.is_(None))
            .order_by(Application.created_at)
        ).all()
    )


@router.get("/postings/{posting_id}/applications", response_model=list[s.ApplicationRow])
def applications(posting_id: str, db: Db) -> list[s.ApplicationRow]:
    if db.get(JobPosting, posting_id) is None:
        raise not_found("공고")
    rows = db.scalars(
        select(Application)
        .where(
            Application.posting_id == posting_id,
            Application.deleted_at.is_(None),
            Application.withdrawn_at.is_(None),
        )
        .order_by(Application.created_at)
    ).all()
    return [views.application_row(a) for a in rows]


@router.get("/applications/schedulable", response_model=list[s.SchedulableApplication])
def schedulable(
    db: Db, round: int | None = Query(None, ge=1, description="only those waiting for this round (1 = 1차)")
) -> list[s.SchedulableApplication]:
    """Applications waiting for their next round: round 1 after screening passed, round N after
    round N-1 was passed."""
    return views.schedulable(_live_applications(db), round)


@router.get("/applications/{application_id}", response_model=s.ApplicationDetail)
def application(application_id: str, db: Db) -> s.ApplicationDetail:
    return views.application_detail(_application(db, application_id))


MAX_REJECT_REASON = 500


@router.patch("/screenings/{screening_id}", response_model=s.Screening)
def update_screening(
    screening_id: str, body: s.ScreeningUpdate, db: Db, me: Me, runtime: RuntimeDep
) -> s.Screening:
    """탈락 needs a short reason; it is de-identified like any other free text, kept on the
    screening while it stays 탈락 and written into the audit row."""
    found = db.get(Screening, screening_id)
    if found is None:
        raise not_found("선별 결과")
    before = found.status
    reason = None
    if body.status is ScreeningStatus.rejected:
        text = (body.reason or "").strip()
        if not text:
            raise invalid("reason", "탈락 사유를 입력하세요.")
        if len(text) > MAX_REJECT_REASON:
            raise invalid("reason", f"탈락 사유는 {MAX_REJECT_REASON}자까지 쓸 수 있습니다.")
        candidate = found.application.candidate
        reason = runtime.deid.deidentify(db, text, candidate)
    if before is body.status and reason == found.reject_reason:
        return s.Screening.model_validate(found)
    found.status = body.status
    found.reject_reason = reason
    details: dict[str, str] = {"from": before.value, "to": body.status.value}
    if reason is not None:
        details["reason"] = reason
    audit(
        db,
        me,
        "screening.status_changed" if before is not body.status else "screening.reason_changed",
        "screening",
        found.id,
        **details,
    )
    db.commit()
    return s.Screening.model_validate(found)


@router.get("/candidates", response_model=list[s.CandidateIndexItem])
def candidates(db: Db) -> list[s.CandidateIndexItem]:
    return views.candidate_index(_live_applications(db))


def _lines(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.splitlines() if v.strip())


_REFUSED_STATUS = {"unknown_posting": 404, "posting_closed": 409, "duplicate_application": 409}


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
    is required; the rest (one value per line) helps de-identification catch more. The file goes
    through the same processing as applications from the recruiting site (intake/service.py)."""
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        raise not_found("공고")
    if posting.status is PostingStatus.closed:
        raise conflict("마감된 공고에는 지원서를 올릴 수 없습니다.")
    if not name.strip():
        raise invalid("name", "지원자 이름을 입력하세요. 비식별화에만 쓰입니다.")
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
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
    models = runtime.models.active  # this upload is read and screened with these settings
    try:
        outcome = await process_application(
            db,
            ApplicationInput(
                channel=ApplicationChannel.upload,
                identity=identity,
                posting_id=posting.id,
                attachments=(Attachment(filename=file.filename or "upload", data=data),),
                actor=me,
            ),
            ai=models.ai,
            deid=runtime.deid,
            uploads_dir=runtime.uploads_dir,
            reader=models.reader,
        )
    except IntakeRefused as exc:
        if exc.code == "ai_failed":
            raise ai_failed("AI 선별에 실패했습니다. 잠시 후 다시 올려 주세요.") from exc
        if exc.code in _REFUSED_STATUS:
            raise HTTPException(_REFUSED_STATUS[exc.code], exc.message) from exc
        raise invalid(exc.field or "file", exc.message) from exc
    application = outcome.application
    assert application.screening is not None
    return s.UploadResult(
        application_id=application.id,
        candidate=views.candidate_ref(outcome.candidate),
        screening=s.Screening.model_validate(application.screening),
        document=s.DocumentInfo.model_validate(outcome.document),
    )
