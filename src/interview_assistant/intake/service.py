"""지원서 1건 처리: the one path every intake channel goes through.

    outcome = await process_application(db, ApplicationInput(...), ai=..., deid=..., uploads_dir=...)

A channel only turns what it received into an `ApplicationInput`: the upload screen (one file and
the identity typed into the form), the recruiting site (form fields, essays, attachments) and,
later, an archive import. The steps are the same for all of them:

1. find the posting, by id or by the site's posting number. Unknown or closed: refused
2. read the attachments with the 서류 읽기 settings taken at the start (documents/reading.py:
   PDF, DOCX, PPTX, HTML, HWP/HWPX, JPG/PNG, .doc/.ppt through LibreOffice; text layer or OCR
   page by page). Unsupported, encrypted, unreadable, or pages left unread: refused
3. find the candidate by the site's applicant number (keyed hash) or create one with a pseudonym
4. de-identify everything: form fields, essays, every block of every attachment
5. profile: form fields are already structured and become the profile as they are; without them
   the `screening` model structures the documents
6. screen against the JD and the approved competency dictionary (status starts at hold)
7. create the application, or update it (same site application number, or the same person's
   withdrawn application to the same posting): new profile, fresh screening, files replaced

All or nothing: when a step fails, a candidate created on the way is removed again and an update
leaves the previous version in place. No write transaction stays open while a model is called or
a thread works: SQLite would make every other writer wait, and a writer waiting inside the event
loop would stall it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse
from urllib.request import url2pathname

from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.gateway import AiGateway
from interview_assistant.ai.guard import IdentifierInPrompt
from interview_assistant.ai.prompts import SCREENING_PROMPT
from interview_assistant.ai.screening import assess_profile, structure_profile
from interview_assistant.deid.documents import DeidentifiedBlock, deidentify_document
from interview_assistant.deid.service import DeidService
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.documents import (
    BlockKind,
    ExtractedDocument,
    ExtractionError,
    UnsupportedFormat,
    extract_document,
    render_blocks,
)
from interview_assistant.documents.base import ConverterMissing, EncryptedDocument
from interview_assistant.documents.reading import DocumentReader
from interview_assistant.intake.forms import FormFields, build_profile, text_blocks, with_texts
from interview_assistant.interviews import screening_set
from interview_assistant.models import (
    ActorType,
    Application,
    ApplicationChannel,
    AuditLog,
    Candidate,
    Interviewer,
    JobPosting,
    PostingStatus,
    Screening,
    ScreeningStatus,
    SessionStatus,
)
from interview_assistant.models.base import new_id, utcnow
from interview_assistant.providers.base import ProviderUnavailable

log = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
EXTENSIONS = {
    "pdf": ".pdf", "docx": ".docx", "pptx": ".pptx", "html": ".html", "hwp": ".hwp", "hwpx": ".hwpx",
    "doc": ".doc", "ppt": ".ppt",
}  # fmt: skip
ATTACHMENT_KIND_LABEL = {"resume": "이력서", "portfolio": "포트폴리오", "certificate": "증빙", "other": "기타"}

T = TypeVar("T")


class IntakeRefused(Exception):
    """The application cannot be applied as sent. `code` is the reason the API and the event
    status carry (docs/site-intake-spec.md); messages name fields, never their values."""

    def __init__(
        self, code: str, message: str, *, field: str | None = None, retriable: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.retriable = retriable


@dataclass(frozen=True)
class Attachment:
    filename: str  # as sent; may hold the candidate's name, so it is de-identified and not kept
    data: bytes
    kind: str = "resume"  # resume, portfolio, certificate, other


@dataclass(frozen=True)
class ApplicationInput:
    channel: ApplicationChannel
    identity: KnownIdentity  # sealed into the candidate, used only to de-identify
    posting_id: str | None = None  # upload: the posting picked on screen
    posting_no: str | None = None  # site: the site's posting number
    applicant_no: str | None = None  # site: the same number is the same person (hashed)
    application_no: str | None = None  # site: the same number is the same application
    fields: FormFields | None = None
    attachments: tuple[Attachment, ...] = ()
    actor: Interviewer | None = None  # who uploaded; None for the site (system)
    revision: int | None = None


@dataclass
class ApplicationOutcome:
    application: Application
    candidate: Candidate
    document: dict[str, Any]  # DocumentInfo: counts only
    created: bool  # False: an existing application was updated
    new_candidate: bool
    screening_reset: bool  # an update replaced a screening people had already decided

    def summary(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "new_candidate": self.new_candidate,
            "screening_reset": self.screening_reset,
            "fit_score": self.application.screening.fit_score if self.application.screening else None,
        }


# --- concurrency ----------------------------------------------------------------------------


class KeyedLocks:
    """asyncio locks by key for work that must not overlap: events of the same application, or
    of the same applicant (finding or creating their candidate). Keys are taken in sorted order
    so two holders never wait on each other crosswise; unused locks are dropped."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._users: dict[str, int] = {}

    @asynccontextmanager
    async def hold(self, *keys: str | None) -> AsyncIterator[None]:
        wanted = sorted({k for k in keys if k})
        for key in wanted:
            self._users[key] = self._users.get(key, 0) + 1
            self._locks.setdefault(key, asyncio.Lock())
        taken: list[str] = []
        try:
            for key in wanted:
                await self._locks[key].acquire()
                taken.append(key)
            yield
        finally:
            for key in reversed(taken):
                self._locks[key].release()
            for key in wanted:
                self._users[key] -= 1
                if not self._users[key]:
                    del self._users[key], self._locks[key]


