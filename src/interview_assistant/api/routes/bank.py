"""질문 은행 and 평점 기준 예시: the company text retrieval works on (docs/question-bank.md).

Anyone signed in can write and edit drafts; approving, retiring, restoring, importing a CSV and
running the AI check are for admins (the recruiters' role until SSO groups exist). Only approved
items are searched and shown to the AI. Editing an approved item sends it back to draft. Every
write is in the audit log; approving a question with prohibited-question warnings needs
`confirm_warnings` and the log keeps which warnings were confirmed.

Rubric examples are made-up answers. One that copies a stored applicant answer is refused, and so
is one with contact or ID-number shapes.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.gateway import AiCall
from interview_assistant.ai.prompts import (
    QUESTION_CHECK_PROMPT,
    QUESTION_CHECK_SCHEMA,
    QUESTION_CHECK_SYSTEM,
    question_check_prompt,
)
from interview_assistant.ai.question_rules import RULE_BY_CATEGORY, check
from interview_assistant.api import schemas as s
from interview_assistant.api.deps import Admin, Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import ai_failed, conflict, invalid, not_found
from interview_assistant.deid.leaks import residual_scan
from interview_assistant.interviews import approved_set
from interview_assistant.models import (
    BankSource,
    BankStatus,
    Interviewer,
    InterviewRound,
    QuestionBankItem,
    RubricExample,
)
from interview_assistant.models.base import utcnow
from interview_assistant.retrieval.bank import looks_like_applicant_answer, similarity
from interview_assistant.runtime import Runtime

log = logging.getLogger(__name__)

router = APIRouter(tags=["question-bank"])

MAX_QUESTION = 1000
MAX_FOLLOW_UPS = 10
MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 5000

# CSV headers, Korean or English.
_HEADERS = {
    "job_family": ("직군", "job_family"),
    "competency": ("역량", "competency"),
    "round": ("차수", "round", "round_position"),
    "question": ("질문", "question"),
    "intent": ("의도", "intent"),
    "follow_ups": ("꼬리질문 예시", "꼬리질문", "follow_ups"),
}


# --- views ------------------------------------------------------------------------------------


def _person(person: Interviewer | None) -> s.BankPerson | None:
    return s.BankPerson(id=person.id, name=person.name) if person is not None else None


def bank_view(item: QuestionBankItem) -> s.QuestionBankItem:
    return s.QuestionBankItem(
        id=item.id,
        job_family=item.job_family,
        competency=item.competency,
        round_position=item.round_position,
        question=item.question,
        intent=item.intent,
        follow_ups=list(item.follow_ups or []),
        status=item.status.value,
        flags=[s.BankFlag(**f) for f in item.flags or []],
        source=item.source.value,
        created_by=_person(item.author),
        approved_by=_person(item.approver),
        created_at=item.created_at,
        updated_at=item.updated_at,
        approved_at=item.approved_at,
        retired_at=item.retired_at,
    )


def rubric_view(row: RubricExample, overlaps: list[s.RubricOverlap] | None = None) -> s.RubricExample:
    return s.RubricExample(
        id=row.id,
        job_family=row.job_family,
        competency=row.competency,
        score=row.score,
        question=row.question,
        answer=row.answer,
        rationale=row.rationale,
        status=row.status.value,
        source=row.source.value,
        created_by=_person(row.author),
        approved_by=_person(row.approver),
        created_at=row.created_at,
        updated_at=row.updated_at,
        approved_at=row.approved_at,
        retired_at=row.retired_at,
        overlaps=overlaps or [],
    )


def families(db: Session, extra: list[tuple[str, str]]) -> list[s.BankFamily]:
    """Job families and their competencies: those in use in the bank or rubric, plus every
    posting's approved competency dictionaries (what a new question can be written for)."""
    found: dict[str, set[str]] = {}
    for family, competency in extra:
        found.setdefault(family, set()).add(competency)
    for round_ in db.scalars(select(InterviewRound)).all():
        approved = approved_set(round_)
        names = [c["name"] for c in approved.competencies] if approved else []
        found.setdefault(round_.posting.job_family, set()).update(names)
    return [s.BankFamily(job_family=f, competencies=sorted(c)) for f, c in sorted(found.items())]


# --- helpers ----------------------------------------------------------------------------------


