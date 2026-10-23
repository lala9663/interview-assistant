"""공고·역량 사전 (FR-02): postings, competency-set versions, AI drafts, approval."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from interview_assistant.ai.competency import draft_competency_set
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.interviews import approved_set, latest_set
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


@router.get("/postings/{posting_id}/competency-sets", response_model=list[s.CompetencySet])
def competency_sets(posting_id: str, db: Db) -> list[s.CompetencySet]:
    return [s.CompetencySet.model_validate(x) for x in _posting(db, posting_id).competency_sets]


@router.post(
    "/postings/{posting_id}/competency-sets", response_model=s.CompetencySet, status_code=201
)
def create_competency_set(
    posting_id: str, body: s.CompetenciesBody, db: Db, me: Me
) -> s.CompetencySet:
    found = _posting(db, posting_id)
    latest = latest_set(found)
    created = CompetencySet(
        posting=found,
        version=(latest.version if latest else 0) + 1,
        competencies=[c.model_dump() for c in body.competencies],
    )
    db.add(created)
    db.flush()
    audit(db, me, "competency_set.created", "competency_set", created.id)
    db.commit()
    return s.CompetencySet.model_validate(created)


@router.post(
    "/postings/{posting_id}/competency-sets/generate",
    response_model=s.CompetencySet,
    status_code=201,
)
async def generate_competency_set(posting_id: str, db: Db, runtime: RuntimeDep) -> s.CompetencySet:
    found = _posting(db, posting_id)
    try:
        drafted = await draft_competency_set(db, runtime.ai, found)
    finally:
        db.commit()  # the AI call's audit row stays even when the draft is unusable
    return s.CompetencySet.model_validate(drafted)


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
    previous = approved_set(found.posting)
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
