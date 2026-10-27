"""What is embedded: approved company-written text only.

- `question`: an approved question-bank question (part 0) and each of its follow-up examples
  (parts 1..n), filtered by job family, competency and round.
- `rubric`: an approved rubric anchor answer, for the overlap warning between score levels.
- `competency_set`: the approved competency dictionary of each round, found by how close its
  posting is to a new one (draft examples).

Drafts, retired items, candidate answers, transcripts and documents are never here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.interviews import approved_set, full_name
from interview_assistant.models import (
    BankStatus,
    InterviewRound,
    JobPosting,
    QuestionBankItem,
    RubricExample,
)
from interview_assistant.retrieval.index import Doc


def competency_set_text(round_: InterviewRound) -> str | None:
    found = approved_set(round_)
    if found is None:
        return None
    posting = round_.posting
    lines = [f"- {c['name']}: {c.get('description', '')}" for c in found.competencies]
    return "\n".join(
        [f"직군: {posting.job_family}", f"공고: {posting.title}", f"차수: {full_name(round_)}", *lines]
    )


def posting_query(posting: JobPosting, round_: InterviewRound) -> str:
    """How a new posting's round asks for similar dictionaries: the same header plus its JD."""
    return "\n".join(
        [
            f"직군: {posting.job_family}",
            f"공고: {posting.title}",
            f"차수: {full_name(round_)}",
            posting.jd_text.strip(),
        ]
    )


def documents(db: Session) -> list[Doc]:
    docs: list[Doc] = []
    questions = db.scalars(
        select(QuestionBankItem).where(QuestionBankItem.status == BankStatus.approved)
    ).all()
    for item in questions:
        meta = {
            "job_family": item.job_family,
            "competency": item.competency,
            "round_position": item.round_position,
        }
        docs.append(Doc("question", item.id, 0, item.question, meta))
        for part, text in enumerate(item.follow_ups or [], start=1):
            if text.strip():
                docs.append(Doc("question", item.id, part, text.strip(), meta))
    examples = db.scalars(
        select(RubricExample).where(RubricExample.status == BankStatus.approved)
    ).all()
    for example in examples:
        meta = {
            "job_family": example.job_family,
            "competency": example.competency,
            "score": example.score,
        }
        docs.append(Doc("rubric", example.id, 0, example.answer, meta))
    for round_ in db.scalars(select(InterviewRound)).all():
        text = competency_set_text(round_)
        found = approved_set(round_)
        if text is None or found is None:
            continue
        meta = {
            "job_family": round_.posting.job_family,
            "posting_id": round_.posting_id,
            "round_id": round_.id,
            "round_position": round_.position,
        }
        docs.append(Doc("competency_set", found.id, 0, text, meta))
    return docs
