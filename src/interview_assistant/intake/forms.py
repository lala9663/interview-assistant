"""채용 사이트 입력 칸: what an application form carries besides files.

학력, 경력, 자격, 보유 기술, 프로젝트 and 자기소개 항목 are already structured, so they become the
profile without a model call. They are de-identified first like any other text: every free-text
value goes through the de-identifier as one block of a synthetic document (`text_blocks`), and
the tokenised values are put back where they came from (`with_texts`).

Code values (degree, school status) and year-months are not free text and stay as sent.
"""

from __future__ import annotations

import enum
import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from interview_assistant.documents.normalize import normalize_text
from interview_assistant.documents.types import BlockKind, TextBlock
from interview_assistant.domain import CandidateProfile, Education, Experience, Project

YearMonth = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=3000)]


class Degree(str, enum.Enum):
    high_school = "high_school"
    associate = "associate"
    bachelor = "bachelor"
    master = "master"
    doctorate = "doctorate"


class SchoolStatus(str, enum.Enum):
    graduated = "graduated"
    expected = "expected"  # 졸업 예정
    enrolled = "enrolled"  # 재학
    completed = "completed"  # 수료
    left = "left"  # 중퇴


DEGREE_LABEL = {
    Degree.high_school: "고등학교",
    Degree.associate: "전문학사",
    Degree.bachelor: "학사",
    Degree.master: "석사",
    Degree.doctorate: "박사",
}
SCHOOL_STATUS_LABEL = {
    SchoolStatus.graduated: "졸업",
    SchoolStatus.expected: "졸업 예정",
    SchoolStatus.enrolled: "재학",
    SchoolStatus.completed: "수료",
    SchoolStatus.left: "중퇴",
}


class FormModel(BaseModel):
    # Extra keys are kept here only so the channel can name and drop them (data minimisation):
    # intake.site strips them before anything is stored.
    model_config = ConfigDict(extra="allow")


class EducationField(FormModel):
    school: Name
    degree: Degree
    major: ShortText = ""
    start: YearMonth | None = None
    end: YearMonth | None = None
    status: SchoolStatus = SchoolStatus.graduated


class CareerField(FormModel):
    company: Name
    department: ShortText = ""
    title: ShortText = ""  # 직무·직책
    start: YearMonth
    end: YearMonth | None = None  # null: 재직 중
    description: LongText = ""  # 담당 업무·성과

    @model_validator(mode="after")
    def _ordered(self) -> CareerField:
        if self.end is not None and self.end < self.start:
            raise ValueError("경력 종료 월이 시작 월보다 빠릅니다.")
        return self


class CertificationField(FormModel):
    name: Name  # 자격증, 어학 시험
    issuer: ShortText = ""
    acquired: YearMonth | None = None
    score: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] = ""


class ProjectField(FormModel):
    name: Name
    role: ShortText = ""
    description: LongText = ""
    tech: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=20
    )


class EssayField(FormModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class FormFields(FormModel):
    education: list[EducationField] = Field(default_factory=list, max_length=10)
    career: list[CareerField] = Field(default_factory=list, max_length=30)
    certifications: list[CertificationField] = Field(default_factory=list, max_length=30)
    skills: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=50
    )
    projects: list[ProjectField] = Field(default_factory=list, max_length=20)
    essays: list[EssayField] = Field(default_factory=list, max_length=10)

    @property
    def has_profile(self) -> bool:
        """Structured enough to be the profile; essays alone go to the model like a document."""
        return bool(self.education or self.career or self.certifications or self.skills or self.projects)

    @property
    def is_empty(self) -> bool:
        return not (self.has_profile or self.essays)


# --- de-identification ----------------------------------------------------------------------

# (list, key) -> block kind and a fixed label ("{n}" is the entry number). Labels never carry
# form content.
_SLOTS: dict[tuple[str, str], tuple[BlockKind, str]] = {
    ("education", "school"): (BlockKind.table, "학력 {n} 학교"),
    ("education", "major"): (BlockKind.table, "학력 {n} 전공"),
    ("career", "company"): (BlockKind.table, "경력 {n} 회사"),
    ("career", "department"): (BlockKind.table, "경력 {n} 부서"),
    ("career", "title"): (BlockKind.table, "경력 {n} 직무"),
    ("career", "description"): (BlockKind.body, "경력 {n} 담당 업무"),
    ("certifications", "name"): (BlockKind.table, "자격 {n}"),
    ("certifications", "issuer"): (BlockKind.table, "자격 {n} 발급 기관"),
    ("certifications", "score"): (BlockKind.table, "자격 {n} 점수"),
    ("projects", "name"): (BlockKind.table, "프로젝트 {n} 이름"),
    ("projects", "role"): (BlockKind.table, "프로젝트 {n} 역할"),
    ("projects", "description"): (BlockKind.body, "프로젝트 {n} 설명"),
    ("projects", "tech"): (BlockKind.table, "프로젝트 {n} 기술"),
    ("essays", "question"): (BlockKind.body, "자기소개 {n} 질문"),
    ("essays", "answer"): (BlockKind.body, "자기소개 {n} 답변"),
}

