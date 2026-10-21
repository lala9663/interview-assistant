"""Audit log: every AI call and every user action, append-only.

Prompts and responses are not stored inline (they may contain candidate data); `payload_ref`
points at the stored payload in the raw zone.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from interview_assistant.models.base import Base, IdMixin, enum_column, utcnow


class ActorType(str, enum.Enum):
    user = "user"
    system = "system"
    ai = "ai"


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(36), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    payload_ref: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
