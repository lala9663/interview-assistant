"""Rules about postings, rounds, applications and sessions that several parts of the app share.

An application moves through steps: 서류 (screening) → each interview round in order → 최종 (final
candidate). Round 1 is open to applications that passed screening; round N+1 to those a person
passed in round N. A round's status for an application comes from its newest session that was not
cancelled and its current decision:

    waiting      reached, no session yet (일정 대기)
    scheduled    session scheduled (예정)
    in_progress  session running (진행 중)
    evaluating   session ended, not every interviewer submitted (평가 대기)
    deciding     every interviewer submitted, no decision yet (결정 대기)
    passed / hold / rejected   the current decision (합격 / 보류 / 불합격)

A pass in the last round makes the application a final candidate; the official result is the
recruiting site's. `counts` follow docs/api-contract.md (서류 선별, 대시보드).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from interview_assistant.models import (
    AiScoringStatus,
    Application,
    CheckPoint,
    CompetencySet,
    InterviewRound,
    InterviewSession,
    JobPosting,
    RoundDecision,
    SessionStatus,
)
from interview_assistant.models.base import as_utc

StepKind = Literal["screening", "round", "final"]
StepStatus = Literal[
    "waiting", "scheduled", "in_progress", "evaluating", "deciding", "passed", "hold", "rejected"
]
STEP_STATUSES: tuple[StepStatus, ...] = (
    "waiting",
    "scheduled",
    "in_progress",
    "evaluating",
    "deciding",
    "passed",
    "hold",
    "rejected",
)

# Earlier rounds' answers given to the AI as context for later rounds (follow-ups, carry-over
# questions), newest last. Enough to see what was asked without crowding the prompt.
EARLIER_ROUND_ANSWERS = 8


# --- rounds and competency sets -------------------------------------------------------------


def rounds_of(posting: JobPosting) -> list[InterviewRound]:
    return sorted(posting.rounds, key=lambda r: r.position)


def first_round(posting: JobPosting) -> InterviewRound | None:
    ordered = rounds_of(posting)
    return ordered[0] if ordered else None


def is_last_round(round_: InterviewRound) -> bool:
    return round_.position == max(r.position for r in round_.posting.rounds)


def full_name(round_: InterviewRound) -> str:
    """"1차 직무 면접": the label, then the name."""
    return f"{round_.label} {round_.name}"


def latest_set(round_: InterviewRound) -> CompetencySet | None:
    return round_.competency_sets[-1] if round_.competency_sets else None


def approved_set(round_: InterviewRound) -> CompetencySet | None:
    approved = [s for s in round_.competency_sets if s.approved_at is not None]
    return approved[-1] if approved else None


def screening_set(posting: JobPosting) -> CompetencySet | None:
    """Screening judges documents against round 1's approved dictionary."""
    first = first_round(posting)
    return approved_set(first) if first is not None else None


def session_competency_set(db: Session, session: InterviewSession) -> CompetencySet | None:
    """The version the session is pinned to (set when it starts), else its round's approved one."""
    if session.competency_set is not None:
        return session.competency_set
    return approved_set(session.round)


# --- sessions and decisions -----------------------------------------------------------------


def submitted(session: InterviewSession) -> bool:
    """Every interviewer of the panel submitted their scores (평가 완료 for a decision)."""
    return bool(session.interviewers) and all(
        link.submitted_at is not None for link in session.interviewers
    )


def is_evaluated(session: InterviewSession) -> bool:
    return session.ai_scoring_status is AiScoringStatus.completed and all(
        link.submitted_at is not None for link in session.interviewers
    )


def round_session(application: Application, round_: InterviewRound) -> InterviewSession | None:
    """The application's newest session of the round that was not cancelled."""
    sessions = [
        s
        for s in application.sessions
        if s.round_id == round_.id and s.status is not SessionStatus.cancelled
    ]
    return max(sessions, key=lambda s: as_utc(s.created_at)) if sessions else None


def current_decision(application: Application, round_: InterviewRound) -> RoundDecision | None:
    revisions = [d for d in application.decisions if d.round_id == round_.id]
    return max(revisions, key=lambda d: d.revision) if revisions else None


def decision_history(application: Application, round_: InterviewRound) -> list[RoundDecision]:
    """Every revision, newest first."""
    return sorted(
        (d for d in application.decisions if d.round_id == round_.id),
        key=lambda d: d.revision,
        reverse=True,
    )


@dataclass(frozen=True)
class Step:
    kind: StepKind
    round: InterviewRound | None
    status: StepStatus | None  # None: not reached
    session: InterviewSession | None = None
    decision: RoundDecision | None = None
    at: datetime | None = None  # when the step got its status (screened, scheduled, ended, decided)


def _round_status(
    session: InterviewSession | None, decision: RoundDecision | None
) -> tuple[StepStatus, datetime | None]:
    if decision is not None:
        return decision.decision.value, decision.created_at
    if session is None:
        return "waiting", None
    match session.status:
        case SessionStatus.scheduled:
            return "scheduled", session.scheduled_at
        case SessionStatus.in_progress:
            return "in_progress", session.started_at
    return ("deciding" if submitted(session) else "evaluating"), session.ended_at