def _item(db: Db, item_id: str) -> QuestionBankItem:
    found = db.get(QuestionBankItem, item_id)
    if found is None:
        raise not_found("질문")
    return found


def _clean(body: s.BankQuestionBody) -> dict[str, Any]:
    question = re.sub(r"\s+", " ", body.question).strip()
    if not question:
        raise invalid("question", "질문을 입력하세요.")
    if len(question) > MAX_QUESTION:
        raise invalid("question", f"질문은 {MAX_QUESTION}자 이하로 써 주세요.")
    follow_ups = [re.sub(r"\s+", " ", f).strip() for f in body.follow_ups]
    follow_ups = [f for f in follow_ups if f]
    if len(follow_ups) > MAX_FOLLOW_UPS:
        raise invalid("follow_ups", f"꼬리질문 예시는 {MAX_FOLLOW_UPS}개까지입니다.")
    if any(len(f) > MAX_QUESTION for f in follow_ups):
        raise invalid("follow_ups", f"꼬리질문 예시는 {MAX_QUESTION}자 이하로 써 주세요.")
    job_family, competency = body.job_family.strip(), body.competency.strip()
    if not job_family:
        raise invalid("job_family", "직군을 고르세요.")
    if not competency:
        raise invalid("competency", "역량을 고르세요.")
    return {
        "job_family": job_family,
        "competency": competency,
        "round_position": body.round_position,
        "question": question,
        "intent": body.intent.strip(),
        "follow_ups": follow_ups,
    }


def _rule_flags(question: str, follow_ups: list[str]) -> list[dict[str, str]]:
    return [f.as_dict() for f in check(question, *follow_ups)]


async def reindex(runtime: Runtime) -> None:
    """Make an approval or retirement searchable now; on failure the background catch-up retries."""
    try:
        await runtime.retrieval.refresh()
    except Exception:
        log.exception("could not refresh the embedding index")
        runtime.retrieval.changed()


# --- question bank ----------------------------------------------------------------------------


@router.get("/question-bank", response_model=s.QuestionBankList)
def question_bank(
    db: Db,
    job_family: str | None = Query(None),
    competency: str | None = Query(None),
    round: int | None = Query(None, ge=1, le=6),
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
) -> s.QuestionBankList:
    rows = db.scalars(
        select(QuestionBankItem).order_by(
            QuestionBankItem.job_family, QuestionBankItem.competency, QuestionBankItem.created_at
        )
    ).all()
    every = [(r.job_family, r.competency) for r in rows]
    if job_family:
        rows = [r for r in rows if r.job_family == job_family]
    if competency:
        rows = [r for r in rows if r.competency == competency]
    if round is not None:
        rows = [r for r in rows if r.round_position in (None, round)]
    counts = {v.value: sum(1 for r in rows if r.status is v) for v in BankStatus}
    if status:
        rows = [r for r in rows if r.status.value == status]
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in r.question.lower()
            or needle in r.intent.lower()
            or any(needle in f.lower() for f in r.follow_ups or [])
        ]
    return s.QuestionBankList(
        items=[bank_view(r) for r in rows],
        families=families(db, every),
        counts=counts,
        total=len(rows),
    )


@router.post("/question-bank/check", response_model=s.BankCheckResult)
def check_question(body: s.BankCheckRequest, me: Me) -> s.BankCheckResult:
    """Prohibited-question warnings for text being written (rules only, nothing stored)."""
    return s.BankCheckResult(flags=[s.BankFlag(**f) for f in _rule_flags(body.question, body.follow_ups)])


@router.post("/question-bank", response_model=s.QuestionBankItem, status_code=201)
def create_question(body: s.BankQuestionBody, db: Db, me: Me) -> s.QuestionBankItem:
    values = _clean(body)
    item = QuestionBankItem(
        **values,
        status=BankStatus.draft,
        flags=_rule_flags(values["question"], values["follow_ups"]),
        source=BankSource.manual,
        created_by=me.id,
    )
    db.add(item)
    db.flush()
    audit(
        db,
        me,
        "question_bank.created",
        "question_bank_item",
        item.id,
        flags=[f["category"] for f in item.flags],
    )
    db.commit()
    return bank_view(item)


