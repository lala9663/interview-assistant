"""Interviewers, sessions, Q&A items, scores, notes, availability, follow-ups, transcripts,
round decisions and points to check in a later round."""

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
    false,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from interview_assistant.models.base import Base, IdMixin, TimestampMixin, enum_column, new_id
from interview_assistant.models.recruiting import (
    DEFAULT_ROUND_NAME,
    Application,
    CompetencySet,
    InterviewRound,
    JobPosting,
    PresetQuestion,
    SessionMode,
)

__all__ = ["SessionMode"]  # defined with the rounds (InterviewRound.default_mode), re-exported


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


class DecisionStatus(str, enum.Enum):
    """A person's decision on a round (합격 / 보류 / 불합격). AI scores are reference only."""

    passed = "passed"
    hold = "hold"
    rejected = "rejected"


class CheckPointSource(str, enum.Enum):
    interviewer = "interviewer"
    ai = "ai"


# Sessions that still hold their round open: an application has at most one per round.
OPEN_STATUSES = frozenset({SessionStatus.scheduled, SessionStatus.in_progress})


class Interviewer(IdMixin, TimestampMixin, Base):
    __tablename__ = "interviewers"

    employee_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_family: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    # May change AI model settings (admin > 모델 설정). SSO will map a group onto this flag.
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    availabilities: Mapped[list[Availability]] = relationship(
        back_populates="interviewer", cascade="all, delete-orphan"
    )
    session_links: Mapped[list[SessionInterviewer]] = relationship(back_populates="interviewer")


class InterviewSession(IdMixin, TimestampMixin, Base):
    """One interview of one application in one round (차수).

    `active_round_id` repeats `round_id` while the session is scheduled or in progress and is
    null otherwise (kept in step by a flush hook), so the unique constraint on (application,
    active_round_id) stops a second open session of the same round at the database too.
    """

    __tablename__ = "interview_sessions"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "active_round_id", name="uq_interview_sessions_open_round"
        ),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        ForeignKey("interview_rounds.id"), nullable=False, index=True
    )
    active_round_id: Mapped[str | None] = mapped_column(String(36))
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
    # The AI model config revision (ai_model_changes.revision) in force when the session started.
    # Live transcription, follow-ups and the AI scoring after it all use those providers, even if
    # an admin switches models meanwhile. Null: not started yet (or started before 0004).
    ai_config_revision: Mapped[int | None] = mapped_column(Integer)

    application: Mapped[Application] = relationship(back_populates="sessions")
    round: Mapped[InterviewRound] = relationship()
    competency_set: Mapped[CompetencySet | None] = relationship()
    # 이어 질문: AI questions for this candidate from earlier rounds' Q&A (PresetQuestion.session_id).
    carryover_questions: Mapped[list[PresetQuestion]] = relationship(
        cascade="all, delete-orphan", order_by="PresetQuestion.position"
    )
    check_points: Mapped[list[CheckPoint]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="CheckPoint.created_at"
    )
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
    preset_question: Mapped[PresetQuestion | None] = relationship(foreign_keys=[preset_question_id])
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


class SuggestionSource(str, enum.Enum):
    bank = "bank"  # an approved question-bank question found for the answer (shown first)
    ai = "ai"  # written by the LLM for this answer


