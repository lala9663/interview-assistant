"""FR-02: draft a competency dictionary (competencies + 1-5 BARS) for one interview round.

The draft becomes a new, unapproved version of the round; people edit and approve it. The model
sees the JD, the round's name (what it is for) and the competencies earlier rounds already look at,
so a later round (임원 면접) does not just repeat round 1. All company text, no candidate data.
"""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.prompts import (
    COMPETENCY_PROMPT,
    COMPETENCY_SCHEMA,
    COMPETENCY_SYSTEM,
    competency_prompt,
)
from interview_assistant.domain import Competency
from interview_assistant.interviews import approved_set, full_name, latest_set, rounds_of
from interview_assistant.models import CompetencySet, InterviewRound
from interview_assistant.models.base import new_id

_COMPETENCIES = TypeAdapter(list[Competency])


async def draft_competency_set(
    db: Session, ai: AiGateway, round_: InterviewRound
) -> CompetencySet:
    posting = round_.posting
    latest = latest_set(round_)
    earlier = [
        c["name"]
        for r in rounds_of(posting)
        if r.position < round_.position and (s := approved_set(r)) is not None
        for c in s.competencies
    ]
    set_id = new_id()
    result = await ai.generate(
        db,
        AiCall(
            action="competency_set.generated",
            prompt_version=COMPETENCY_PROMPT,
            system=COMPETENCY_SYSTEM,
            prompt=competency_prompt(
                title=posting.title,
                job_family=posting.job_family,
                jd_text=posting.jd_text,
                round_name=full_name(round_),
                earlier_rounds=list(dict.fromkeys(earlier)),
                current=latest.competencies if latest else [],
            ),
            schema=COMPETENCY_SCHEMA,
            target_type="competency_set",
            target_id=set_id,
            details={"round_id": round_.id},
        ),
    )
    try:
        competencies = _COMPETENCIES.validate_python((result.structured or {}).get("competencies"))
    except ValidationError as exc:
        raise AiOutputInvalid("역량 사전 초안이 형식에 맞지 않습니다.") from exc
    unique = list({c.name: c for c in competencies}.values())
    if not unique:
        raise AiOutputInvalid("역량 사전 초안에 역량이 없습니다.")
    drafted = CompetencySet(
        id=set_id,
        posting=posting,
        round=round_,
        version=(latest.version if latest else 0) + 1,
        competencies=[c.model_dump() for c in unique],
    )
    db.add(drafted)
    db.flush()
    return drafted