@router.put("/question-bank/{item_id}", response_model=s.QuestionBankItem)
async def update_question(
    item_id: str, body: s.BankQuestionBody, db: Db, me: Me, runtime: RuntimeDep
) -> s.QuestionBankItem:
    """Edit a draft or an approved question. An approved one goes back to draft (approve again)."""
    item = _item(db, item_id)
    if item.status is BankStatus.retired:
        raise conflict("폐기한 질문은 고칠 수 없습니다. 먼저 되살리세요.")
    values = _clean(body)
    was_approved = item.status is BankStatus.approved
    for key, value in values.items():
        setattr(item, key, value)
    ai_flags = [f for f in item.flags or [] if f.get("source") == "ai"]
    changed_text = item.question != values["question"]
    item.flags = _rule_flags(values["question"], values["follow_ups"]) + ([] if changed_text else ai_flags)
    if was_approved:
        item.status, item.approved_by, item.approved_at = BankStatus.draft, None, None
    audit(
        db,
        me,
        "question_bank.updated",
        "question_bank_item",
        item.id,
        back_to_draft=was_approved,
        flags=[f["category"] for f in item.flags],
    )
    db.commit()
    if was_approved:
        await reindex(runtime)
    db.refresh(item)
    return bank_view(item)


@router.post("/question-bank/{item_id}/approve", response_model=s.QuestionBankItem)
async def approve_question(
    item_id: str, body: s.ApproveRequest, db: Db, admin: Admin, runtime: RuntimeDep
) -> s.QuestionBankItem:
    item = _item(db, item_id)
    if item.status is BankStatus.approved:
        raise conflict("이미 승인한 질문입니다.")
    if item.status is BankStatus.retired:
        raise conflict("폐기한 질문은 승인할 수 없습니다. 먼저 되살리세요.")
    ai_flags = [f for f in item.flags or [] if f.get("source") == "ai"]
    item.flags = _rule_flags(item.question, list(item.follow_ups or [])) + ai_flags
    if item.flags and not body.confirm_warnings:
        labels = ", ".join(dict.fromkeys(f["label"] for f in item.flags))
        raise conflict(
            f"금지 질문 경고가 있습니다({labels}). 직무와 관련 있는 질문인지 확인한 뒤 경고를 확인하고 승인하세요."
        )
    item.status, item.approved_by, item.approved_at = BankStatus.approved, admin.id, utcnow()
    audit(
        db,
        admin,
        "question_bank.approved",
        "question_bank_item",
        item.id,
        flags=list(dict.fromkeys(f["category"] for f in item.flags)),
        confirmed_warnings=bool(item.flags),
    )
    db.commit()
    await reindex(runtime)
    db.refresh(item)
    return bank_view(item)


@router.post("/question-bank/{item_id}/retire", response_model=s.QuestionBankItem)
async def retire_question(item_id: str, db: Db, admin: Admin, runtime: RuntimeDep) -> s.QuestionBankItem:
    item = _item(db, item_id)
    if item.status is BankStatus.retired:
        raise conflict("이미 폐기한 질문입니다.")
    was_approved = item.status is BankStatus.approved
    item.status, item.retired_at = BankStatus.retired, utcnow()
    audit(db, admin, "question_bank.retired", "question_bank_item", item.id, was_approved=was_approved)
    db.commit()
    if was_approved:
        await reindex(runtime)
    db.refresh(item)
    return bank_view(item)


@router.post("/question-bank/{item_id}/restore", response_model=s.QuestionBankItem)
def restore_question(item_id: str, db: Db, admin: Admin) -> s.QuestionBankItem:
    """A retired question back to draft (it needs approving again)."""
    item = _item(db, item_id)
    if item.status is not BankStatus.retired:
        raise conflict("폐기한 질문만 되살릴 수 있습니다.")
    item.status, item.retired_at, item.approved_by, item.approved_at = BankStatus.draft, None, None, None
    audit(db, admin, "question_bank.restored", "question_bank_item", item.id)
    db.commit()
    db.refresh(item)
    return bank_view(item)