LOCKS = KeyedLocks()
# A new candidate's pseudonym is the highest one + 1, so two creators must not interleave. Workers
# and uploads create candidates on the event loop without awaiting in between; the lock also
# covers a caller on another thread.
_NEW_CANDIDATE = threading.Lock()


async def in_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run blocking work in a thread. Cancelled meanwhile, it still waits for the thread to finish
    before letting the cancellation through, so nothing else touches the same session at once."""
    future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        await asyncio.wait({future})
        raise


def next_pseudonym(db: Session) -> str:
    taken = db.scalars(select(Candidate.pseudonym).where(Candidate.pseudonym.like("CAND-%"))).all()
    numbers = [int(m.group(1)) for p in taken if (m := re.fullmatch(r"CAND-(\d+)", p))]
    return f"CAND-{max(numbers, default=0) + 1:04d}"


def merge_identity(old: KnownIdentity | None, new: KnownIdentity) -> KnownIdentity:
    """What we know about a person across their applications: the newest values first, older
    ones kept (an old name becomes an alias) so de-identification still finds them."""
    if old is None:
        return new

    def union(*groups: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(v for g in groups for v in g if v))

    old_name = (old.name,) if old.name and old.name != new.name else ()
    return KnownIdentity(
        name=new.name or old.name,
        aliases=union(new.aliases, old.aliases, old_name),
        phones=union(new.phones, old.phones),
        emails=union(new.emails, old.emails),
        birthdate=new.birthdate or old.birthdate,
        addresses=union(new.addresses, old.addresses),
        schools=union(new.schools, old.schools),
        companies=union(new.companies, old.companies),
    )


# --- steps ----------------------------------------------------------------------------------


def find_posting(db: Session, inp: ApplicationInput) -> JobPosting:
    if inp.posting_id is not None:
        posting = db.get(JobPosting, inp.posting_id)
    else:
        posting = db.scalar(select(JobPosting).where(JobPosting.site_posting_no == inp.posting_no))
    if posting is None:
        if inp.posting_no is None:
            raise IntakeRefused("unknown_posting", "공고를 찾을 수 없습니다.", field="posting_id")
        raise IntakeRefused(
            "unknown_posting",
            f"채용 사이트 공고 번호 {inp.posting_no}에 연결된 공고가 없습니다. 공고 화면에서 번호를 "
            "연결한 뒤 다시 처리하세요.",
            field="posting_no",
            retriable=True,
        )
    if posting.status is PostingStatus.closed:
        raise IntakeRefused(
            "posting_closed", "마감된 공고에는 지원서를 받을 수 없습니다.", retriable=True
        )
    return posting


def _where(inp: ApplicationInput, index: int, attachment: Attachment) -> tuple[str, str]:
    """(message prefix, field) for an attachment. An upload has one file and no prefix."""
    if inp.channel is ApplicationChannel.upload:
        return "", "file"
    label = ATTACHMENT_KIND_LABEL.get(attachment.kind, attachment.kind)
    return f"첨부 {index + 1}({label}): ", f"attachments[{index}]"


def read_attachments(
    inp: ApplicationInput, reader: DocumentReader | None = None
) -> list[ExtractedDocument]:
    """Text of every attachment, or the reason one cannot be used. No database.

    `reader` carries the 서류 읽기 settings the application is processed with (taken once, at the
    start); without it nothing is OCR'd. Codes: unsupported_attachment (format), encrypted_attachment
    (password), converter_missing (.doc/.ppt without LibreOffice), unreadable_attachment (broken),
    reader_unavailable (the reader configured for the format cannot run), ocr_required (a page
    needs OCR and the setting is text only), ocr_unavailable (OCR could not read it: no engine,
    model files missing, a failure). The last four can be retried once an admin has fixed it.
    """
    documents = []
    for i, attachment in enumerate(inp.attachments):
        prefix, field = _where(inp, i, attachment)
        if not attachment.data:
            raise IntakeRefused("invalid_field", f"{prefix}빈 파일입니다.", field=field)
        if len(attachment.data) > MAX_ATTACHMENT_BYTES:
            raise IntakeRefused("invalid_field", f"{prefix}파일이 너무 큽니다 (최대 10MB).", field=field)
        name = attachment.filename or "upload"
        try:
            document = reader.read(attachment.data, name) if reader else extract_document(attachment.data, name)
        except UnsupportedFormat as exc:
            raise IntakeRefused("unsupported_attachment", f"{prefix}{exc}", field=field) from exc
        except EncryptedDocument as exc:
            raise IntakeRefused("encrypted_attachment", f"{prefix}{exc}", field=field) from exc
        except ConverterMissing as exc:
            raise IntakeRefused("converter_missing", f"{prefix}{exc}", field=field, retriable=True) from exc
        except ExtractionError as exc:
            raise IntakeRefused(
                "unreadable_attachment",
                f"{prefix}파일을 읽을 수 없습니다. 손상되었거나 암호가 걸린 파일입니다.",
                field=field,
            ) from exc
        except ProviderUnavailable as exc:
            raise IntakeRefused("reader_unavailable", f"{prefix}{exc}", field=field, retriable=True) from exc
        if document.needs_ocr:
            held = [p for p in document.pages if p.needs_ocr]
            pages = ", ".join(str(p.number) for p in held)
            if any("텍스트만" in p.reason for p in held) or reader is None:
                raise IntakeRefused(
                    "ocr_required",
                    f"{prefix}텍스트 층이 없는 쪽이 있어 OCR이 필요합니다 ({pages}쪽). 읽기 방식이 "
                    "'텍스트만'이면 관리자가 '자동'으로 바꾼 뒤 다시 처리합니다.",
                    field=field,
                    retriable=True,
                )
            raise IntakeRefused(
                "ocr_unavailable",
                f"{prefix}OCR로 읽지 못했습니다 ({pages}쪽: {held[0].reason}). 관리자 > 모델 설정에서 "
                "OCR 엔진을 확인한 뒤 다시 처리합니다.",
                field=field,
                retriable=True,
            )
        documents.append(document)
    return documents


def _require(inp: ApplicationInput) -> None:
    if not (inp.identity.name or "").strip():
        raise IntakeRefused(
            "missing_field", "지원자 이름이 없습니다. 비식별화에만 쓰입니다.", field="name"
        )
    if not inp.attachments and (inp.fields is None or inp.fields.is_empty):
        raise IntakeRefused(
            "missing_field",
            "선별할 내용이 없습니다. 입력 칸이나 첨부가 하나 이상 있어야 합니다.",
            field="attachments",
        )


def _target(
    db: Session, inp: ApplicationInput, posting: JobPosting, applicant_hash: str | None
) -> Application | None:
    """The application this input updates, if any: the same site application number, or the
    same person's withdrawn application to the same posting (철회 후 재지원)."""
    if inp.application_no:
        found = db.scalar(
            select(Application).where(Application.site_application_no == inp.application_no)
        )
        if found is not None:
            if found.posting_id != posting.id:
                raise IntakeRefused(
                    "invalid_field", "이 지원 번호는 다른 공고의 지원서입니다.", field="posting_no"
                )
            if applicant_hash and found.candidate.site_applicant_hash not in (None, applicant_hash):
                raise IntakeRefused(
                    "invalid_field",
                    "이 지원 번호는 다른 지원자의 지원서입니다.",
                    field="applicant.applicant_no",
                )
            return found
    if applicant_hash is None:
        return None
    found = db.scalar(
        select(Application)
        .join(Candidate)
        .where(Candidate.site_applicant_hash == applicant_hash, Application.posting_id == posting.id)
    )
    if found is None:
        return None
    if found.withdrawn_at is None:
        raise IntakeRefused(
            "duplicate_application",
            "같은 지원자가 이 공고에 다른 지원 번호로 이미 지원했습니다.",
            field="application_no",
        )
    return found


