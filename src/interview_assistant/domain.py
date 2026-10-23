"""Shapes of the JSON columns, shared by the API and the AI tasks that produce them.

`CompetencySet.competencies` is a list of `Competency`; `Application.profile` is a
`CandidateProfile` built from the de-identified document (schools and companies are tokens).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

BARS_LEVELS = ("1", "2", "3", "4", "5")


class Competency(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(max_length=100)
    description: str
    bars: dict[str, str]

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError("value_error", "역량 이름이 비어 있습니다.")
        return v.strip()

    @field_validator("bars")
    @classmethod
    def _five_levels(cls, v: dict[str, str]) -> dict[str, str]:
        missing = [level for level in BARS_LEVELS if not isinstance(v.get(level), str)]
        if missing:
            raise PydanticCustomError("value_error", "역량마다 1~5점 기준이 모두 필요합니다.")
        return {level: v[level] for level in BARS_LEVELS}


class Experience(BaseModel):
    company: str = ""
    role: str = ""
    period: str = ""
    highlights: list[str] = []


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""


class Project(BaseModel):
    name: str = ""
    description: str = ""
    tech: list[str] = []


class CandidateProfile(BaseModel):
    summary: str = ""
    years_experience: float = Field(default=0, ge=0, le=60)
    skills: list[str] = []
    experience: list[Experience] = []
    education: list[Education] = []
    projects: list[Project] = []
    certifications: list[str] = []