def progress(application: Application) -> list[Step]:
    """서류 → each round → 최종, in order. Steps after one that is not passed are not reached
    (status None) unless they already hold a session or a decision."""
    screening = application.screening
    steps = [
        Step(
            "screening",
            None,
            screening.status.value if screening is not None else "waiting",
            at=screening.created_at if screening is not None else None,
        )
    ]
    reached = screening is not None and screening.status.value == "passed"
    for round_ in rounds_of(application.posting):
        session = round_session(application, round_)
        decision = current_decision(application, round_)
        if reached or session is not None or decision is not None:
            status, at = _round_status(session, decision)
        else:
            status, at = None, None
        steps.append(Step("round", round_, status, session, decision, at))
        reached = reached and status == "passed"
    last = steps[-1]
    steps.append(Step("final", None, "passed" if reached else None, at=last.at if reached else None))
    return steps


def stage(application: Application) -> Step:
    """Where the application is now: the first step that is not passed, or 최종."""
    steps = progress(application)
    return next((s for s in steps if s.status != "passed"), steps[-1])


def next_round(application: Application) -> InterviewRound | None:
    """The round a session can be scheduled for now, if any."""
    now = stage(application)
    return now.round if now.kind == "round" and now.status == "waiting" else None


def schedule_refusal(application: Application, round_: InterviewRound) -> str | None:
    """Why a session of `round_` cannot be scheduled for the application (None: it can)."""
    steps = progress(application)
    index = next(i for i, s in enumerate(steps) if s.round is round_)
    step, before = steps[index], steps[index - 1]
    if step.session is not None:
        if step.session.status in (SessionStatus.scheduled, SessionStatus.in_progress):
            return f"이미 예정된 {round_.label} 면접이 있습니다."
        return f"{round_.label} 면접을 이미 마쳤습니다."
    if before.status != "passed":
        if before.kind == "screening":
            return "서류 통과한 지원서만 1차 면접을 잡을 수 있습니다."
        assert before.round is not None
        return f"{before.round.label} 합격자만 {round_.label} 면접을 잡을 수 있습니다."
    return None


def later_round_sessions(application: Application, round_: InterviewRound) -> list[InterviewSession]:
    return [
        s
        for s in application.sessions
        if s.round.position > round_.position and s.status is not SessionStatus.cancelled
    ]


# --- earlier rounds -------------------------------------------------------------------------


def earlier_sessions(session: InterviewSession) -> list[InterviewSession]:
    """The application's completed sessions of earlier rounds, oldest round first."""
    application = session.application
    found = []
    for round_ in rounds_of(application.posting):
        if round_.position >= session.round.position:
            break
        earlier = round_session(application, round_)
        if earlier is not None and earlier.status is SessionStatus.completed:
            found.append(earlier)
    return found


def earlier_round_qa(session: InterviewSession) -> list[tuple[str, str, str]]:
    """(round label, question, answer) of earlier rounds, de-identified as stored, newest last."""
    pairs = [
        (earlier.round.label, qa.question, qa.answer_deidentified)
        for earlier in earlier_sessions(session)
        for qa in earlier.qa_items
        if qa.answer_deidentified
    ]
    return pairs[-EARLIER_ROUND_ANSWERS:]


def earlier_check_points(session: InterviewSession) -> list[CheckPoint]:
    return [p for earlier in earlier_sessions(session) for p in earlier.check_points]


# --- counts ---------------------------------------------------------------------------------


@dataclass
class RoundTally:
    """How many applications reached a round, and how many are at each status in it."""

    round: InterviewRound
    reached: int = 0
    statuses: dict[str, int] = field(default_factory=lambda: dict.fromkeys(STEP_STATUSES, 0))


@dataclass
class PostingTally:
    applications: int = 0
    passed: int = 0
    hold: int = 0
    rejected: int = 0
    interviewing: int = 0  # the current step has a scheduled or running session
    interviewed: int = 0  # at least one session ended
    evaluated: int = 0  # every ended session AI-scored and submitted by its whole panel
    rounds: list[RoundTally] = field(default_factory=list)
    final: int = 0  # passed the last round (최종 합격 후보)


def counts(posting: JobPosting) -> PostingTally:
    tally = PostingTally(rounds=[RoundTally(r) for r in rounds_of(posting)])
    per_round = {t.round.id: t for t in tally.rounds}
    for application in posting.applications:
        if application.deleted_at is not None or application.withdrawn_at is not None:
            continue
        tally.applications += 1
        if application.screening is not None:
            status = application.screening.status.value
            setattr(tally, status, getattr(tally, status) + 1)
        steps = progress(application)
        for step in steps:
            if step.kind == "round" and step.status is not None and step.round is not None:
                per_round[step.round.id].reached += 1
                per_round[step.round.id].statuses[step.status] += 1
        tally.final += steps[-1].status == "passed"
        now = next((s for s in steps if s.status != "passed"), steps[-1])
        tally.interviewing += now.status in ("scheduled", "in_progress")
        done = [s for s in application.sessions if s.status is SessionStatus.completed]
        if done:
            tally.interviewed += 1
            tally.evaluated += all(is_evaluated(s) for s in done)
    return tally