def _candidate(
    db: Session, deid: DeidService, inp: ApplicationInput, target: Application | None, applicant_hash: str | None
) -> tuple[Candidate, bool, KnownIdentity]:
    """(candidate, created now, identity to de-identify with). A new candidate is committed
    right away so de-identification tokens can point at it."""
    candidate = target.candidate if target is not None else None
    if candidate is None and applicant_hash is not None:
        candidate = db.scalar(select(Candidate).where(Candidate.site_applicant_hash == applicant_hash))
    if candidate is not None:
        return candidate, False, merge_identity(deid.identity(candidate), inp.identity)
    with _NEW_CANDIDATE:
        candidate = Candidate(
            pseudonym=next_pseudonym(db),
            encrypted_identity=deid.seal(inp.identity),
            site_applicant_hash=applicant_hash,
        )
        db.add(candidate)
        db.commit()
    return candidate, True, inp.identity


def _deidentify(
    db: Session,
    deid: DeidService,
    candidate_id: str,
    identity: KnownIdentity,
    fields: FormFields | None,
    documents: list[ExtractedDocument],
) -> tuple[FormFields | None, list[DeidentifiedBlock], list[list[DeidentifiedBlock]], int]:
    """Runs in a thread and commits the tokens it creates. Returns the tokenised form fields,
    their blocks, each attachment's blocks and the number of replacements."""
    deidentifier = deid.deidentifier(db)
    replacements = 0
    form_blocks: list[DeidentifiedBlock] = []
    deid_fields = None
    if fields is not None and not fields.is_empty:
        slots = text_blocks(fields)
        synthetic = ExtractedDocument(filename="", format="form", blocks=tuple(b for _, b in slots))
        done = deidentify_document(deidentifier, synthetic, candidate_id=candidate_id, known=identity)
        form_blocks = list(done.blocks)
        replacements += done.replacements
        deid_fields = with_texts(fields, {path: b.text for (path, _), b in zip(slots, done.blocks, strict=True)})
    attachment_blocks = []
    for document in documents:
        done = deidentify_document(deidentifier, document, candidate_id=candidate_id, known=identity)
        attachment_blocks.append(list(done.blocks))
        replacements += done.replacements
    db.commit()
    return deid_fields, form_blocks, attachment_blocks, replacements