@router.post("/question-bank/{item_id}/ai-check", response_model=s.QuestionBankItem)
async def ai_check_question(item_id: str, db: Db, admin: Admin, runtime: RuntimeDep) -> s.QuestionBankItem:
    """Ask the LLM what the rules may have missed. The question only, no candidate data."""
    item = _item(db, item_id)
    try:
        result = await runtime.ai.generate(
            db,
            AiCall(
                action="question_bank.ai_checked",
                prompt_version=QUESTION_CHECK_PROMPT,
                system=QUESTION_CHECK_SYSTEM,
                prompt=question_check_prompt(question=item.question, follow_ups=list(item.follow_ups or [])),
                schema=QUESTION_CHECK_SCHEMA,
                max_tokens=1000,
                target_type="question_bank_item",
                target_id=item.id,
            ),
        )
    except AiOutputInvalid as exc:
        raise ai_failed(str(exc)) from exc
    issues = (result.structured or {}).get("issues") or []
    ai_flags = []
    for issue in issues if isinstance(issues, list) else []:
        rule = RULE_BY_CATEGORY.get(str(issue.get("category")))
        if rule is None:
            continue
        ai_flags.append(
            {
                "category": rule.category,
                "label": rule.label,
                "basis": rule.basis,
                "matched": str(issue.get("quote") or "")[:200],
                "source": "ai",
                "note": str(issue.get("reason") or "")[:300],
            }
        )
    rules = _rule_flags(item.question, list(item.follow_ups or []))
    item.flags = rules + ai_flags
    db.commit()
    db.refresh(item)
    return bank_view(item)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):  # Excel on Korean Windows saves CSV as CP949
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise invalid("file", "CSV 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949로 저장하세요).")


def _columns(fieldnames: list[str]) -> dict[str, str]:
    found = {}
    lowered = {name.strip().lower(): name for name in fieldnames}
    for key, names in _HEADERS.items():
        for name in names:
            if name.lower() in lowered:
                found[key] = lowered[name.lower()]
                break
    missing = [names[0] for key, names in _HEADERS.items() if key in ("job_family", "competency", "question") and key not in found]
    if missing:
        raise invalid("file", f"CSV 첫 줄에 {', '.join(missing)} 열이 있어야 합니다.")
    return found


def _round(value: str) -> int | None:
    value = value.strip().replace("차", "")
    if not value or value in ("전체", "모든 차수", "-"):
        return None
    if not value.isdigit() or not 1 <= int(value) <= 6:
        raise ValueError("차수는 1~6 또는 비워 둡니다.")
    return int(value)


def _key(job_family: str, competency: str, question: str) -> tuple[str, str, str]:
    return (job_family, competency, re.sub(r"\s+", "", question))


@router.post("/question-bank/import", response_model=s.ImportResult)
async def import_questions(
    db: Db,
    admin: Admin,
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
) -> s.ImportResult:
    """CSV (직군, 역량, 차수, 질문, 의도, 꼬리질문 예시 — '|' or line breaks between examples) into
    drafts. Nothing is approved by an import. `dry_run` only reports what would happen."""
    data = await file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise invalid("file", "CSV가 너무 큽니다 (최대 2MB).")
    reader = csv.DictReader(io.StringIO(_decode(data)))
    columns = _columns(list(reader.fieldnames or []))
    existing = {
        _key(r.job_family, r.competency, r.question) for r in db.scalars(select(QuestionBankItem)).all()
    }
    errors: list[s.ImportRowIssue] = []
    warnings: list[s.ImportRowIssue] = []
    created = skipped = rows = 0
    for number, raw in enumerate(reader, start=1):
        rows += 1
        if rows > MAX_IMPORT_ROWS:
            errors.append(s.ImportRowIssue(row=number, message=f"{MAX_IMPORT_ROWS}행까지만 가져옵니다."))
            break

        def cell(key: str, raw: dict[str, Any] = raw) -> str:
            column = columns.get(key)
            return str(raw.get(column) or "").strip() if column else ""

        follow_ups = [f.strip() for f in re.split(r"\|\||\||\n", cell("follow_ups")) if f.strip()]
        try:
            round_position = _round(cell("round"))
            values = _clean(
                s.BankQuestionBody(
                    job_family=cell("job_family")[:100],
                    competency=cell("competency")[:100],
                    round_position=round_position,
                    question=cell("question"),
                    intent=cell("intent")[:200],
                    follow_ups=follow_ups,
                )
            )
        except ValueError as exc:
            errors.append(s.ImportRowIssue(row=number, message=str(exc)))
            continue
        except Exception as exc:  # invalid(): HTTPException with a detail list
            detail = getattr(exc, "detail", None)
            message = detail[0]["msg"] if isinstance(detail, list) and detail else str(detail or exc)
            errors.append(s.ImportRowIssue(row=number, message=message))
            continue
        key = _key(values["job_family"], values["competency"], values["question"])
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        flags = _rule_flags(values["question"], values["follow_ups"])
        if flags:
            labels = ", ".join(f["label"] for f in flags)
            warnings.append(s.ImportRowIssue(row=number, message=f"금지 질문 경고: {labels}"))
        created += 1
        if not dry_run:
            db.add(
                QuestionBankItem(
                    **values,
                    status=BankStatus.draft,
                    flags=flags,
                    source=BankSource.csv,
                    created_by=admin.id,
                )
            )
    if not dry_run:
        audit(
            db,
            admin,
            "question_bank.imported",
            "question_bank",
            None,
            rows=rows,
            created=created,
            skipped=skipped,
            errors=len(errors),
            warnings=len(warnings),
        )
        db.commit()
    return s.ImportResult(
        dry_run=dry_run,
        rows=rows,
        created=created,
        skipped=skipped,
        errors=errors,
        warnings=warnings,
    )


