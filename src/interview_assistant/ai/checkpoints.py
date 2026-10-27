"""확인이 필요한 점: after AI scoring, points the next round should check, with evidence.

One call over the session's de-identified Q&A. A point counts only if its evidence is copied
verbatim from the answer it names (like scores, 근거 없는 항목 거부); its competency must be in
the session's dictionary or is dropped. The AI's points replace its earlier ones for the session;
interviewers' points are never touched. Reference only: they carry no score.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from interview_assistant.ai.gateway import AiCall, AiGateway
from interview_assistant.ai.prompts import (
    CHECKPOINT_PROMPT,
    CHECKPOINT_SCHEMA,
    CHECKPOINT_SYSTEM,
    checkpoint_prompt,
)
from interview_assistant.deid.types import KnownIdentity
from interview_assistant.models import CheckPoint, CheckPointSource, InterviewSession

MAX_POINTS = 3


class _Point(BaseModel):
    competency: str = ""
    point: str
    evidence: str
    qa_seq: int


class _Points(BaseModel):
    points: list[_Point]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


async def extract_check_points(
    db: Session,
    ai: AiGateway,
    session: InterviewSession,
    competencies: list[dict[str, Any]],
    known: KnownIdentity | None,
) -> int:
    """Stores the AI's points for the session; returns how many were kept."""
    answered = [qa for qa in session.qa_items if qa.answer_deidentified]
    db.execute(
        delete(CheckPoint).where(
            CheckPoint.session_id == session.id, CheckPoint.source == CheckPointSource.ai
        )
    )
    db.commit()
    if not answered:
        return 0
    result = await ai.generate(
        db,
        AiCall(
            action="checkpoint.generated",
            prompt_version=CHECKPOINT_PROMPT,
            system=CHECKPOINT_SYSTEM,
            prompt=checkpoint_prompt(
                competencies=competencies,
                qa=[(qa.seq, qa.question, qa.answer_deidentified or "") for qa in answered],
            ),
            schema=CHECKPOINT_SCHEMA,
            candidate_texts=[t for qa in answered for t in (qa.question, qa.answer_deidentified or "")],
            known=known,
            target_type="interview_session",
            target_id=session.id,
        ),
    )
    try:
        drafts = _Points.model_validate(result.structured or {}).points
    except ValidationError:
        drafts = []
    by_seq = {qa.seq: qa for qa in answered}
    names = {c["name"] for c in competencies}
    kept = 0
    for draft in drafts:
        qa = by_seq.get(draft.qa_seq)
        evidence = _squash(draft.evidence).strip("\"'“”")
        if qa is None or not evidence or evidence not in _squash(qa.answer_deidentified or ""):
            continue
        if not draft.point.strip():
            continue
        db.add(
            CheckPoint(
                session_id=session.id,
                source=CheckPointSource.ai,
                competency=draft.competency if draft.competency in names else None,
                text=draft.point.strip(),
                evidence=evidence,
                qa_item_id=qa.id,
                model=result.model,
                prompt_version=CHECKPOINT_PROMPT,
            )
        )
        kept += 1
        if kept >= MAX_POINTS:
            break
    db.commit()
    return kept
