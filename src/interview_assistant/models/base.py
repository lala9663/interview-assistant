"""Declarative base, id/timestamp mixins, and a constraint naming convention.

The naming convention matters for Alembic: SQLite cannot drop unnamed constraints, so
every constraint gets a deterministic name here. All column types are chosen to work on
SQLite, PostgreSQL and MySQL alike (no JSONB, no ARRAY, no native enums).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Aware UTC. SQLite hands DateTime(timezone=True) columns back naive; they are stored as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    """The API's datetime format: UTC, milliseconds, `Z` (what JavaScript's toISOString gives)."""
    return as_utc(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def enum_column(enum_cls: type[enum.Enum], length: int = 20) -> Enum:
    """Portable enum: stored as VARCHAR of the enum *values*, with a CHECK constraint."""
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda e: [member.value for member in e],
    )


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
