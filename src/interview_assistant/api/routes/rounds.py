"""전형 (interview rounds): a posting's rounds, their competency dictionary versions and their
preset questions (FR-02, FR-06).

Rounds run in order (1차, 2차 ...). A round that already has sessions or decisions keeps its place:
it cannot move or be deleted, so what an application passed stays what it passed. A posting keeps
at least one round. Competency versions count per round and approved versions are read-only, their
preset questions too; a new draft copies the questions of the round's approved version, and AI can
add questions to a draft (two per competency, none an earlier round already uses).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from interview_assistant.ai.competency import draft_competency_set
from interview_assistant.ai.presets import draft_preset_questions
from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me, RuntimeDep, audit
from interview_assistant.api.errors import conflict, invalid, not_found
from interview_assistant.interviews import approved_set, latest_set, rounds_of
from interview_assistant.models import (
    CompetencySet,
    InterviewRound,
    JobPosting,
    PresetQuestion,
)

router = APIRouter(tags=["rounds"])

MAX_ROUNDS = 6


def get_round(db: Db, round_id: str) -> InterviewRound:
    found = db.get(InterviewRound, round_id)
    if found is None:
        raise not_found("차수")
    return found


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


def _locked(round_: InterviewRound) -> bool:
    return views.round_summary(round_).locked


def _name(value: str) -> str:
    name = value.strip()
    if not name:
        raise invalid("name", "차수 이름을 입력하세요. 예: 직무 면접, 임원 면접")
    return name


def _interviewers(value: int) -> int:
    if not 1 <= value <= 10:
        raise invalid("recommended_interviewers", "권장 면접관 수는 1~10명입니다.")
    return value


def _place(db: Db, ordered: list[InterviewRound]) -> None:
    """Number `ordered` 1..n. Positions are unique per posting, so they go out of the way first."""
    for i, round_ in enumerate(ordered, start=1):
        round_.position = -i
    db.flush()
    for i, round_ in enumerate(ordered, start=1):
        round_.position = i
    db.flush()


# --- rounds ---------------------------------------------------------------------------------


@router.get("/postings/{posting_id}/rounds", response_model=list[s.RoundSummary])
def rounds(posting_id: str, db: Db) -> list[s.RoundSummary]:
    return [views.round_summary(r) for r in rounds_of(_posting(db, posting_id))]


@router.post("/postings/{posting_id}/rounds", response_model=s.RoundSummary, status_code=201)
def create_round(posting_id: str, body: s.CreateRoundRequest, db: Db, me: Me) -> s.RoundSummary:
    """Adds a round after the last one. Its competency dictionary starts empty (copy the earlier
    round's or draft one with AI)."""
    posting = _posting(db, posting_id)
    if len(posting.rounds) >= MAX_ROUNDS:
        raise conflict(f"차수는 {MAX_ROUNDS}개까지 둘 수 있습니다.")
    created = InterviewRound(
        posting=posting,
        position=max((r.position for r in posting.rounds), default=0) + 1,
        name=_name(body.name),
        default_mode=body.default_mode,
        recommended_interviewers=_interviewers(body.recommended_interviewers),
        show_previous_scores=body.show_previous_scores,
    )
    db.add(created)
    db.flush()
    audit(db, me, "round.created", "interview_round", created.id, position=created.position)
    db.commit()
    return views.round_summary(created)


@router.patch("/rounds/{round_id}", response_model=s.RoundSummary)
def update_round(round_id: str, body: s.UpdateRoundRequest, db: Db, me: Me) -> s.RoundSummary:
    found = get_round(db, round_id)
    wanted = {
        "name": _name(body.name) if body.name is not None else None,
        "default_mode": body.default_mode,
        "recommended_interviewers": (
            _interviewers(body.recommended_interviewers)
            if body.recommended_interviewers is not None
            else None
        ),
        "show_previous_scores": body.show_previous_scores,
    }
    changed = {}
    for field, value in wanted.items():
        before = getattr(found, field)
        if value is not None and value != before:
            setattr(found, field, value)
            changed[field] = {
                "from": getattr(before, "value", before),
                "to": getattr(value, "value", value),
            }
    if changed:
        audit(db, me, "round.updated", "interview_round", found.id, **changed)
        db.commit()
    return views.round_summary(found)


@router.delete("/rounds/{round_id}", status_code=204)
def delete_round(round_id: str, db: Db, me: Me) -> Response:
    found = get_round(db, round_id)
    posting = found.posting
    if len(posting.rounds) == 1:
        raise conflict("공고에는 차수가 하나 이상 있어야 합니다.")
    if _locked(found):
        raise conflict(f"{found.label}에 면접이나 결정이 있어 지울 수 없습니다.")
    audit(
        db,
        me,
        "round.deleted",
        "job_posting",
        posting.id,
        round_id=found.id,
        position=found.position,
        name=found.name,
    )
    posting.rounds.remove(found)
    db.delete(found)
    db.flush()
    _place(db, rounds_of(posting))
    db.commit()
    return Response(status_code=204)


@router.put("/postings/{posting_id}/rounds/order", response_model=list[s.RoundSummary])
def reorder_rounds(
    posting_id: str, body: s.ReorderRoundsRequest, db: Db, me: Me
) -> list[s.RoundSummary]:
    posting = _posting(db, posting_id)
    by_id = {r.id: r for r in posting.rounds}
    if sorted(body.round_ids) != sorted(by_id) or len(set(body.round_ids)) != len(by_id):
        raise invalid("round_ids", "공고의 차수를 모두 한 번씩 보내야 합니다.")
    ordered = [by_id[i] for i in body.round_ids]
    moved = [r for i, r in enumerate(ordered, start=1) if r.position != i]
    stuck = [r for r in moved if _locked(r)]
    if stuck:
        raise conflict(f"{stuck[0].label}에 면접이나 결정이 있어 순서를 바꿀 수 없습니다.")
    if moved:
        _place(db, ordered)
        audit(db, me, "round.reordered", "job_posting", posting.id, round_ids=body.round_ids)
        db.commit()
    return [views.round_summary(r) for r in rounds_of(posting)]


# --- competency sets of a round --------------------------------------------------------------


@router.get("/rounds/{round_id}/competency-sets", response_model=list[s.CompetencySet])
def round_sets(round_id: str, db: Db) -> list[s.CompetencySet]:
    return [s.CompetencySet.model_validate(x) for x in get_round(db, round_id).competency_sets]


@router.post("/rounds/{round_id}/competency-sets", response_model=s.CompetencySet, status_code=201)
def create_round_set(
    round_id: str, body: s.CompetenciesBody, db: Db, me: Me
) -> s.CompetencySet:
    """A new draft version. It copies the preset questions of the round's approved version whose
    competency it keeps, so they can be edited before approval."""
    found = get_round(db, round_id)
    latest = latest_set(found)
    approved = approved_set(found)
    keep = {c.name for c in body.competencies}
    # Read before the new set joins the round's collections, or the lazy load autoflushes it half-built.
    carried = [q for q in approved.preset_questions if q.competency in keep] if approved else []
    created = CompetencySet(
        posting=found.posting,
        round=found,
        version=(latest.version if latest else 0) + 1,
        competencies=[c.model_dump() for c in body.competencies],
    )
    for position, q in enumerate(carried, start=1):
        created.preset_questions.append(
            PresetQuestion(
                position=position, competency=q.competency, question=q.question, intent=q.intent
            )
        )
    db.add(created)
    db.flush()
    audit(db, me, "competency_set.created", "competency_set", created.id, round_id=found.id)
    db.commit()
    return s.CompetencySet.model_validate(created)


@router.post(
    "/rounds/{round_id}/competency-sets/generate",
    response_model=s.CompetencySet,
    status_code=201,
)
async def generate_round_set(round_id: str, db: Db, runtime: RuntimeDep) -> s.CompetencySet:
    found = get_round(db, round_id)
    try:
        drafted = await draft_competency_set(db, runtime.ai, found, runtime.retrieval)
    finally:
        db.commit()  # the AI call's audit row stays even when the draft is unusable
    return s.CompetencySet.model_validate(drafted)


# --- preset questions ------------------------------------------------------------------------


def _draft_only(competency_set: CompetencySet) -> None:
    if competency_set.approved_at is not None:
        raise conflict("확정된 버전의 사전 질문은 바꿀 수 없습니다. 새 버전을 만드세요.")


def _question(db: Db, question_id: str) -> PresetQuestion:
    found = db.get(PresetQuestion, question_id)
    if found is None or found.competency_set is None:
        raise not_found("사전 질문")
    return found


def _validated(competency_set: CompetencySet, body: s.PresetQuestionBody) -> tuple[str, str, str]:
    names = [c["name"] for c in competency_set.competencies]
    if body.competency not in names:
        raise invalid("competency", f"'{body.competency}'은(는) 이 버전의 역량이 아닙니다.")
    question = body.question.strip()
    if not question:
        raise invalid("question", "질문을 입력하세요.")
    return body.competency, question, body.intent.strip()[:200]


@router.get("/competency-sets/{set_id}/preset-questions", response_model=list[s.PresetQuestion])
def preset_questions(set_id: str, db: Db) -> list[s.PresetQuestion]:
    return [views.preset_view(db, q) for q in _set(db, set_id).preset_questions]


@router.post(
    "/competency-sets/{set_id}/preset-questions",
    response_model=s.PresetQuestion,
    status_code=201,
)
def create_preset_question(
    set_id: str, body: s.PresetQuestionBody, db: Db, me: Me
) -> s.PresetQuestion:
    found = _set(db, set_id)
    _draft_only(found)
    competency, question, intent = _validated(found, body)
    created = PresetQuestion(
        position=max((q.position for q in found.preset_questions), default=0) + 1,
        competency=competency,
        question=question,
        intent=intent,
    )
    found.preset_questions.append(created)
    db.flush()
    audit(db, me, "preset_question.created", "competency_set", found.id, question_id=created.id)
    db.commit()
    return views.preset_view(db, created)


@router.post(
    "/competency-sets/{set_id}/preset-questions/generate",
    response_model=list[s.PresetQuestion],
)
async def generate_preset_questions(
    set_id: str, db: Db, runtime: RuntimeDep
) -> list[s.PresetQuestion]:
    """AI adds questions to the draft; returns the draft's whole list."""
    found = _set(db, set_id)
    _draft_only(found)
    if not found.competencies:
        raise invalid("competencies", "역량을 먼저 정하세요.")
    try:
        await draft_preset_questions(db, runtime.ai, found)
    finally:
        db.commit()
    return [views.preset_view(db, q) for q in found.preset_questions]


@router.put("/preset-questions/{question_id}", response_model=s.PresetQuestion)
def update_preset_question(
    question_id: str, body: s.PresetQuestionBody, db: Db, me: Me
) -> s.PresetQuestion:
    found = _question(db, question_id)
    assert found.competency_set is not None
    _draft_only(found.competency_set)
    found.competency, found.question, found.intent = _validated(found.competency_set, body)
    audit(db, me, "preset_question.updated", "competency_set", found.competency_set_id, question_id=found.id)
    db.commit()
    return views.preset_view(db, found)


@router.delete("/preset-questions/{question_id}", status_code=204)
def delete_preset_question(question_id: str, db: Db, me: Me) -> Response:
    found = _question(db, question_id)
    competency_set = found.competency_set
    assert competency_set is not None
    _draft_only(competency_set)
    audit(db, me, "preset_question.deleted", "competency_set", competency_set.id, question_id=found.id)
    competency_set.preset_questions.remove(found)
    db.flush()
    rest = sorted(competency_set.preset_questions, key=lambda q: q.position)
    for i, q in enumerate(rest, start=1):
        q.position = -i
    db.flush()
    for i, q in enumerate(rest, start=1):
        q.position = i
    db.commit()
    return Response(status_code=204)

