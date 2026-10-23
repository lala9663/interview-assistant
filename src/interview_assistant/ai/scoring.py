"""FR-07: AI scoring after a session ends. Reference only; never merged with interviewer scores.

Each answered question is scored `SAMPLES` times against the session's competency dictionary.
A sample counts only if its competency is in the dictionary, its score is 1-5 and its evidence is
copied verbatim from the de-identified answer (근거 없는 점수 거부). Per answer and competency the
median of the valid samples is kept; confidence is the samples' own confidence scaled down by
their spread and by the share of samples that were rejected. An answer with no valid sample gets
no score ("근거 없음").
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from interview_assistant.ai.gateway import AiCall, AiGateway, model_name
from interview_assistant.ai.prompts import (
    SCORING_PROMPT,
    SCORING_SCHEMA,
    SCORING_SYSTEM,
    scoring_prompt,
)
from interview_assistant.deid.service import DeidService
from interview_assistant.interviews import session_competency_set
from interview_assistant.models import (
    ActorType,
    AiScoringStatus,
    AuditLog,
    EvaluatorType,
    InterviewSession,
    QAItem,
    Score,
)
from interview_assistant.models.base import utcnow

SAMPLES = 3

log = logging.getLogger(__name__)


class _Sample(BaseModel):
    competency: str
    score: int
    evidence: str
    confidence: float


class _Samples(BaseModel):
    scores: list[_Sample]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def valid_samples(structured: Any, answer: str, names: set[str]) -> list[_Sample]:
    try:
        parsed = _Samples.model_validate(structured or {})
    except ValidationError:
        return []
    text = _squash(answer)
    return [
        s
        for s in parsed.scores
        if s.competency in names
        and 1 <= s.score <= 5
        and 0 <= s.confidence <= 1
        and _squash(s.evidence).strip("\"'“”") in text
        and _squash(s.evidence)
    ]


def aggregate(samples: list[_Sample], total: int) -> tuple[int, float, str]:
    """(score, confidence, evidence) from the valid samples of one answer and competency."""
    scores = [s.score for s in samples]
    score = statistics.median_low(scores)
    spread = (max(scores) - min(scores)) / 4
    confidence = (
        statistics.fmean(s.confidence for s in samples) * (1 - spread) * len(samples) / total
    )
    evidence = next(s.evidence for s in samples if s.score == score)
    return score, round(confidence, 2), _squash(evidence).strip("\"'“”")


async def _score_answer(
    db: Session, ai: AiGateway, qa: QAItem, competencies: list[dict[str, Any]], known: Any
) -> tuple[list[Score], str | None]:
    names = {c["name"] for c in competencies}
    answer = qa.answer_deidentified or ""
    calls = [
        AiCall(
            action="score.ai_sample",
            prompt_version=SCORING_PROMPT,
            system=SCORING_SYSTEM,
            prompt=scoring_prompt(
                competencies=competencies,
                target_competency=qa.target_competency,
                question=qa.question,
                answer=answer,
            ),
            schema=SCORING_SCHEMA,
            candidate_texts=[answer, qa.question],
            known=known,
            target_type="interview_session",
            target_id=qa.session_id,
            details={"qa_item_id": qa.id, "sample": i + 1},
        )
        for i in range(SAMPLES)
    ]
    results = await asyncio.gather(*(ai.generate(db, c) for c in calls))
    by_competency: dict[str, list[_Sample]] = defaultdict(list)
    for result in results:
        for sample in valid_samples(result.structured, answer, names):
            by_competency[sample.competency].append(sample)
    rows = []
    for competency, samples in by_competency.items():
        score, confidence, evidence = aggregate(samples, SAMPLES)
        rows.append(
            Score(
                session_id=qa.session_id,
                qa_item_id=qa.id,
                competency=competency,
                score=score,
                evidence=evidence,
                confidence=confidence,
                evaluator_type=EvaluatorType.ai,
                model=results[0].model,
                prompt_version=SCORING_PROMPT,
            )
        )
    return rows, results[0].model if results else None


async def score_session(
    session_factory: sessionmaker[Session], ai: AiGateway, deid: DeidService, session_id: str
) -> None:
    """Runs in the background after the session ends; leaves status completed or failed."""
    with session_factory() as db:
        session = db.get(InterviewSession, session_id)
        if session is None:
            return
        try:
            competency_set = session_competency_set(db, session)
            competencies = competency_set.competencies if competency_set else []
            known = deid.identity(session.application.candidate)
            db.execute(
                delete(Score).where(
                    Score.session_id == session_id, Score.evaluator_type == EvaluatorType.ai
                )
            )
            scored, model = 0, None
            for qa in session.qa_items:
                if not qa.answer_deidentified or not competencies:
                    continue
                rows, model = await _score_answer(db, ai, qa, competencies, known)
                db.add_all(rows)
                scored += len(rows)
                db.commit()
            session.ai_scoring_status = AiScoringStatus.completed
            session.ai_scoring_finished_at = utcnow()
            db.add(
                AuditLog(
                    actor_type=ActorType.ai,
                    action="score.ai_completed",
                    target_type="interview_session",
                    target_id=session_id,
                    model=model or model_name(ai.llm("primary")),
                    prompt_version=SCORING_PROMPT,
                    details={"application_id": session.application_id, "scores": scored},
                )
            )
            db.commit()
        except Exception as exc:
            log.exception("AI scoring failed for session %s", session_id)
            db.rollback()
            session = db.get(InterviewSession, session_id)
            if session is not None:
                session.ai_scoring_status = AiScoringStatus.failed
                session.ai_scoring_finished_at = utcnow()
                db.add(
                    AuditLog(
                        actor_type=ActorType.ai,
                        action="score.ai_failed",
                        target_type="interview_session",
                        target_id=session_id,
                        prompt_version=SCORING_PROMPT,
                        details={"error": type(exc).__name__},
                    )
                )
                db.commit()