# --- rubric examples (평점 기준 예시) ------------------------------------------------------------


def _example(db: Db, example_id: str) -> RubricExample:
    found = db.get(RubricExample, example_id)
    if found is None:
        raise not_found("평점 기준 예시")
    return found


def _clean_example(db: Db, body: s.RubricExampleBody) -> dict[str, Any]:
    answer = body.answer.strip()
    if not answer:
        raise invalid("answer", "예시 답변을 입력하세요.")
    if len(answer) > 4000:
        raise invalid("answer", "예시 답변은 4,000자 이하로 써 주세요.")
    if not body.job_family.strip() or not body.competency.strip():
        raise invalid("competency", "직군과 역량을 고르세요.")
    if residual_scan(answer) or residual_scan(body.question):
        raise invalid("answer", "연락처·이메일·주민번호 모양이 있습니다. 실제 사람의 정보는 쓰지 마세요.")
    if looks_like_applicant_answer(db, answer):
        raise conflict(
            "지원자의 실제 답변과 거의 같습니다. 평점 기준 예시는 사람이 새로 쓴 가상의 답변이어야 합니다."
        )
    return {
        "job_family": body.job_family.strip(),
        "competency": body.competency.strip(),
        "score": body.score,
        "question": body.question.strip(),
        "answer": answer,
        "rationale": body.rationale.strip(),
    }


async def overlaps_for(runtime: Runtime, db: Session, rows: list[RubricExample]) -> dict[str, list[s.RubricOverlap]]:
    """Approved examples of the same job family and competency at another score that read almost
    the same as each row (dense similarity at the duplicate threshold). Uses the stored vectors of
    approved rows; drafts are embedded on the fly. Empty without an index."""
    retrieval = runtime.retrieval
    served = retrieval.serving
    if served is None or not rows:
        return {}
    threshold = retrieval.threshold("duplicate_threshold", 0.9)
    approved = db.scalars(select(RubricExample).where(RubricExample.status == BankStatus.approved)).all()
    vectors = {r.id: served.index.vector(("rubric", r.id, 0)) for r in approved}
    drafts = [r for r in rows if vectors.get(r.id) is None and r.status is not BankStatus.retired]
    if drafts:
        try:
            for row, emb in zip(drafts, await retrieval.encode([r.answer for r in drafts]), strict=True):
                vectors[row.id] = emb.dense
        except Exception:
            log.exception("could not embed rubric drafts for the overlap check")
    out: dict[str, list[s.RubricOverlap]] = {}
    for row in rows:
        mine = vectors.get(row.id)
        if mine is None:
            continue
        found = []
        for other in approved:
            theirs = vectors.get(other.id)
            if (
                other.id == row.id
                or theirs is None
                or other.score == row.score
                or other.competency != row.competency
                or other.job_family != row.job_family
            ):
                continue
            score = similarity(list(mine), list(theirs))
            if score >= threshold:
                found.append(s.RubricOverlap(id=other.id, score=other.score, similarity=round(score, 3)))
        out[row.id] = found
    return out


