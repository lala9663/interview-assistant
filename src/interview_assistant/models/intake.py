"""Application events received from the recruiting site (채용 사이트 연동), one row per event.

The row is the queue entry, the idempotency record and the audit trail of one event at once:
`event_id` (the site's) is unique, so a resent event finds its row instead of being applied again;
`status` moves queued -> processing -> done / skipped / failed and the background worker resumes
queued and interrupted rows after a restart. Events refused at the door (forbidden or missing
fields) are kept as `rejected` with field names only.

The payload (identity, form fields, essays) is raw zone: Fernet ciphertext, kept only while the
event can still be processed (queued, processing, failed) and cleared once it is applied; the
recruiting site stays the record. Attachments wait in the raw-zone folder `uploads/intake/{id}/`.
Failure messages and field lists never carry values, only codes and field names.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from interview_assistant.models.base import Base, IdMixin, enum_column, utcnow
from interview_assistant.models.recruiting import (
    Application,
    ApplicationChannel,
    Candidate,
    JobPosting,
)


class IntakeEventType(str, enum.Enum):
    submitted = "submitted"  # 제출
    updated = "updated"  # 수정 (마감 전)
    withdrawn = "withdrawn"  # 철회


class IntakeStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    done = "done"  # applied
    skipped = "skipped"  # not applied on purpose: an older revision, or withdrawn meanwhile
    failed = "failed"  # could not be applied; retriable while the payload is kept
    rejected = "rejected"  # refused at the door (422): nothing was stored but field names


class IntakeEvent(IdMixin, Base):
    __tablename__ = "intake_events"
    __table_args__ = (UniqueConstraint("channel", "event_id", name="uq_intake_events_channel_event"),)

    channel: Mapped[ApplicationChannel] = mapped_column(
        enum_column(ApplicationChannel), default=ApplicationChannel.site, nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[IntakeEventType | None] = mapped_column(enum_column(IntakeEventType))
    status: Mapped[IntakeStatus] = mapped_column(
        enum_column(IntakeStatus), default=IntakeStatus.queued, nullable=False, index=True
    )
    # The site's per-application revision: higher wins, so events may arrive in any order.
    revision: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    posting_no: Mapped[str | None] = mapped_column(String(64))
    application_no: Mapped[str | None] = mapped_column(String(64), index=True)
    posting_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL")
    )
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL")
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )

    # sha256 of the canonical event JSON and attachment hashes: a resend with the same event_id
    # must carry the same content.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    failure_code: Mapped[str | None] = mapped_column(String(40))
    failure_message: Mapped[str | None] = mapped_column(Text)
    # Field paths only, never values: what was missing, or which forbidden items came in.
    failure_fields: Mapped[list[str] | None] = mapped_column(JSON)
    # Fields outside the spec that were dropped before anything was stored (names only).
    dropped_fields: Mapped[list[str] | None] = mapped_column(JSON)
    # What applying did: {created, new_candidate, screening_reset, cancelled_sessions ...}.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    posting: Mapped[JobPosting | None] = relationship()
    candidate: Mapped[Candidate | None] = relationship()
    application: Mapped[Application | None] = relationship()
