"""Model settings in the database: the active spec per role and the change history.

Specs are stored as {"impl": ..., "options": {...}}. Credentials never appear in them (providers
read those from the environment). The providers YAML is read only to seed roles that have no row
yet: on the first start, or when a new role is added later.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from interview_assistant.config import ProviderSpec
from interview_assistant.models import AiModelChange, AiModelSetting, ModelChangeKind
from interview_assistant.models.base import utcnow
from interview_assistant.providers.catalog import ROLE_BY_KEY

INITIAL_REASON = "providers YAML 기본값"


def spec_json(spec: ProviderSpec) -> dict[str, Any]:
    return {"impl": spec.impl, "options": spec.options}


def spec_from(data: Mapping[str, Any]) -> ProviderSpec:
    return ProviderSpec(impl=data["impl"], **dict(data.get("options") or {}))


def same(a: ProviderSpec | None, b: ProviderSpec | None) -> bool:
    return a is not None and b is not None and spec_json(a) == spec_json(b)


def current_revision(db: Session) -> int:
    return db.scalar(select(func.max(AiModelChange.revision))) or 0


def active(db: Session) -> dict[str, AiModelSetting]:
    return {row.role: row for row in db.scalars(select(AiModelSetting)) if row.role in ROLE_BY_KEY}


def load_or_seed(
    db: Session, defaults: Mapping[str, ProviderSpec]
) -> tuple[int, dict[str, ProviderSpec]]:
    """The active revision and specs; roles without a row are seeded from `defaults` first."""
    rows = active(db)
    missing = [role for role in ROLE_BY_KEY if role not in rows and role in defaults]
    if missing:
        for role in missing:
            record(db, role, ModelChangeKind.initial, None, defaults[role], reason=INITIAL_REASON)
        rows = active(db)
    return current_revision(db), {role: spec_from(row.spec) for role, row in rows.items()}


def specs_at(db: Session, revision: int) -> dict[str, ProviderSpec]:
    """The config in force right after `revision`: each role's latest change at or below it."""
    rows = db.scalars(
        select(AiModelChange)
        .where(AiModelChange.revision <= revision)
        .order_by(AiModelChange.revision)
    ).all()
    return {row.role: spec_from(row.new) for row in rows if row.role in ROLE_BY_KEY}


def record(
    db: Session,
    role: str,
    kind: ModelChangeKind,
    previous: ProviderSpec | None,
    new: ProviderSpec,
    *,
    actor_id: str | None = None,
    reason: str | None = None,
    reverts_change_id: str | None = None,
    details: dict[str, Any] | None = None,
    also: Callable[[Session, AiModelChange], None] | None = None,
) -> AiModelChange:
    """One change: the next revision in the history and the role's active row, committed together
    with whatever `also` adds (the audit row)."""
    revision = current_revision(db) + 1
    change = AiModelChange(
        revision=revision,
        role=role,
        kind=kind,
        actor_id=actor_id,
        previous=spec_json(previous) if previous is not None else None,
        new=spec_json(new),
        reason=reason,
        reverts_change_id=reverts_change_id,
        details=details,
    )
    db.add(change)
    row = db.get(AiModelSetting, role)
    if row is None:
        db.add(AiModelSetting(role=role, spec=spec_json(new), revision=revision))
    else:
        row.spec = spec_json(new)
        row.revision = revision
        row.updated_at = utcnow()
    if also is not None:
        also(db, change)
    db.commit()
    return change


def history(db: Session, *, role: str | None = None, limit: int = 100) -> list[AiModelChange]:
    query = select(AiModelChange).order_by(AiModelChange.revision.desc()).limit(limit)
    if role is not None:
        query = query.where(AiModelChange.role == role)
    return list(db.scalars(query))
