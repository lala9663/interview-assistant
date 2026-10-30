"""서류 선별: structure a de-identified document into a profile, then assess it against the JD and
the approved competency dictionary. Two calls on the `screening` model role.

The initial screening status is `hold` whatever the model recommends: 통과·보류·탈락 is a human
decision (PATCH /api/screenings/{id}); the recommendation is kept apart as reference.

screening-v0.5 assesses requirement by requirement (필수/우대 → 충족/미충족/확인 필요 with evidence
and where it is in the document) and lists what to check in the interview. Everything a person
reads is plain Korean: the prompt keeps JSON keys out of the model's sight and `humanize` turns
any field name that still slips into the text back into a Korean word.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
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
KIND_LABEL = {"required": "필수", "preferred": "우대"}
VERDICT_LABEL = {"met": "충족", "unmet": "미충족", "unclear": "확인 필요"}

# Profile and schema field names a model may still echo, and what a person calls them.
_FIELD_WORDS = {
    "years_experience": "경력 연수",
    "fit_score": "적합도",
    "interview_checks": "면접 확인 사항",
    "competencies": "역량",
    "certifications": "자격증",
    "experience": "경력",
    "education": "학력",
    "highlights": "주요 성과",
    "projects": "프로젝트",
    "skills": "기술",
    "summary": "요약",
}
_SNAKE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(k for k in _FIELD_WORDS if "_" in k) + r")(?![A-Za-z0-9_])")
# A plain English field name counts only right before a Korean particle ("skills에", "competencies의").
_BARE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(k for k in _FIELD_WORDS if "_" not in k) + r")(?=[가-힣])")


def humanize(text: str) -> str:
    """Field names that slipped into model text, back in Korean ('years_experience 7.2' ->
    '경력 연수 7.2')."""
    text = _SNAKE.sub(lambda m: _FIELD_WORDS[m.group(1)], text)
    return _BARE.sub(lambda m: _FIELD_WORDS[m.group(1)], text).strip()


class RequirementCheck(BaseModel):
    kind: Literal["required", "preferred"]
    requirement: str
    verdict: Literal["met", "unmet", "unclear"]
    evidence: str = ""
    source: str = ""


class Assessment(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    summary: str
    requirements: list[RequirementCheck] = []
    recommendation: Literal["passed", "hold", "rejected"]
    interview_checks: list[str] = []

    @model_validator(mode="after")
    def _plain_korean(self) -> Assessment:
        self.summary = humanize(self.summary)
        for r in self.requirements:
            r.requirement, r.evidence, r.source = (
                humanize(r.requirement),
                humanize(r.evidence),
                humanize(r.source),
            )
        self.interview_checks = [humanize(c) for c in self.interview_checks if c.strip()]
        self.requirements = [r for r in self.requirements if r.requirement]
        return self

    def details(self) -> dict[str, Any]:
        """What Screening.assessment stores (the API's `assessment`)."""
        return {
            "summary": self.summary,
            "requirements": [r.model_dump() for r in self.requirements],
            "interview_checks": self.interview_checks,
        }

    def rationale(self) -> str:
        """Plain text for readers that predate `details` (the interview's candidate card, the
        agent): the summary, `+ ` met requirements, `- ` the rest and the points to check."""
        lines = [self.summary]
        for r in self.requirements:
            line = f"{KIND_LABEL[r.kind]} {VERDICT_LABEL[r.verdict]} · {r.requirement}"
            if r.evidence:
                line += f": {r.evidence}"
            lines.append(f"{'+' if r.verdict == 'met' else '-'} {line}")
        lines += [f"- 면접에서 확인: {c}" for c in self.interview_checks]
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
