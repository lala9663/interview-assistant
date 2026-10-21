"""De-identification reverse map: which original value each token stands for, per candidate.

This table belongs to the raw zone (업무정의서 9장): the original value is stored only as
Fernet ciphertext, and `value_hash` (keyed HMAC) lets the de-identifier find an existing token
without decrypting. Decryption happens only in `interview_assistant.deid.reidentify`.
In production this table moves to a separate schema with its own grants.
"""

from __future__ import annotations

import enum

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from interview_assistant.models.base import Base, IdMixin, TimestampMixin, enum_column


class DeidCategory(str, enum.Enum):
    candidate = "candidate"  # the candidate's own name and aliases
    person = "person"  # anyone else named in the text
    phone = "phone"
    email = "email"
    birthdate = "birthdate"
    rrn = "rrn"  # 주민등록번호
    address = "address"
    school = "school"
    company = "company"


class DeidMapping(IdMixin, TimestampMixin, Base):
    __tablename__ = "deid_mappings"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "category", "value_hash", name="uq_deid_mappings_candidate_value"
        ),
        UniqueConstraint("candidate_id", "token", name="uq_deid_mappings_candidate_token"),
    )

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[DeidCategory] = mapped_column(enum_column(DeidCategory), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    token: Mapped[str] = mapped_column(String(50), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
