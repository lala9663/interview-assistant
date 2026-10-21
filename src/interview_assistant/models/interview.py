"""Interviewers, sessions, Q&A items, scores, notes, availability."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
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
from interview_assistant.models.recruiting import Application


class SessionMode(str, enum.Enum):
    onsite = "onsite"
    remote = "remote"


class SessionStatus(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class InterviewerRole(str, enum.Enum):
    lead = "lead"
    panel = "panel"


class QuestionSource(str, enum.Enum):
    preset = "preset"
    ai_suggested = "ai_suggested"
    interviewer = "interviewer"


class EvaluatorType(str, enum.Enum):
    ai = "ai"
    interviewer = "interviewer"


class AvailabilitySource(str, enum.Enum):
    manual = "manual"
    calendar = "calendar"


class Interviewer(IdMixin, TimestampMixin, Base):
    __tablename__ = "interviewers"

    employee_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_family: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))

    availabilities: Mapped[list[Availability]] = relationship(
        back_populates="interviewer", cascade="all, delete-orphan"
    )
    session_links: Mapped[list[SessionInterviewer]] = relationship(back_populates="interviewer")


class InterviewSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[SessionMode] = mapped_column(enum_column(SessionMode), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        enum_column(SessionStatus), default=SessionStatus.scheduled, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_uri: Mapped[str | None] = mapped_column(String(500))

    application: Mapped[Application] = relationship(back_populates="sessions")
    interviewers: Mapped[list[SessionInterviewer]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    qa_items: Mapped[list[QAItem]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="QAItem.seq"
    )
    notes: Mapped[list[CandidateNote]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionInterviewer(Base):
    __tablename__ = "session_interviewers"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    interviewer_id: Mapped[str] = mapped_column(ForeignKey("interviewers.id"), primary_key=True)
    role: Mapped[InterviewerRole] = mapped_column(
        enum_column(InterviewerRole), default=InterviewerRole.panel, nullable=False
    )

    session: Mapped[InterviewSession] = relationship(back_populates="interviewers")
    interviewer: Mapped[Interviewer] = relationship(back_populates="session_links")


class QAItem(IdMixin, TimestampMixin, Base):
    """One question and its answer. `answer_text` is raw; `answer_deidentified` is what LLMs see."""

    __tablename__ = "qa_items"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_qa_items_session_seq"),)

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_source: Mapped[QuestionSource] = mapped_column(
        enum_column(QuestionSource), nullable=False
    )
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_deidentified: Mapped[str | None] = mapped_column(Text)
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="qa_items")
    scores: Mapped[list[Score]] = relationship(
        back_populates="qa_item", cascade="all, delete-orphan"
    )


class Score(IdMixin, TimestampMixin, Base):
    """A 1-5 competency score for one answer. AI scores must cite evidence."""

    __tablename__ = "scores"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="score_range"),
        CheckConstraint(
            "evaluator_type <> 'ai' OR evidence IS NOT NULL", name="ai_requires_evidence"
        ),
    )

    qa_item_id: Mapped[str] = mapped_column(
        ForeignKey("qa_items.id", ondelete="CASCADE"), nullable=False
    )
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evaluator_type: Mapped[EvaluatorType] = mapped_column(enum_column(EvaluatorType), nullable=False)
    evaluator_id: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    qa_item: Mapped[QAItem] = relationship(back_populates="scores")


class CandidateNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_notes"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("interviewers.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    session: Mapped[InterviewSession] = relationship(back_populates="notes")
    author: Mapped[Interviewer] = relationship()


class Availability(IdMixin, TimestampMixin, Base):
    __tablename__ = "availabilities"
    __table_args__ = (CheckConstraint("end_at > start_at", name="end_after_start"),)

    interviewer_id: Mapped[str] = mapped_column(
        ForeignKey("interviewers.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[AvailabilitySource] = mapped_column(
        enum_column(AvailabilitySource), default=AvailabilitySource.manual, nullable=False
    )

    interviewer: Mapped[Interviewer] = relationship(back_populates="availabilities")
