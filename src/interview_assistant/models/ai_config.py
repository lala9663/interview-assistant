"""Which provider serves each AI role, and every change to it (admin > 모델 설정).

`ai_model_settings` holds the active spec per role. `ai_model_changes` is the append-only history:
who changed which role, when, from what to what and why. Every change gets the next global
`revision`; a session pins the revision it started with, so the config in force at any revision
can be rebuilt from the history (for each role, its latest change at or below that revision).
The providers YAML only seeds the first revision (kind `initial`, no actor).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from interview_assistant.models.base import Base, IdMixin, enum_column, utcnow


class ModelChangeKind(str, enum.Enum):
    initial = "initial"  # seeded from the providers YAML at first start
    apply = "apply"
    rollback = "rollback"


class AiModelSetting(Base):
    __tablename__ = "ai_model_settings"

    # "llm.primary", "stt.batch" ... (providers.catalog.ROLES)
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    # {"impl": "...", "options": {...}}: a ProviderSpec without credentials (those stay in env).
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)  # the change that set it
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AiModelChange(IdMixin, Base):
    __tablename__ = "ai_model_changes"

    revision: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    kind: Mapped[ModelChangeKind] = mapped_column(enum_column(ModelChangeKind), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("interviewers.id", ondelete="SET NULL"))
    previous: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    reverts_change_id: Mapped[str | None] = mapped_column(String(36))
    # Where the new provider sends data, and whether the admin confirmed an external transfer.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
