"""Interviewers, sessions, Q&A items, scores, notes, availability, follow-ups, transcripts."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from interview_assistant.models.base import Base, IdMixin, TimestampMixin, enum_column
from interview_assistant.models.recruiting import (
    Application,
    CompetencySet,
    PresetQuestion,
)


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


class AiScoringStatus(str, enum.Enum):
    not_started = "not_started"
    running = "running"
    completed = "completed"
    failed = "failed"


class Speaker(str, enum.Enum):
    interviewer = "interviewer"
    candidate = "candidate"


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
    # The approved competency set in force when the session started. Preset questions, scoring
    # and the evaluation keep using it even if a newer version is approved later.
    competency_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("competency_sets.id", ondelete="SET NULL")
    )
    # AI scoring runs after the session ends (FR-07); the UI polls while it is running.
    ai_scoring_status: Mapped[AiScoringStatus] = mapped_column(
        enum_column(AiScoringStatus), default=AiScoringStatus.not_started, nullable=False
    )
    ai_scoring_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_scoring_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(back_populates="sessions")
    competency_set: Mapped[CompetencySet | None] = relationship()
    interviewers: Mapped[list[SessionInterviewer]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    qa_items: Mapped[list[QAItem]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="QAItem.seq"
    )
    notes: Mapped[list[CandidateNote]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    scores: Mapped[list[Score]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    transcript: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_ms",
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
    # When this interviewer last submitted their competency scores for the session.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    # Where the question came from: the preset it was picked from, and the competency it targets
    # (the preset's, or the chosen follow-up's). A used follow-up points back here through
    # FollowUpSuggestion.used_qa_item_id.
    preset_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("preset_questions.id", ondelete="SET NULL")
    )
    target_competency: Mapped[str | None] = mapped_column(String(100))
    answer_text: Mapped[str | None] = mapped_column(Text)
    answer_deidentified: Mapped[str | None] = mapped_column(Text)
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="qa_items")
    preset_question: Mapped[PresetQuestion | None] = relationship()
    scores: Mapped[list[Score]] = relationship(
        back_populates="qa_item", cascade="all, delete-orphan"
    )


class Score(IdMixin, TimestampMixin, Base):
    """A 1-5 competency score. AI scores belong to one answer and must cite evidence from it.
    Interviewer scores are given per session and competency, so their `qa_item_id` is null."""

    __tablename__ = "scores"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="score_range"),
        CheckConstraint(
            "evaluator_type <> 'ai' OR evidence IS NOT NULL", name="ai_requires_evidence"
        ),
        CheckConstraint(
            "evaluator_type <> 'ai' OR qa_item_id IS NOT NULL", name="ai_requires_answer"
        ),
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    qa_item_id: Mapped[str | None] = mapped_column(ForeignKey("qa_items.id", ondelete="CASCADE"))
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evaluator_type: Mapped[EvaluatorType] = mapped_column(enum_column(EvaluatorType), nullable=False)
    evaluator_id: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    session: Mapped[InterviewSession] = relationship(back_populates="scores")
    qa_item: Mapped[QAItem | None] = relationship(back_populates="scores")


@event.listens_for(Session, "before_flush")
def _score_follows_its_answer(session: Session, _context: Any, _instances: Any) -> None:
    """A score added to an answer belongs to that answer's session; callers need not set both."""
    for obj in session.new:
        if isinstance(obj, Score) and obj.session is None and obj.session_id is None:
            if obj.qa_item is not None:
                obj.session = obj.qa_item.session


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


class FollowUpSuggestion(IdMixin, TimestampMixin, Base):
    """One AI follow-up suggestion (FR-06), kept whether or not the interviewer used it.

    Suggestions streamed together share `batch_id`. `grounding` quotes the de-identified answer
    the suggestion builds on and `rationale` says why the model proposed it. When the interviewer
    picks one, `used_qa_item_id` points at the question it became and `edited` says whether the
    wording was changed; the AI's original wording stays in `question`.
    """

    __tablename__ = "follow_up_suggestions"

    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    qa_item_id: Mapped[str] = mapped_column(
        ForeignKey("qa_items.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    grounding: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    used_qa_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("qa_items.id", ondelete="SET NULL")
    )
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    qa_item: Mapped[QAItem] = relationship(foreign_keys=[qa_item_id])
    used_qa_item: Mapped[QAItem | None] = relationship(foreign_keys=[used_qa_item_id])


class TranscriptSegment(IdMixin, TimestampMixin, Base):
    """A final STT segment, de-identified. Partial segments are streamed, never stored. The raw
    recognised text stays in the raw zone: QAItem.answer_text holds a whole answer."""

    __tablename__ = "transcript_segments"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    qa_item_id: Mapped[str | None] = mapped_column(ForeignKey("qa_items.id", ondelete="SET NULL"))
    speaker: Mapped[Speaker] = mapped_column(enum_column(Speaker), nullable=False)
    text_deidentified: Mapped[str] = mapped_column(Text, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)  # since the session started
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    session: Mapped[InterviewSession] = relationship(back_populates="transcript")