def _document_info(
    inp: ApplicationInput,
    documents: list[ExtractedDocument],
    form_blocks: list[DeidentifiedBlock],
    attachment_blocks: list[list[DeidentifiedBlock]],
    replacements: int,
) -> dict[str, Any]:
    formats = [d.format for d in documents]
    if inp.channel is ApplicationChannel.upload and len(formats) == 1 and not form_blocks:
        fmt = formats[0]
    else:
        fmt = "+".join([inp.channel.value, *formats])
    blocks = [*form_blocks, *(b for group in attachment_blocks for b in group)]
    info: dict[str, Any] = {
        "format": fmt,
        "blocks": len(blocks),
        "hidden_blocks": sum(b.kind is BlockKind.hidden for b in blocks),
        "images_dropped": sum(d.images_dropped for d in documents),
        "replacements": replacements,
    }
    readings = [d for d in documents if d.reading is not None]
    if readings:
        info["reading"] = reading_summary(readings)
    return info


def reading_summary(documents: list[ExtractedDocument]) -> dict[str, Any]:
    """How the attachments were read, kept with the application: the settings revision, mode,
    tools with versions, and per file the pages read by OCR with their confidence. Labels and
    numbers only, nothing from the files."""
    first = documents[0].reading
    assert first is not None
    files = []
    for d in documents:
        ocr = [p for p in d.pages if p.method.value == "ocr"]
        files.append(
            {
                "format": d.format,
                "converted_from": d.reading.converted_from if d.reading else None,
                "pages": len(d.pages),
                "ocr_pages": [p.number for p in ocr],
                "ocr_confidence": (
                    round(min(p.confidence for p in ocr if p.confidence is not None), 3)
                    if any(p.confidence is not None for p in ocr)
                    else None
                ),
                "pictures_read": sum(1 for i in d.images if i.decision == "ocr"),
                "photos_dropped": sum(1 for i in d.images if i.decision == "photo"),
                "garbled_pages": [p.number for p in d.pages if p.garbled is not None and "깨짐" in p.reason],
            }
        )
    return {
        "revision": first.revision,
        "mode": first.mode,
        "embedded_images": first.embedded_images,
        "sensitivity": first.sensitivity,
        "tools": list(dict.fromkeys(t for d in documents if d.reading for t in d.reading.tools)),
        "files": files,
    }