FieldPath = tuple[Any, ...]


def text_blocks(fields: FormFields) -> list[tuple[FieldPath, TextBlock]]:
    """Every free-text value as (where it sits, a labelled block). Empty values are left out."""
    data = fields.model_dump(mode="json", exclude_unset=False)
    out: list[tuple[FieldPath, TextBlock]] = []
    for key, items in data.items():
        if key == "skills":
            for i, skill in enumerate(items):
                out.append((("skills", i), TextBlock(BlockKind.table, "보유 기술", normalize_text(skill))))
            continue
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            for name, value in item.items():
                slot = _SLOTS.get((key, name))
                if slot is None:
                    continue
                kind, label = slot
                values = value if isinstance(value, list) else [value]
                for j, text in enumerate(values):
                    text = normalize_text(text or "")
                    if text:
                        path = (key, i, name, j) if isinstance(value, list) else (key, i, name)
                        out.append((path, TextBlock(kind, label.format(n=i + 1), text)))
    return out


def with_texts(fields: FormFields, texts: dict[FieldPath, str]) -> FormFields:
    """The same fields with the values at `texts`' paths replaced (by their tokenised text)."""
    data = fields.model_dump(mode="json")
    for path, text in texts.items():
        node: Any = data
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = text
    return FormFields.model_validate(data)


# --- profile --------------------------------------------------------------------------------


def _month_index(value: str) -> int:
    year, month = value.split("-")
    return int(year) * 12 + int(month) - 1


def career_months(career: list[CareerField], today: date | None = None) -> int:
    """Months worked, overlapping jobs counted once. An open end is this month (재직 중)."""
    today = today or date.today()
    now = today.year * 12 + today.month  # exclusive end of this month
    spans = sorted(
        (_month_index(c.start), _month_index(c.end) + 1 if c.end else now) for c in career
    )
    total, cur_start, cur_end = 0, None, None
    for start, end in spans:
        if end <= start:
            continue
        if cur_end is None or start > cur_end:
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None:
        total += cur_end - cur_start
    return total


def _period(start: str, end: str | None) -> str:
    return f"{start.replace('-', '.')} – {end.replace('-', '.') if end else '현재'}"


def _sentences(text: str, limit: int = 3) -> list[str]:
    parts = [p.strip(" -•·\t") for p in re.split(r"(?<=[.?!])\s+|\n+", text) if p.strip()]
    return [p[:200] for p in parts[:limit]]


def build_profile(fields: FormFields, today: date | None = None) -> CandidateProfile:
    """The profile straight from (de-identified) form fields. The summary is a rule, not a model."""
    career = sorted(fields.career, key=lambda c: c.start, reverse=True)
    years = min(60.0, round(career_months(fields.career, today) / 12, 1))
    experience = [
        Experience(
            company=c.company,
            role=c.title or c.department,
            period=_period(c.start, c.end),
            highlights=_sentences(c.description),
        )
        for c in career[:8]
    ]
    education = [
        Education(
            school=e.school,
            degree=DEGREE_LABEL[e.degree]
            + ("" if e.status is SchoolStatus.graduated else f" ({SCHOOL_STATUS_LABEL[e.status]})"),
            major=e.major,
        )
        for e in fields.education
    ]
    projects = [
        Project(name=p.name, description=p.description[:300], tech=list(p.tech)) for p in fields.projects
    ]
    skills = list(dict.fromkeys([*fields.skills, *(t for p in fields.projects for t in p.tech)]))
    certifications = [" ".join(x for x in (c.name, c.score) if x) for c in fields.certifications]

    role = next((e.role for e in experience if e.role), "")
    head = f"{role} {years:g}년".strip() if years else (role or "경력 없음")
    summary = f"{head}. 주요 기술: {', '.join(skills[:4])}." if skills else f"{head}."
    return CandidateProfile(
        summary=summary,
        years_experience=years,
        skills=skills,
        experience=experience,
        education=education,
        projects=projects,
        certifications=certifications,
    )
