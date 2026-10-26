"""FR-01·03: structure a de-identified document into a profile, then assess it against the JD and
the approved competency dictionary. Two calls on the `screening` model role.

The initial screening status is `hold` whatever the model recommends: 통과·보류·탈락 is a human
decision (PATCH /api/screenings/{id}); the recommendation is written into the rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from interview_assistant.ai import AiOutputInvalid
from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.prompts import (
    PROFILE_PROMPT,
    PROFILE_SCHEMA,
    PROFILE_SYSTEM,
    SCREENING_PROMPT,
    SCREENING_SCHEMA,
    SCREENING_SYSTEM,
    profile_prompt,
    screening_prompt,
)
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.domain import CandidateProfile
from interview_assistant.models import JobPosting

RECOMMENDATION_LABEL = {"passed": "통과", "hold": "보류", "rejected": "탈락"}


class Assessment(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    summary: str
    strengths: list[str] = []
    concerns: list[str] = []
    recommendation: Literal["passed", "hold", "rejected"]

    def rationale(self) -> str:
        """Line format the UI reads: summary, `+ ` strengths, `- ` concerns."""
        head = f"{self.summary.strip()} (AI 권고: {RECOMMENDATION_LABEL[self.recommendation]})"
        lines = [head, *(f"+ {s.strip()}" for s in self.strengths if s.strip())]
        lines += [f"- {c.strip()}" for c in self.concerns if c.strip()]
        return "\n".join(lines)


@dataclass
class ScreeningOutcome:
    profile: CandidateProfile
    assessment: Assessment
    model: str


def _common(application_id: str, known: KnownIdentity | None, *texts: str) -> dict[str, Any]:
    return dict(
        role="screening",
        candidate_texts=list(texts),
        known=known,
        target_type="application",
        target_id=application_id,
    )


async def structure_profile(
    db: Session,
    ai: AiGateway,
    *,
    application_id: str,
    document_text: str,
    known: KnownIdentity | None,
) -> CandidateProfile:
    """Profile from free-form documents (uploads, attachments without site form fields)."""
    result = await ai.generate(
        db,
        AiCall(
            action="profile.extracted",
            prompt_version=PROFILE_PROMPT,
            system=PROFILE_SYSTEM,
            prompt=profile_prompt(document_text=document_text),
            schema=PROFILE_SCHEMA,
            **_common(application_id, known, document_text),
        ),
    )
    try:
        return CandidateProfile.model_validate(result.structured or {})
    except ValidationError as exc:
        raise AiOutputInvalid("서류 구조화 결과가 형식에 맞지 않습니다.") from exc


async def assess_profile(
    db: Session,
    ai: AiGateway,
    *,
    posting: JobPosting,
    competencies: list[dict[str, Any]],
    application_id: str,
    profile: CandidateProfile,
    document_text: str,
    known: KnownIdentity | None,
) -> tuple[Assessment, str]:
    """Fit against the JD and approved competencies. Returns the assessment and the model name."""
    profile_json = profile.model_dump()
    assessed = await ai.generate(
        db,
        AiCall(
            action="screening.assessed",
            prompt_version=SCREENING_PROMPT,
            system=SCREENING_SYSTEM,
            prompt=screening_prompt(
                title=posting.title,
                jd_text=posting.jd_text,
                competencies=competencies,
                profile=profile_json,
                document_text=document_text,
            ),
            schema=SCREENING_SCHEMA,
            **_common(
                application_id, known, document_text, json.dumps(profile_json, ensure_ascii=False)
            ),
        ),
    )
    try:
        return Assessment.model_validate(assessed.structured or {}), assessed.model
    except ValidationError as exc:
        raise AiOutputInvalid("서류 선별 결과가 형식에 맞지 않습니다.") from exc


async def screen_document(
    db: Session,
    ai: AiGateway,
    *,
    posting: JobPosting,
    competencies: list[dict[str, Any]],
    application_id: str,
    document_text: str,
    known: KnownIdentity | None,
) -> ScreeningOutcome:
    """Both calls in one go. The intake service calls them one by one so it can commit the audit
    rows in between (no write transaction stays open across a model call)."""
    profile = await structure_profile(
        db, ai, application_id=application_id, document_text=document_text, known=known
    )
    assessment, model = await assess_profile(
        db,
        ai,
        posting=posting,
        competencies=competencies,
        application_id=application_id,
        profile=profile,
        document_text=document_text,
        known=known,
    )
    return ScreeningOutcome(profile=profile, assessment=assessment, model=model)
