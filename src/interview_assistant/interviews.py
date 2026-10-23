"""Rules about postings, applications and sessions that several parts of the app share.

`stage` and `counts` follow docs/api-contract.md (서류 선별): a session is evaluated when AI scoring
completed and every interviewer on the panel submitted.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from interview_assistant.models import (
    AiScoringStatus,
    Application,
    CompetencySet,
    InterviewSession,
    JobPosting,
    SessionStatus,
)

Stage = Literal["screening", "interview_scheduled", "interviewing", "interviewed", "evaluated"]


def latest_set(posting: JobPosting) -> CompetencySet | None:
    return posting.competency_sets[-1] if posting.competency_sets else None


def approved_set(posting: JobPosting) -> CompetencySet | None:
    approved = [s for s in posting.competency_sets if s.approved_at is not None]
    return approved[-1] if approved else None


def session_competency_set(db: Session, session: InterviewSession) -> CompetencySet | None:
    """The version the session is pinned to (set when it starts), else the current approved one."""
    if session.competency_set is not None:
        return session.competency_set
    return approved_set(session.application.posting)


def is_evaluated(session: InterviewSession) -> bool:
    return session.ai_scoring_status is AiScoringStatus.completed and all(
        link.submitted_at is not None for link in session.interviewers
    )


def stage(application: Application) -> Stage:
    sessions = [s for s in application.sessions if s.status is not SessionStatus.cancelled]
    if any(s.status is SessionStatus.in_progress for s in sessions):
        return "interviewing"
    if any(s.status is SessionStatus.scheduled for s in sessions):
        return "interview_scheduled"
    done = [s for s in sessions if s.status is SessionStatus.completed]
    if not done:
        return "screening"
    return "evaluated" if all(is_evaluated(s) for s in done) else "interviewed"


def counts(posting: JobPosting) -> dict[str, int]:
    c = dict.fromkeys(
        ("applications", "passed", "hold", "rejected", "interviewing", "interviewed", "evaluated"),
        0,
    )
    for application in posting.applications:
        if application.deleted_at is not None:
            continue
        c["applications"] += 1
        if application.screening is not None:
            c[application.screening.status.value] += 1
        st = stage(application)
        if st in ("interview_scheduled", "interviewing"):
            c["interviewing"] += 1
        if st in ("interviewed", "evaluated"):
            c["interviewed"] += 1
        if st == "evaluated":
            c["evaluated"] += 1
    return c
