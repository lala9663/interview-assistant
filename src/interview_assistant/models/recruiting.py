"""Job postings, their interview rounds (전형 차수), competency dictionaries, candidates,
applications, screening results."""

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
    from interview_assistant.models.interview import InterviewSession, RoundDecision

# A posting without rounds gets this one (and so did every posting before 0006): "1차 면접".
DEFAULT_ROUND_NAME = "면접"


class PostingStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    closed = "closed"


class ScreeningStatus(str, enum.Enum):
    passed = "passed"
    hold = "hold"
    rejected = "rejected"


class SessionMode(str, enum.Enum):
    onsite = "onsite"
    remote = "remote"


class ApplicationChannel(str, enum.Enum):
    """How an application reached the system (수신 경로)."""

    upload = "upload"  # a recruiter uploaded one file on the screening screen
    site = "site"  # the recruiting site sent it (intake/, docs/site-intake-spec.md)


class JobPosting(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_postings"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_family: Mapped[str] = mapped_column(String(100), nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PostingStatus] = mapped_column(
        enum_column(PostingStatus), default=PostingStatus.draft, nullable=False
    )
    # The recruiting site's posting number (채용 사이트 공고 번호). Site events name the posting by
    # it; empty until someone links the posting on its detail screen.
    site_posting_no: Mapped[str | None] = mapped_column(String(64), unique=True)

    rounds: Mapped[list[InterviewRound]] = relationship(
        back_populates="posting",
        cascade="all, delete-orphan",
        order_by="InterviewRound.position",
    )
    competency_sets: Mapped[list[CompetencySet]] = relationship(
        back_populates="posting",
        cascade="all, delete-orphan",
        order_by="CompetencySet.version",
    )
    applications: Mapped[list[Application]] = relationship(back_populates="posting")


class InterviewRound(IdMixin, TimestampMixin, Base):
    """One interview round of a posting (전형 차수): 1차 직무 면접, 2차 임원 면접 ...

    Rounds run in `position` order. Round 1 takes applications that passed screening; round N+1
    takes those a person passed in round N (RoundDecision). The short label is always
    "{position}차"; `name` says what the round is for. Each round has its own competency
    dictionary versions and preset questions. `show_previous_scores` decides whether the
    interviewers of this round see earlier rounds' scores (off by default, so earlier scores do
    not anchor them; they still see the points to check and the notes).
    """

    __tablename__ = "interview_rounds"
    __table_args__ = (
        UniqueConstraint("posting_id", "position", name="uq_interview_rounds_posting_position"),
        CheckConstraint(
            "recommended_interviewers >= 1 AND recommended_interviewers <= 10",
            name="recommended_interviewers_range",
        ),
    )

    posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_mode: Mapped[SessionMode] = mapped_column(
        enum_column(SessionMode), default=SessionMode.remote, nullable=False
    )
    recommended_interviewers: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    show_previous_scores: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    posting: Mapped[JobPosting] = relationship(back_populates="rounds")
    competency_sets: Mapped[list[CompetencySet]] = relationship(
        back_populates="round", cascade="all, delete-orphan", order_by="CompetencySet.version"
    )

    @property
    def label(self) -> str:
        return f"{self.position}차"


