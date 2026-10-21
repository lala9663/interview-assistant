"""Job postings, competency dictionaries, candidates, applications, screening results."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from interview_assistant.models.base import Base, IdMixin, TimestampMixin, enum_column

if TYPE_CHECKING:
    from interview_assistant.models.interview import InterviewSession


class PostingStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    closed = "closed"


class ScreeningStatus(str, enum.Enum):
    passed = "passed"
    hold = "hold"
    rejected = "rejected"


class JobPosting(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_postings"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_family: Mapped[str] = mapped_column(String(100), nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PostingStatus] = mapped_column(
        enum_column(PostingStatus), default=PostingStatus.draft, nullable=False
    )

    competency_sets: Mapped[list[CompetencySet]] = relationship(
        back_populates="posting",
        cascade="all, delete-orphan",
        order_by="CompetencySet.version",
    )
    applications: Mapped[list[Application]] = relationship(back_populates="posting")


class CompetencySet(IdMixin, TimestampMixin, Base):
    """One version of the competency dictionary for a posting.

    `competencies` is a list of {name, description, bars: {"1": ..., "5": ...}}.
    """

    __tablename__ = "competency_sets"
    __table_args__ = (UniqueConstraint("posting_id", "version", name="uq_competency_sets_posting_version"),)

    posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    competencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    posting: Mapped[JobPosting] = relationship(back_populates="competency_sets")


class Candidate(IdMixin, TimestampMixin, Base):
    """A person. Identity lives only in `encrypted_identity`; everything else uses `pseudonym`."""

    __tablename__ = "candidates"

    pseudonym: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    encrypted_identity: Mapped[str | None] = mapped_column(Text)
    consent_recording: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    applications: Mapped[list[Application]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "posting_id", name="uq_applications_candidate_posting"),
    )

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    source_file_uri: Mapped[str | None] = mapped_column(String(500))
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    posting: Mapped[JobPosting] = relationship(back_populates="applications")
    screening: Mapped[Screening | None] = relationship(
        back_populates="application", cascade="all, delete-orphan", uselist=False
    )
    sessions: Mapped[list[InterviewSession]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class Screening(IdMixin, TimestampMixin, Base):
    __tablename__ = "screenings"
    __table_args__ = (
        CheckConstraint("fit_score >= 0 AND fit_score <= 100", name="fit_score_range"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ScreeningStatus] = mapped_column(enum_column(ScreeningStatus), nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    application: Mapped[Application] = relationship(back_populates="screening")
