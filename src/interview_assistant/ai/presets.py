"""사전 질문 (FR-06) drafts, two kinds:

- `draft_preset_questions`: questions for a round's draft competency version, two per competency.
  The model sees the questions earlier rounds already use and those the version already has, so a
  later round does not repeat them. Company text only, no candidate data.
- `draft_carryover_questions`: 이어 질문 for one candidate's session in round 2 or later, built on
  the earlier rounds' de-identified Q&A and points to check. Each must quote the earlier answer
  it builds on verbatim (`ground`) and must not repeat an earlier question; the guard checks every
  earlier text that goes into the prompt.

Neither turns anything into a question asked: the interviewer picks.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.followups import ground
from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.prompts import (
    CARRYOVER_PROMPT,
    CARRYOVER_SCHEMA,
    CARRYOVER_SYSTEM,
    PRESET_PROMPT,
    PRESET_SCHEMA,
    PRESET_SYSTEM,
    carryover_prompt,
    preset_prompt,
)
from interview_assistant.deid.service import DeidService
from interview_assistant.interviews import (
    approved_set,
    earlier_check_points,
    earlier_sessions,
    full_name,
    rounds_of,
    session_competency_set,
)
from interview_assistant.models import CompetencySet, InterviewSession, PresetQuestion, QAItem

PER_COMPETENCY = 2
MAX_CARRYOVER = 3


class _Draft(BaseModel):
    competency: str
    question: str
    intent: str = ""


class _Drafts(BaseModel):
    questions: list[_Draft]


class _Carryover(_Draft):
    based_on: str
    grounding: str
    rationale: str = ""


class _Carryovers(BaseModel):
    questions: list[_Carryover]


def _key(text: str) -> str:
    return re.sub(r"[\s\W]+", "", text)


async def draft_preset_questions(
    db: Session, ai: AiGateway, competency_set: CompetencySet
) -> list[PresetQuestion]:
    """Adds AI questions to a draft version; returns the ones added."""
    round_ = competency_set.round
    earlier = [
        q.question
        for r in rounds_of(round_.posting)
        if r.position < round_.position and (s := approved_set(r)) is not None
        for q in s.preset_questions
    ]
    existing = [q.question for q in competency_set.preset_questions]
    result = await ai.generate(
        db,
        AiCall(
            action="preset_question.generated",
            prompt_version=PRESET_PROMPT,
            system=PRESET_SYSTEM,
            prompt=preset_prompt(
                title=round_.posting.title,
                round_name=full_name(round_),
                competencies=competency_set.competencies,
                earlier_questions=earlier,
                existing_questions=existing,
            ),
            schema=PRESET_SCHEMA,
            target_type="competency_set",
            target_id=competency_set.id,
        ),
    )
    try:
        drafts = _Drafts.model_validate(result.structured or {}).questions
    except ValidationError as exc:
        raise AiOutputInvalid("사전 질문 초안이 형식에 맞지 않습니다.") from exc
    names = [c["name"] for c in competency_set.competencies]
    seen = {_key(q) for q in [*earlier, *existing]}
    per: dict[str, int] = {}
    added = []
    position = max((q.position for q in competency_set.preset_questions), default=0)
    for draft in drafts:
        question = draft.question.strip()
        if draft.competency not in names or not question or _key(question) in seen:
            continue
        if per.get(draft.competency, 0) >= PER_COMPETENCY:
            continue
        per[draft.competency] = per.get(draft.competency, 0) + 1
        seen.add(_key(question))
        position += 1
        row = PresetQuestion(
            position=position,
            competency=draft.competency,
            question=question,
            intent=draft.intent.strip()[:200],
            model=result.model,
            prompt_version=PRESET_PROMPT,
        )
        competency_set.preset_questions.append(row)
        added.append(row)
    if not added:
        raise AiOutputInvalid("새로 더할 사전 질문을 만들지 못했습니다.")
    db.flush()
    return added


async def draft_carryover_questions(
    db: Session, ai: AiGateway, deid: DeidService, session: InterviewSession
) -> list[PresetQuestion]:
    """Replaces the session's carry-over questions not asked yet; returns the session's list."""
    earlier_qa: list[tuple[str, QAItem]] = []
    for earlier in earlier_sessions(session):
        for qa in earlier.qa_items:
            if qa.answer_deidentified:
                earlier_qa.append((f"{earlier.round.label}-Q{qa.seq}", qa))
    if not earlier_qa:
        raise AiOutputInvalid("이전 차수에 답변이 없어 이어 질문을 만들 수 없습니다.")
    points = [p.text for p in earlier_check_points(session)]
    competency_set = session_competency_set(db, session)
    competencies: list[dict[str, Any]] = competency_set.competencies if competency_set else []
    by_ref = dict(earlier_qa)
    texts = [t for _, qa in earlier_qa for t in (qa.question, qa.answer_deidentified or "")]
    result = await ai.generate(
        db,
        AiCall(
            action="carryover.generated",
            prompt_version=CARRYOVER_PROMPT,
            system=CARRYOVER_SYSTEM,
            prompt=carryover_prompt(
                round_name=full_name(session.round),
                competencies=competencies,
                earlier=[
                    (ref, qa.session.round.label, qa.question, qa.answer_deidentified or "")
                    for ref, qa in earlier_qa
                ],
                check_points=points,
            ),
            schema=CARRYOVER_SCHEMA,
            candidate_texts=[*texts, *points],
            known=deid.identity(session.application.candidate),
            target_type="interview_session",
            target_id=session.id,
            details={"earlier_round_answers": len(earlier_qa)},
        ),
    )
    try:
        drafts = _Carryovers.model_validate(result.structured or {}).questions
    except ValidationError as exc:
        raise AiOutputInvalid("이어 질문이 형식에 맞지 않습니다.") from exc

    asked = {q.preset_question_id for q in session.qa_items if q.preset_question_id}
    kept = [q for q in session.carryover_questions if q.id in asked]
    for q in list(session.carryover_questions):
        if q.id not in asked:
            session.carryover_questions.remove(q)
    db.flush()

    names = [c["name"] for c in competencies]
    seen = {_key(qa.question) for _, qa in earlier_qa} | {_key(q.question) for q in kept}
    position = max((q.position for q in kept), default=0)
    for draft in drafts:
        source = by_ref.get(draft.based_on.strip())
        question = draft.question.strip()
        if source is None or not question or _key(question) in seen:
            continue
        quote = ground(draft.grounding, source.answer_deidentified or "")
        if not quote:
            continue
        seen.add(_key(question))
        position += 1
        session.carryover_questions.append(
            PresetQuestion(
                position=position,
                competency=draft.competency if draft.competency in names or not names else names[0],
                question=question,
                intent=draft.intent.strip()[:200],
                based_on_qa_item_id=source.id,
                grounding=quote,
                rationale=draft.rationale.strip(),
                model=result.model,
                prompt_version=CARRYOVER_PROMPT,
            )
        )
        if len(session.carryover_questions) - len(kept) >= MAX_CARRYOVER:
            break
    db.flush()
    return list(session.carryover_questions)
