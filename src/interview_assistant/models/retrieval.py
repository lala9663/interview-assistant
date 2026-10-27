"""The question bank, rubric anchor answers, and the stored embedding vectors with their indexes.

The question bank holds questions recruiters wrote and approved per job family and competency
(and optionally round). Only approved questions are ever searched or suggested. Rubric examples
are made-up answers that people wrote and approved as anchors for each score 1-5 of a competency;
the scoring prompt shows them next to the BARS levels. Neither ever holds an applicant's answer.

Vectors are stored engine-independently (float32 bytes and a JSON map) with the key of the model
that made them (`EmbeddingProvider.index_key`), so switching models means rebuilding them; the
CHECK on `owner_type` keeps anything but these three company-written sources out of the store.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from interview_assistant.models.base import Base, IdMixin, TimestampMixin, enum_column, utcnow
from interview_assistant.models.interview import Interviewer


class BankStatus(str, enum.Enum):
    draft = "draft"  # 초안
    approved = "approved"  # 승인: the only status that is searched and suggested
    retired = "retired"  # 폐기


class BankSource(str, enum.Enum):
    manual = "manual"
    csv = "csv"
    seed = "seed"


class QuestionBankItem(IdMixin, TimestampMixin, Base):
    """One vetted interview question of a job family and competency (질문 은행).

    `round_position` limits it to one round (1차, 2차 ...) across postings; null means any round.
    `follow_ups` are good follow-up questions to it, written by people: they are searched too and
    shown to the LLM as examples. `flags` are the prohibited-question warnings (rules, and the AI
    check when someone ran it) for the current text; approving a flagged question needs an
    explicit confirmation, recorded in the audit log.
    """

    __tablename__ = "question_bank_items"
    __table_args__ = (
        CheckConstraint(
            "round_position IS NULL OR (round_position >= 1 AND round_position <= 6)",
            name="round_position_range",
        ),
        CheckConstraint(
            "status <> 'approved' OR approved_by IS NOT NULL", name="approved_has_approver"
        ),
    )

    job_family: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    round_position: Mapped[int | None] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    follow_ups: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[BankStatus] = mapped_column(
        enum_column(BankStatus), default=BankStatus.draft, nullable=False
    )
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[BankSource] = mapped_column(
        enum_column(BankSource), default=BankSource.manual, nullable=False
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("interviewers.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("interviewers.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[Interviewer] = relationship(foreign_keys=[created_by])
    approver: Mapped[Interviewer | None] = relationship(foreign_keys=[approved_by])


class RubricExample(IdMixin, TimestampMixin, Base):
    """평점 기준 예시: a made-up answer at one score (1-5) of one competency, written and approved
    by people. The scoring prompt shows the approved ones as anchors beside the BARS levels; the
    score itself still comes from the model reading the candidate's answer against the levels,
    never from how close the answer is to an example. An applicant's answer is refused here."""

    __tablename__ = "rubric_examples"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="score_range"),
        CheckConstraint(
            "status <> 'approved' OR approved_by IS NOT NULL", name="approved_has_approver"
        ),
    )

    job_family: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    competency: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, default="", nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[BankStatus] = mapped_column(
        enum_column(BankStatus), default=BankStatus.draft, nullable=False
    )
    source: Mapped[BankSource] = mapped_column(
        enum_column(BankSource), default=BankSource.manual, nullable=False
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("interviewers.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("interviewers.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[Interviewer] = relationship(foreign_keys=[created_by])
    approver: Mapped[Interviewer | None] = relationship(foreign_keys=[approved_by])


# What may be embedded and stored: company-written text only. Candidate answers, transcripts and
# documents are never vectors (the CHECK below keeps it so at the database too).
INDEXED_OWNERS = ("question", "rubric", "competency_set")


class EmbeddingVector(IdMixin, Base):
    """One text's vectors under one model. `part` numbers the texts of one owner (a bank question
    is part 0, its follow-up examples 1..n). `text_hash` tells a stale vector after an edit."""

    __tablename__ = "embedding_vectors"
    __table_args__ = (
        UniqueConstraint("index_key", "owner_type", "owner_id", "part", name="uq_embedding_vectors_owner"),
        CheckConstraint(
            "owner_type IN ('question', 'rubric', 'competency_set')", name="company_text_only"
        ),
    )

    index_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    part: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    dense: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # float32, little-endian
    sparse: Mapped[dict[str, float] | None] = mapped_column(JSON)  # token id -> weight
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class IndexStatus(str, enum.Enum):
    building = "building"
    ready = "ready"
    failed = "failed"


class EmbeddingIndex(Base):
    """The vectors of one embedding model: being built, ready (searched), or failed. The newest
    ready one is searched; while a new model's index is built, the old one keeps serving. `spec`
    rebuilds the provider that made it after a restart."""

    __tablename__ = "embedding_indexes"

    index_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[IndexStatus] = mapped_column(enum_column(IndexStatus), nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
