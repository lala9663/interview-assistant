"""공고·역량 사전 (FR-02): postings, the link to the recruiting site's posting number,
competency-set versions (editing and approval; creating and AI drafts are per round, rounds.py)."""

from __future__ import annotations

import re

from fastapi import APIRouter
from sqlalchemy import select

from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.interviews import approved_set, rounds_of
from interview_assistant.models import CompetencySet, JobPosting, PresetQuestion
from interview_assistant.models.base import utcnow

router = APIRouter(tags=["postings"])


def _posting(db: Db, posting_id: str) -> JobPosting:
    posting = db.get(JobPosting, posting_id)
    if posting is None:
        raise not_found("공고")
    return posting


def _set(db: Db, set_id: str) -> CompetencySet:
    found = db.get(CompetencySet, set_id)
    if found is None:
        raise not_found("역량 사전")
    return found


@router.get("/postings", response_model=list[s.PostingSummary])
def postings(db: Db) -> list[s.PostingSummary]:
    rows = db.scalars(select(JobPosting).order_by(JobPosting.created_at)).all()
    return [views.posting_summary(p) for p in rows]


@router.get("/postings/{posting_id}", response_model=s.PostingDetail)
def posting(posting_id: str, db: Db) -> s.PostingDetail:
    return views.posting_detail(_posting(db, posting_id))


_SITE_POSTING_NO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@router.patch("/postings/{posting_id}", response_model=s.PostingDetail)
def update_posting(posting_id: str, body: s.UpdatePostingRequest, db: Db, me: Me) -> s.PostingDetail:
    """Link the posting to the recruiting site's posting number (or unlink with null/""). Site
    events name their posting by it; events that failed as `unknown_posting` can then be
    processed again from 연동 현황."""
    found = _posting(db, posting_id)
    number = (body.site_posting_no or "").strip() or None
    if number is not None and not _SITE_POSTING_NO.match(number):
        raise invalid("site_posting_no", "영문·숫자와 . _ : - 만 쓸 수 있습니다 (64자 이하).")
    if number is not None:
        other = db.scalar(select(JobPosting).where(JobPosting.site_posting_no == number))
        if other is not None and other.id != found.id:
            raise conflict(f"공고 번호 {number}는 이미 '{other.title}' 공고에 연결되어 있습니다.")
    before = found.site_posting_no
    if before != number:
        found.site_posting_no = number
        audit(db, me, "posting.site_linked", "job_posting", found.id, **{"from": before, "to": number})
        db.commit()
    return views.posting_detail(found)


@router.get("/postings/{posting_id}/competency-sets", response_model=list[s.CompetencySet])
def competency_sets(posting_id: str, db: Db) -> list[s.CompetencySet]:
    """Every version of every round, rounds in order (`round_id` says whose)."""
    posting = _posting(db, posting_id)
    return [s.CompetencySet.model_validate(x) for r in rounds_of(posting) for x in r.competency_sets]


@router.put("/competency-sets/{set_id}", response_model=s.CompetencySet)
def update_competency_set(set_id: str, body: s.CompetenciesBody, db: Db, me: Me) -> s.CompetencySet:
    found = _set(db, set_id)
    if found.approved_at is not None:
        raise conflict("확정된 버전은 수정할 수 없습니다. 새 버전을 만드세요.")
    found.competencies = [c.model_dump() for c in body.competencies]
    audit(db, me, "competency_set.updated", "competency_set", found.id)
    db.commit()
    return s.CompetencySet.model_validate(found)


@router.post("/competency-sets/{set_id}/approve", response_model=s.CompetencySet)
def approve_competency_set(set_id: str, db: Db, me: Me) -> s.CompetencySet:
    found = _set(db, set_id)
    if found.approved_at is not None:
        raise conflict("이미 확정된 버전입니다.")
    if not found.competencies:
        raise invalid("competencies", "역량이 하나 이상 있어야 확정할 수 있습니다.")
    previous = approved_set(found.round)
    found.approved_by = me.id
    found.approved_at = utcnow()
    # Preset questions follow the competencies they were written for.
    if previous is not None and not found.preset_questions:
        keep = {c["name"] for c in found.competencies}
        carried = [q for q in previous.preset_questions if q.competency in keep]
        for position, q in enumerate(carried, start=1):
            found.preset_questions.append(
                PresetQuestion(
                    position=position, competency=q.competency, question=q.question, intent=q.intent
                )
            )
    audit(db, me, "competency_set.approved", "competency_set", found.id)
    db.commit()
    return s.CompetencySet.model_validate(found)
