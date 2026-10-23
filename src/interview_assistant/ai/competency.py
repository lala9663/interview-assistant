"""FR-02: draft a competency dictionary (competencies + 1-5 BARS) from the JD.

The draft becomes a new, unapproved version; people edit and approve it. The JD is company text,
so no candidate data is involved.
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
from interview_assistant.models import CompetencySet, JobPosting
from interview_assistant.models.base import new_id

_COMPETENCIES = TypeAdapter(list[Competency])


async def draft_competency_set(db: Session, ai: AiGateway, posting: JobPosting) -> CompetencySet:
    latest = posting.competency_sets[-1] if posting.competency_sets else None
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
                current=latest.competencies if latest else [],
            ),
            schema=COMPETENCY_SCHEMA,
            target_type="competency_set",
            target_id=set_id,
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
        version=(latest.version if latest else 0) + 1,
        competencies=[c.model_dump() for c in unique],
    )
    db.add(drafted)
    db.flush()
    return drafted