@router.get("/rubric-examples", response_model=s.RubricList)
async def rubric_examples(
    db: Db,
    runtime: RuntimeDep,
    job_family: str | None = Query(None),
    competency: str | None = Query(None),
    status: str | None = Query(None),
) -> s.RubricList:
    rows = db.scalars(
        select(RubricExample).order_by(
            RubricExample.job_family, RubricExample.competency, RubricExample.score, RubricExample.created_at
        )
    ).all()
    every = [(r.job_family, r.competency) for r in rows]
    if job_family:
        rows = [r for r in rows if r.job_family == job_family]
    if competency:
        rows = [r for r in rows if r.competency == competency]
    counts = {v.value: sum(1 for r in rows if r.status is v) for v in BankStatus}
    if status:
        rows = [r for r in rows if r.status.value == status]
    overlaps = await overlaps_for(runtime, db, list(rows))
    return s.RubricList(
        items=[rubric_view(r, overlaps.get(r.id)) for r in rows],
        families=families(db, every),
        counts=counts,
    )


@router.post("/rubric-examples", response_model=s.RubricExample, status_code=201)
async def create_example(body: s.RubricExampleBody, db: Db, me: Me, runtime: RuntimeDep) -> s.RubricExample:
    values = _clean_example(db, body)
    row = RubricExample(**values, status=BankStatus.draft, source=BankSource.manual, created_by=me.id)
    db.add(row)
    db.flush()
    audit(db, me, "rubric_example.created", "rubric_example", row.id, competency=row.competency, score=row.score)
    db.commit()
    overlaps = await overlaps_for(runtime, db, [row])
    return rubric_view(row, overlaps.get(row.id))


@router.put("/rubric-examples/{example_id}", response_model=s.RubricExample)
async def update_example(
    example_id: str, body: s.RubricExampleBody, db: Db, me: Me, runtime: RuntimeDep
) -> s.RubricExample:
    row = _example(db, example_id)
    if row.status is BankStatus.retired:
        raise conflict("폐기한 예시는 고칠 수 없습니다. 먼저 되살리세요.")
    values = _clean_example(db, body)
    was_approved = row.status is BankStatus.approved
    for key, value in values.items():
        setattr(row, key, value)
    if was_approved:
        row.status, row.approved_by, row.approved_at = BankStatus.draft, None, None
    audit(db, me, "rubric_example.updated", "rubric_example", row.id, back_to_draft=was_approved)
    db.commit()
    if was_approved:
        await reindex(runtime)
    db.refresh(row)
    overlaps = await overlaps_for(runtime, db, [row])
    return rubric_view(row, overlaps.get(row.id))


@router.post("/rubric-examples/{example_id}/approve", response_model=s.RubricExample)
async def approve_example(example_id: str, db: Db, admin: Admin, runtime: RuntimeDep) -> s.RubricExample:
    row = _example(db, example_id)
    if row.status is not BankStatus.draft:
        raise conflict("초안만 승인할 수 있습니다.")
    row.status, row.approved_by, row.approved_at = BankStatus.approved, admin.id, utcnow()
    audit(db, admin, "rubric_example.approved", "rubric_example", row.id, competency=row.competency, score=row.score)
    db.commit()
    await reindex(runtime)
    db.refresh(row)
    overlaps = await overlaps_for(runtime, db, [row])
    return rubric_view(row, overlaps.get(row.id))


@router.post("/rubric-examples/{example_id}/retire", response_model=s.RubricExample)
async def retire_example(example_id: str, db: Db, admin: Admin, runtime: RuntimeDep) -> s.RubricExample:
    row = _example(db, example_id)
    if row.status is BankStatus.retired:
        raise conflict("이미 폐기한 예시입니다.")
    was_approved = row.status is BankStatus.approved
    row.status, row.retired_at = BankStatus.retired, utcnow()
    audit(db, admin, "rubric_example.retired", "rubric_example", row.id)
    db.commit()
    if was_approved:
        await reindex(runtime)
    db.refresh(row)
    return rubric_view(row)


@router.post("/rubric-examples/{example_id}/restore", response_model=s.RubricExample)
def restore_example(example_id: str, db: Db, admin: Admin) -> s.RubricExample:
    row = _example(db, example_id)
    if row.status is not BankStatus.retired:
        raise conflict("폐기한 예시만 되살릴 수 있습니다.")
    row.status, row.retired_at, row.approved_by, row.approved_at = BankStatus.draft, None, None, None
    audit(db, admin, "rubric_example.restored", "rubric_example", row.id)
    db.commit()
    db.refresh(row)
    return rubric_view(row)