def uri_path(uri: str) -> Path:
    return Path(url2pathname(urlparse(uri).path))


def _store_files(
    uploads_dir: Path,
    inp: ApplicationInput,
    candidate_id: str,
    application_id: str,
    documents: list[ExtractedDocument],
) -> tuple[str | None, Path | None]:
    """Originals go to the raw zone (never served), named without anything from the file name.
    One upload: uploads/{candidate}/{application}.{ext}; otherwise a folder per version."""
    if not inp.attachments:
        return None, None
    base = uploads_dir / candidate_id
    if inp.channel is ApplicationChannel.upload and len(inp.attachments) == 1:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{application_id}{_extension(documents[0], inp.attachments[0].data)}"
        path.write_bytes(inp.attachments[0].data)
        return path.resolve().as_uri(), path
    folder = base / application_id / new_id()[:8]
    folder.mkdir(parents=True, exist_ok=True)
    for i, (attachment, document) in enumerate(zip(inp.attachments, documents, strict=True), 1):
        kind = attachment.kind if attachment.kind in ATTACHMENT_KIND_LABEL else "other"
        (folder / f"{i}-{kind}{_extension(document, attachment.data)}").write_bytes(attachment.data)
    return folder.resolve().as_uri() + "/", folder


def _extension(document: ExtractedDocument, data: bytes) -> str:
    if document.format == "image":
        return ".png" if data[:4] == b"\x89PNG" else ".jpg"
    return EXTENSIONS.get(document.format, "")


def remove_files(uri: str | None) -> None:
    if not uri:
        return
    path = uri_path(uri)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _drop_candidate(db: Session, candidate_id: str) -> None:
    """A candidate created for an application that did not make it: removed with its tokens."""
    candidate = db.get(Candidate, candidate_id)
    if candidate is not None and not candidate.applications:
        db.delete(candidate)
        db.commit()