class CompetencySet(IdMixin, TimestampMixin, Base):
    """One version of the competency dictionary of an interview round.

    `competencies` is a list of {name, description, bars: {"1": ..., "5": ...}}. Versions count
    per round; `posting_id` is the round's posting, kept for lookups (filled in from the round).
    """

    __tablename__ = "competency_sets"
    __table_args__ = (
        UniqueConstraint("round_id", "version", name="uq_competency_sets_round_version"),
    )

    posting_id: Mapped[str] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        ForeignKey("interview_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    competencies: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    # Id of the interviewer who approved this version (the SSO user id once login exists).
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    posting: Mapped[JobPosting] = relationship(back_populates="competency_sets")
    round: Mapped[InterviewRound] = relationship(back_populates="competency_sets")
    preset_questions: Mapped[list[PresetQuestion]] = relationship(
        back_populates="competency_set",
        cascade="all, delete-orphan",
        order_by="PresetQuestion.position",
    )


class PresetQuestion(IdMixin, TimestampMixin, Base):
    """사전 질문 (FR-06). Two kinds:

    - A round's question, written against one competency-set version (`competency_set_id`), since
      each targets one of that version's competencies. A new draft copies the questions of the
      version it starts from; approving an AI draft carries over those whose competency it keeps.
    - A carry-over question (이어 질문) for one candidate's session in round 2 or later
      (`session_id`): drafted by AI from the de-identified Q&A of earlier rounds, so the round
      digs deeper instead of asking the same again. `based_on_qa_item_id` is the earlier answer
      it builds on and `grounding` quotes that answer verbatim.
    """

    __tablename__ = "preset_questions"
    __table_args__ = (
        UniqueConstraint("competency_set_id", "position", name="uq_preset_questions_set_position"),
        UniqueConstraint("session_id", "position", name="uq_preset_questions_session_position"),
        CheckConstraint(
            "competency_set_id IS NOT NULL OR session_id IS NOT NULL", name="set_or_session"
        ),
    )

    competency_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("competency_sets.id", ondelete="CASCADE")
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # Carry-over questions only (AI): the earlier answer, a verbatim quote of it, and why. A plain
    # id, not a foreign key: qa_items already points here (preset_question_id), and a key both
    # ways would leave the tables without a creation order.
    based_on_qa_item_id: Mapped[str | None] = mapped_column(String(36))
    grounding: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    competency_set: Mapped[CompetencySet | None] = relationship(back_populates="preset_questions")


class Candidate(IdMixin, TimestampMixin, Base):
    """A person. Identity lives only in `encrypted_identity`; everything else uses `pseudonym`.

    `site_applicant_hash` is a keyed hash (`FieldCipher.lookup_hash`) of the recruiting site's
    applicant number: the same number is the same person whichever posting they apply to. The
    number itself is never stored and never leaves the API. Uploads have none (each upload is a
    new person).
    """

    __tablename__ = "candidates"

    pseudonym: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    encrypted_identity: Mapped[str | None] = mapped_column(Text)
    site_applicant_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
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
    # What the uploaded file held, as counts only: {format, blocks, hidden_blocks, images_dropped,
    # replacements}. Hidden blocks are de-identified but kept out of the screening prompt.
    document_info: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    channel: Mapped[ApplicationChannel] = mapped_column(
        enum_column(ApplicationChannel),
        default=ApplicationChannel.upload,
        server_default=ApplicationChannel.upload.value,
        nullable=False,
    )
    # The recruiting site's application number (채용 사이트 지원 번호): one row per number, so an
    # application sent twice or updated stays one application.
    site_application_no: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Withdrawn on the recruiting site: the row stays (the site is the record) but leaves every list.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="applications")
    posting: Mapped[JobPosting] = relationship(back_populates="applications")
    screening: Mapped[Screening | None] = relationship(
        back_populates="application", cascade="all, delete-orphan", uselist=False
    )
    sessions: Mapped[list[InterviewSession]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    decisions: Mapped[list[RoundDecision]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="RoundDecision.revision",
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
    # Plain-text rendering (summary, `+ ` met, `- ` not met or to check) for readers that predate
    # `assessment`; rows screened before screening-v0.5 have only this.
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # screening-v0.5: {summary, requirements: [{kind, requirement, verdict, evidence, source}],
    # interview_checks} (ai/screening.py Assessment).
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # The AI's 통과/보류/탈락 recommendation (passed / hold / rejected). Reference only.
    recommendation: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[ScreeningStatus] = mapped_column(enum_column(ScreeningStatus), nullable=False)
    # Why a person set 탈락 (de-identified); cleared when the status moves away from 탈락.
    reject_reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    application: Mapped[Application] = relationship(back_populates="screening")