class FollowUpSuggestion(IdMixin, TimestampMixin, Base):
    """One follow-up suggestion (FR-06), kept whether or not the interviewer used it.

    Suggestions shown together share `batch_id`. `source` says where it came from: the question
    bank (`bank_item_id`, `retrieval_score`) or the LLM. `grounding` quotes the de-identified
    answer the suggestion builds on and `rationale` says why it was proposed. When the interviewer
    picks one, `used_qa_item_id` points at the question it became and `edited` says whether the
    wording was changed; the original wording stays in `question`. `latency_ms` is how long after
    the request it appeared. A candidate that meant the same as a question already asked (this
    interview, earlier rounds, or a suggestion shown before it) is kept with `discarded` =
    "duplicate", `duplicate_of` and `similarity`, and was never shown or was taken back.
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
    source: Mapped[SuggestionSource] = mapped_column(
        enum_column(SuggestionSource),
        default=SuggestionSource.ai,
        server_default=SuggestionSource.ai.value,
        nullable=False,
    )
    bank_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("question_bank_items.id", ondelete="SET NULL")
    )
    retrieval_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    discarded: Mapped[str | None] = mapped_column(String(20))
    duplicate_of: Mapped[str | None] = mapped_column(Text)
    similarity: Mapped[float | None] = mapped_column(Float)

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
    # The STT model that recognised a candidate segment (null for typed interviewer questions).
    model: Mapped[str | None] = mapped_column(String(100))

    session: Mapped[InterviewSession] = relationship(back_populates="transcript")


class RoundDecision(IdMixin, TimestampMixin, Base):
    """A person's decision on one application in one round (N차 결정): 합격, 보류 or 불합격.

    Append-only: changing a decision adds the next `revision`, so the history stays. The current
    decision is the highest revision. `reason` is de-identified like every other free text.
    Recorded only after the round's interview was evaluated (every interviewer submitted). A pass
    in the posting's last round makes the application a final candidate (최종 합격 후보); the
    official result is recorded on the recruiting site, not here.
    """

    __tablename__ = "round_decisions"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "round_id", "revision", name="uq_round_decisions_revision"
        ),
        CheckConstraint("revision >= 1", name="revision_positive"),
    )

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_id: Mapped[str] = mapped_column(ForeignKey("interview_rounds.id"), nullable=False)
    # The evaluated session the decision was made on.
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="SET NULL")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[DecisionStatus] = mapped_column(enum_column(DecisionStatus), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(ForeignKey("interviewers.id"), nullable=False)

    application: Mapped[Application] = relationship(back_populates="decisions")
    round: Mapped[InterviewRound] = relationship()
    session: Mapped[InterviewSession | None] = relationship()
    decider: Mapped[Interviewer] = relationship()


class CheckPoint(IdMixin, TimestampMixin, Base):
    """확인이 필요한 점: something a later round should check, noted on one session.

    Interviewers write them on the evaluation screen; AI extracts them after scoring, each with
    `evidence` quoted verbatim from the de-identified answer (`qa_item_id`). The next round's
    candidate card shows them whatever the score setting, since they carry no scores.
    """

    __tablename__ = "check_points"
    __table_args__ = (
        CheckConstraint("source <> 'ai' OR evidence IS NOT NULL", name="ai_requires_evidence"),
        CheckConstraint(
            "source <> 'interviewer' OR author_id IS NOT NULL", name="interviewer_requires_author"
        ),
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[CheckPointSource] = mapped_column(
        enum_column(CheckPointSource), nullable=False
    )
    competency: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    qa_item_id: Mapped[str | None] = mapped_column(ForeignKey("qa_items.id", ondelete="SET NULL"))
    author_id: Mapped[str | None] = mapped_column(ForeignKey("interviewers.id"))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))

    session: Mapped[InterviewSession] = relationship(back_populates="check_points")
    qa_item: Mapped[QAItem | None] = relationship()
    author: Mapped[Interviewer | None] = relationship()


@event.listens_for(Session, "before_flush")
def _rounds_fill_in(session: Session, _context: Any, _instances: Any) -> None:
    """Rounds callers need not spell out: a new posting gets its first round ("1차 면접"), a
    competency set or session without a round goes to the posting's first round, a set takes its
    round's posting, and every session's `active_round_id` follows its status."""
    for obj in list(session.new):
        if isinstance(obj, JobPosting) and not obj.rounds:
            obj.rounds.append(InterviewRound(id=new_id(), position=1, name=DEFAULT_ROUND_NAME))
    for obj in list(session.new):
        if isinstance(obj, CompetencySet):
            if obj.round is None and obj.round_id is None:
                posting = obj.posting or session.get(JobPosting, obj.posting_id)
                if posting is not None and posting.rounds:
                    obj.round = posting.rounds[0]
            if obj.posting is None and obj.posting_id is None and obj.round is not None:
                obj.posting = obj.round.posting
    for obj in [*session.new, *session.dirty]:
        if not isinstance(obj, InterviewSession):
            continue
        if obj.round is None and obj.round_id is None:
            application = obj.application or session.get(Application, obj.application_id)
            if application is not None and application.posting.rounds:
                obj.round = application.posting.rounds[0]
        if obj.round is not None and obj.round.id is None:
            obj.round.id = new_id()
        round_id = obj.round.id if obj.round is not None else obj.round_id
        status = obj.status or SessionStatus.scheduled
        obj.active_round_id = round_id if status in OPEN_STATUSES else None