def _audit_failure(db: Session, inp: ApplicationInput, posting_id: str, application_id: str, error: str) -> None:
    db.add(
        AuditLog(
            actor_type=ActorType.ai,
            action="screening.failed",
            target_type="job_posting",
            target_id=posting_id,
            prompt_version=SCREENING_PROMPT,
            details={"application_id": application_id, "channel": inp.channel.value, "error": error},
        )
    )
    db.commit()


# --- the service ----------------------------------------------------------------------------


async def process_application(
    db: Session,
    inp: ApplicationInput,
    *,
    ai: AiGateway,
    deid: DeidService,
    uploads_dir: Path,
    reader: DocumentReader | None = None,
) -> ApplicationOutcome:
    """Apply one application (see the module docstring). Raises IntakeRefused with a reason
    code; model errors come through as AiOutputInvalid / IdentifierInPrompt / ProviderUnavailable,
    anything else from the model as IntakeRefused("ai_failed"). `reader` comes from the same
    model-settings snapshot as `ai` (`ProviderSet.reader`); without it nothing is OCR'd."""
    posting = find_posting(db, inp)
    _require(inp)
    documents = await in_thread(read_attachments, inp, reader)
    applicant_hash = deid.applicant_hash(inp.applicant_no) if inp.applicant_no else None
    async with LOCKS.hold(f"applicant:{applicant_hash}" if applicant_hash else None):
        return await _apply(db, inp, posting, documents, applicant_hash, ai=ai, deid=deid, uploads_dir=uploads_dir)


async def _apply(
    db: Session,
    inp: ApplicationInput,
    posting: JobPosting,
    documents: list[ExtractedDocument],
    applicant_hash: str | None,
    *,
    ai: AiGateway,
    deid: DeidService,
    uploads_dir: Path,
) -> ApplicationOutcome:
    target = _target(db, inp, posting, applicant_hash)
    candidate, new_candidate, identity = _candidate(db, deid, inp, target, applicant_hash)
    application_id = target.id if target is not None else new_id()
    stored: tuple[str | None, Path | None] = (None, None)
    phase = "read"
    try:
        deid_fields, form_blocks, attachment_blocks, replacements = await in_thread(
            _deidentify,
            db,
            deid,
            candidate.id,
            identity,
            inp.fields,
            documents,
        )
        visible = [b for b in form_blocks if b.kind is not BlockKind.hidden]
        visible += [b for group in attachment_blocks for b in group if b.kind is not BlockKind.hidden]
        document_text = render_blocks(visible)
        info = _document_info(inp, documents, form_blocks, attachment_blocks, replacements)
        approved = screening_set(posting)
        phase = "model"
        try:
            if deid_fields is not None and deid_fields.has_profile:
                profile = build_profile(deid_fields)
            else:
                profile = await structure_profile(
                    db, ai, application_id=application_id, document_text=document_text, known=identity
                )
                db.commit()  # the call's audit row; nothing stays open across the next call
            assessment, model = await assess_profile(
                db,
                ai,
                posting=posting,
                competencies=approved.competencies if approved else [],
                application_id=application_id,
                profile=profile,
                document_text=document_text,
                known=identity,
            )
            db.commit()
        except (AiOutputInvalid, IdentifierInPrompt, ProviderUnavailable, IntakeRefused):
            raise
        except Exception as exc:
            log.exception("screening failed")
            raise IntakeRefused(
                "ai_failed", "AI 선별에 실패했습니다. 잠시 후 다시 시도하세요.", retriable=True
            ) from exc

        # Everything below is one transaction.
        phase = "apply"
        previous_uri = target.source_file_uri if target is not None else None
        stored = _store_files(uploads_dir, inp, candidate.id, application_id, documents)
        candidate.encrypted_identity = deid.seal(identity)
        screening_reset = False
        if target is None:
            application = Application(
                id=application_id,
                candidate=candidate,
                posting=posting,
                channel=inp.channel,
                site_application_no=inp.application_no,
            )
            db.add(application)
        else:
            application = target
            if application.screening is not None:
                screening_reset = application.screening.status is not ScreeningStatus.hold
                db.delete(application.screening)
                db.flush()
            application.site_application_no = inp.application_no or application.site_application_no
            application.withdrawn_at = None
        application.source_file_uri = stored[0]
        application.profile = profile.model_dump()
        application.document_info = info
        application.screening = Screening(
            fit_score=assessment.fit_score,
            rationale=assessment.rationale(),
            assessment=assessment.details(),
            recommendation=assessment.recommendation,
            status=ScreeningStatus.hold,  # people decide
            model=model,
            prompt_version=SCREENING_PROMPT,
        )
        db.flush()
        _audit_applied(db, inp, application, posting, info, model, created=target is None, reset=screening_reset)
        db.commit()
    except BaseException as exc:  # cancellation (a withdrawal arrived) included
        try:
            # A failed or refused model call left its audit row: keep it. Anything else is undone.
            db.commit() if phase == "model" else db.rollback()
        except Exception:
            db.rollback()
        remove_files(stored[0])
        if isinstance(exc, (AiOutputInvalid, IdentifierInPrompt, ProviderUnavailable)) or (
            isinstance(exc, IntakeRefused) and exc.code == "ai_failed"
        ):
            _audit_failure(db, inp, posting.id, application_id, type(exc).__name__)
        if new_candidate:
            _drop_candidate(db, candidate.id)
        raise
    if previous_uri and previous_uri != application.source_file_uri:
        remove_files(previous_uri)
    return ApplicationOutcome(
        application=application,
        candidate=candidate,
        document=info,
        created=target is None,
        new_candidate=new_candidate,
        screening_reset=screening_reset,
    )


