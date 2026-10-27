"""Question-bank and rubric-anchor logic shared by the API and the AI tasks.

- `bank_matches`: approved bank questions (or their follow-up examples) close to an answer, for
  the instant follow-up suggestions and as examples in the LLM prompt.
- `duplicate_of`: whether a candidate question means the same as one already asked.
- `anchors_for`: the approved rubric examples the scoring prompt shows, chosen by job family and
  competency only. They are never chosen by how close they are to the candidate's answer, and the
  score never comes from such a closeness: that would favour rehearsed answers.
- `looks_like_applicant_answer`: refuses a rubric example that copies a stored applicant answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.models import BankStatus, QAItem, QuestionBankItem, RubricExample
from interview_assistant.providers.base import Embedding
from interview_assistant.retrieval.index import Hit
from interview_assistant.retrieval.service import Retrieval


@dataclass(frozen=True)
class BankMatch:
    item: QuestionBankItem
    text: str  # what to ask: the question, or the follow-up example that matched
    part: int
    score: float
    embedding: list[float]


async def bank_matches(
    retrieval: Retrieval,
    db: Session,
    query: Embedding,
    *,
    job_family: str,
    competencies: Sequence[str],
    round_position: int | None,
    k: int = 6,
) -> list[BankMatch]:
    """Best part per approved item, best first. Approval is checked again in the database."""
    where: dict[str, object] = {"job_family": job_family, "round_position": (None, round_position)}
    if competencies:
        where["competency"] = tuple(competencies)
    hits: list[Hit] = retrieval.search(query, owner_type="question", where=where, k=k * 4)
    best: dict[str, Hit] = {}
    for hit in hits:
        if hit.doc.owner_id not in best:
            best[hit.doc.owner_id] = hit
    if not best:
        return []
    items = {
        i.id: i
        for i in db.scalars(
            select(QuestionBankItem).where(
                QuestionBankItem.id.in_(list(best)),
                QuestionBankItem.status == BankStatus.approved,
            )
        )
    }
    found = []
    for owner_id, hit in best.items():
        item = items.get(owner_id)
        if item is None:
            continue
        vector = retrieval.serving.index.vector(hit.doc.key) if retrieval.serving else None
        found.append(
            BankMatch(
                item,
                hit.doc.text,
                hit.doc.part,
                hit.score,
                vector.tolist() if vector is not None else [],
            )
        )
    return found[:k]


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not len(a) or not len(b):
        return 0.0
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb) / norm if norm else 0.0


def duplicate_of(
    vector: Sequence[float], asked: Sequence[tuple[str, Sequence[float]]], threshold: float
) -> tuple[str, float] | None:
    """The asked question this one means the same as (dense similarity >= threshold), if any."""
    best: tuple[str, float] | None = None
    for text, other in asked:
        score = similarity(vector, other)
        if score >= threshold and (best is None or score > best[1]):
            best = (text, score)
    return best


# --- rubric anchors ---------------------------------------------------------------------------


def anchors_for(
    db: Session, job_family: str, competencies: Sequence[str]
) -> list[tuple[str, int, str, str, str]]:
    """(competency, score, question, answer, why): per competency the newest approved example of
    each score, from the posting's job family; a competency with none there takes the same
    competency name from other job families. Selection never looks at the candidate's answer."""
    rows = db.scalars(
        select(RubricExample)
        .where(
            RubricExample.status == BankStatus.approved,
            RubricExample.competency.in_(list(competencies)),
        )
        .order_by(RubricExample.approved_at.desc())
    ).all()
    out = []
    for name in competencies:
        mine = [r for r in rows if r.competency == name and r.job_family == job_family]
        pool = mine or [r for r in rows if r.competency == name]
        by_score: dict[int, RubricExample] = {}
        for row in pool:
            by_score.setdefault(row.score, row)
        for score in sorted(by_score):
            row = by_score[score]
            out.append((name, score, row.question, row.answer, row.rationale))
    return out


def _shingles(text: str, n: int = 5) -> set[str]:
    squashed = re.sub(r"\s+", "", text)
    return {squashed[i : i + n] for i in range(max(0, len(squashed) - n + 1))}


def looks_like_applicant_answer(db: Session, text: str, *, overlap: float = 0.6) -> bool:
    """True when most of `text` is copied from a stored (de-identified) applicant answer."""
    mine = _shingles(text)
    if len(mine) < 8:
        return False
    for answer in db.scalars(select(QAItem.answer_deidentified).where(QAItem.answer_deidentified.is_not(None))):
        theirs = _shingles(answer or "")
        if theirs and len(mine & theirs) / len(mine) >= overlap:
            return True
    return False
