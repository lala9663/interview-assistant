"""Re-identification: the single place that decrypts the reverse map.

Every call names who is asking and why, and leaves an AuditLog row (counts only, never values).
Callers outside the raw zone (LLM prompts, exports, logs) must not import this module.

The value returned for a token is the canonical form stored at tokenisation time, e.g. a text
that said "서울대" comes back as "서울대학교", and a phone number comes back as digits only.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.crypto import FieldCipher
from interview_assistant.models.audit import ActorType, AuditLog
from interview_assistant.models.deid import DeidMapping


def reidentify_text(
    session: Session,
    cipher: FieldCipher,
    *,
    candidate_id: str,
    text: str,
    actor_type: ActorType,
    actor_id: str | None,
    purpose: str,
) -> str:
    """Replace every token of this candidate in `text` with its original value."""
    rows = session.scalars(
        select(DeidMapping).where(DeidMapping.candidate_id == candidate_id)
    ).all()
    by_token = {row.token: row for row in rows}
    resolved: dict[str, str] = {}

    def replace(m: re.Match[str]) -> str:
        token = m.group()
        if token not in resolved:
            resolved[token] = cipher.decrypt(by_token[token].encrypted_value)
        return resolved[token]

    result = text
    if by_token:
        tokens = sorted(by_token, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(t) for t in tokens))
        result = pattern.sub(replace, text)
    count = len(resolved)
    _audit(session, "deid.reidentify_text", candidate_id, actor_type, actor_id, purpose, count)
    return result


def lookup_token(
    session: Session,
    cipher: FieldCipher,
    *,
    candidate_id: str,
    token: str,
    actor_type: ActorType,
    actor_id: str | None,
    purpose: str,
) -> str | None:
    """Original value of one token, or None if this candidate has no such token."""
    row = session.scalar(
        select(DeidMapping).where(
            DeidMapping.candidate_id == candidate_id, DeidMapping.token == token
        )
    )
    value = cipher.decrypt(row.encrypted_value) if row is not None else None
    resolved = 0 if row is None else 1
    _audit(session, "deid.lookup_token", candidate_id, actor_type, actor_id, purpose, resolved)
    return value


def _audit(
    session: Session,
    action: str,
    candidate_id: str,
    actor_type: ActorType,
    actor_id: str | None,
    purpose: str,
    resolved: int,
) -> None:
    session.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type="candidate",
            target_id=candidate_id,
            details={"purpose": purpose, "tokens_resolved": resolved},
        )
    )
    session.flush()