def _audit_applied(
    db: Session,
    inp: ApplicationInput,
    application: Application,
    posting: JobPosting,
    info: dict[str, Any],
    model: str,
    *,
    created: bool,
    reset: bool,
) -> None:
    if inp.channel is ApplicationChannel.upload:
        actor_type, actor_id, action = ActorType.user, inp.actor.id if inp.actor else None, "application.uploaded"
        details: dict[str, Any] = {"format": info["format"]}
    else:
        actor_type, actor_id = ActorType.system, None
        action = "application.received" if created else "application.updated"
        details = {"channel": inp.channel.value, "revision": inp.revision, "format": info["format"]}
        if reset:
            details["screening_reset"] = True
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type="application",
            target_id=application.id,
            details=details,
        )
    )
    # The dashboard feed shows an upload's screening; site events are watched on 연동 현황, where
    # hundreds of them would not drown the feed.
    db.add(
        AuditLog(
            actor_type=ActorType.ai,
            action="screening.batch_completed" if inp.channel is ApplicationChannel.upload else "screening.completed",
            target_type="job_posting",
            target_id=posting.id,
            model=model,
            prompt_version=SCREENING_PROMPT,
            details={"count": 1}
            if inp.channel is ApplicationChannel.upload
            else {"application_id": application.id, "channel": inp.channel.value},
        )
    )


def withdraw_application(db: Session, application: Application) -> dict[str, Any]:
    """지원서 비활성화: out of every list and count, scheduled interviews cancelled. Files and
    tokens stay until the retention policy says otherwise; the site keeps the record."""
    application.withdrawn_at = utcnow()
    cancelled = [s for s in application.sessions if s.status is SessionStatus.scheduled]
    for session in cancelled:
        session.status = SessionStatus.cancelled
    db.add(
        AuditLog(
            actor_type=ActorType.system,
            action="application.withdrawn",
            target_type="application",
            target_id=application.id,
            details={"cancelled_sessions": len(cancelled)},
        )
    )
    return {"cancelled_sessions": len(cancelled)}
