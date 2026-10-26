"""ORM rows -> response bodies. The only place that decides what of a row the API shows."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from interview_assistant.ai.prompts import SCORING_PROMPT
from interview_assistant.ai.scoring import SAMPLES
from interview_assistant.api import schemas as s
from interview_assistant.interviews import (
    approved_set,
    counts,
    latest_set,
    session_competency_set,
    stage,
)
from interview_assistant.models import (
    ActorType,
    AiScoringStatus,
    Application,
    ApplicationChannel,
    AuditLog,
    Candidate,
    CompetencySet,
    EvaluatorType,
    IntakeEvent,
    IntakeStatus,
    Interviewer,
    InterviewerRole,
    InterviewSession,
    JobPosting,
    Score,
    Screening,
    SessionInterviewer,
    SessionStatus,
    TranscriptSegment,
)
from interview_assistant.models.base import as_utc

KST = timezone(timedelta(hours=9))

# Audit actions people read in the dashboard feed. Everything else (each AI call, de-identification
# lookups, availability edits ...) stays in the audit log only.
FEED_ACTIONS = (
    "screening.batch_completed",
    "screening.status_changed",
    "competency_set.generated",
    "competency_set.created",
    "competency_set.updated",
    "competency_set.approved",
    "consent.recorded",
    "session.scheduled",
    "session.started",
    "session.completed",
    "qa.created",
    "score.ai_started",
    "score.ai_completed",
    "score.interviewer_submitted",
)


def candidate_ref(candidate: Candidate) -> s.CandidateRef:
    return s.CandidateRef(id=candidate.id, pseudonym=candidate.pseudonym)


def posting_ref(posting: JobPosting) -> s.PostingRefWithFamily:
    return s.PostingRefWithFamily(id=posting.id, title=posting.title, job_family=posting.job_family)


def session_view(session: InterviewSession) -> s.InterviewSession:
    return s.InterviewSession(
        id=session.id,
        application_id=session.application_id,
        mode=session.mode,
        status=session.status,
        scheduled_at=session.scheduled_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        has_recording=session.recording_uri is not None,
        created_at=session.created_at,
    )


def brief(session: InterviewSession) -> s.SessionBrief:
    return s.SessionBrief.model_validate(session)


def panel_links(session: InterviewSession) -> list[SessionInterviewer]:
    return sorted(session.interviewers, key=lambda link: link.role is not InterviewerRole.lead)


def panel(session: InterviewSession) -> list[s.SessionInterviewerView]:
    return [
        s.SessionInterviewerView(
            session_id=link.session_id,
            interviewer_id=link.interviewer_id,
            role=link.role,
            interviewer=s.Interviewer.model_validate(link.interviewer),
        )
        for link in panel_links(session)
    ]


def session_summary(session: InterviewSession) -> s.SessionSummary:
    application = session.application
    return s.SessionSummary(
        **session_view(session).model_dump(),
        candidate=candidate_ref(application.candidate),
        posting=s.PostingRef(id=application.posting.id, title=application.posting.title),
        interviewers=panel(session),
        qa_count=len(session.qa_items),
        ai_scoring=session.ai_scoring_status.value,
        submitted_interviewer_ids=[
            link.interviewer_id for link in panel_links(session) if link.submitted_at is not None
        ],
    )


def sort_sessions(
    sessions: Iterable[InterviewSession], *, newest_first: bool
) -> list[InterviewSession]:
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def key(x: InterviewSession) -> datetime:
        return as_utc(x.scheduled_at) if x.scheduled_at else epoch

    return sorted(sessions, key=key, reverse=newest_first)


def set_brief(competency_set: CompetencySet | None) -> s.CompetencySetBrief | None:
    return s.CompetencySetBrief.model_validate(competency_set) if competency_set else None


def posting_summary(posting: JobPosting) -> s.PostingSummary:
    return s.PostingSummary(
        id=posting.id,
        title=posting.title,
        job_family=posting.job_family,
        status=posting.status,
        site_posting_no=posting.site_posting_no,
        created_at=posting.created_at,
        counts=s.PostingCounts(**counts(posting)),
        latest_competency_set=set_brief(latest_set(posting)),
        approved_competency_set=set_brief(approved_set(posting)),
    )


def posting_detail(posting: JobPosting) -> s.PostingDetail:
    return s.PostingDetail(
        **s.JobPosting.model_validate(posting).model_dump(),
        counts=s.PostingCounts(**counts(posting)),
    )


def screening(row: Screening | None) -> s.Screening | None:
    return s.Screening.model_validate(row) if row else None


def application_row(application: Application) -> s.ApplicationRow:
    profile = application.profile or {}
    return s.ApplicationRow(
        application_id=application.id,
        candidate=candidate_ref(application.candidate),
        screening=screening(application.screening),
        years_experience=profile.get("years_experience") if application.profile else None,
        top_skills=list(profile.get("skills") or [])[:3],
        stage=stage(application),
        channel=application.channel.value,
        created_at=application.created_at,
    )


def document_info(application: Application) -> s.DocumentInfo | None:
    info = application.document_info
    return s.DocumentInfo.model_validate(info) if info else None


def application_detail(application: Application) -> s.ApplicationDetail:
    return s.ApplicationDetail(
        application=s.Application.model_validate(application),
        candidate=s.Candidate.model_validate(application.candidate),
        posting=posting_ref(application.posting),
        screening=screening(application.screening),
        sessions=[brief(x) for x in sort_sessions(application.sessions, newest_first=False)],
        document=document_info(application),
    )


def candidate_index(applications: Iterable[Application]) -> list[s.CandidateIndexItem]:
    return [
        s.CandidateIndexItem(
            candidate_id=a.candidate.id,
            pseudonym=a.candidate.pseudonym,
            application_id=a.id,
            posting_id=a.posting.id,
            posting_title=a.posting.title,
            screening_status=a.screening.status if a.screening else None,
            fit_score=a.screening.fit_score if a.screening else None,
        )
        for a in applications
    ]


def schedulable(applications: Iterable[Application]) -> list[s.SchedulableApplication]:
    active = (SessionStatus.scheduled, SessionStatus.in_progress, SessionStatus.completed)
    return [
        s.SchedulableApplication(
            application_id=a.id,
            candidate=candidate_ref(a.candidate),
            posting=posting_ref(a.posting),
            fit_score=a.screening.fit_score,
        )
        for a in applications
        if a.screening is not None
        and a.screening.status.value == "passed"
        and not any(x.status in active for x in a.sessions)
    ]


def competency_set(row: CompetencySet | None) -> s.CompetencySet | None:
    return s.CompetencySet.model_validate(row) if row else None


def session_detail(db: Session, session: InterviewSession) -> s.SessionDetail:
    application = session.application
    candidate = application.candidate
    pinned = session_competency_set(db, session)
    return s.SessionDetail(
        session=session_view(session),
        posting=posting_ref(application.posting),
        card=s.CandidateCard(
            candidate=s.CardCandidate.model_validate(candidate),
            profile=application.profile,
            screening=(
                s.CardScreening.model_validate(application.screening)
                if application.screening
                else None
            ),
            previous_sessions=[
                brief(x)
                for x in sort_sessions(application.sessions, newest_first=False)
                if x.id != session.id and x.status is SessionStatus.completed
            ],
        ),
        interviewers=panel(session),
        competency_set=competency_set(pinned),
        preset_questions=[s.PresetQuestion.model_validate(q) for q in pinned.preset_questions]
        if pinned
        else [],
        qa_items=[s.QAItem.model_validate(q) for q in session.qa_items],
        notes=[
            s.CandidateNote.model_validate(n)
            for n in sorted(session.notes, key=lambda n: as_utc(n.created_at))
        ],
    )


def transcript(segments: Sequence[TranscriptSegment]) -> s.TranscriptHistory:
    return s.TranscriptHistory(
        segments=[
            s.TranscriptSegment(
                segment_id=seg.id,
                qa_item_id=seg.qa_item_id,
                speaker=seg.speaker.value,
                text=seg.text_deidentified,
                is_final=True,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
            )
            for seg in segments
        ]
    )


def _round1(value: float) -> float:
    """Half-up to one decimal, as the frontend's round1 does (Python's round is half-even)."""
    return math.floor(value * 10 + 0.5) / 10


def ai_summary(scores: Sequence[Score]) -> list[s.AiCompetencySummary]:
    """Mean AI item score per competency and the lowest confidence. AI scores only: interviewer
    scores are never mixed in (FR-07)."""
    groups: dict[str, list[Score]] = {}
    for score in scores:
        if score.evaluator_type is EvaluatorType.ai:
            groups.setdefault(score.competency, []).append(score)
    return [
        s.AiCompetencySummary(
            competency=name,
            score=_round1(sum(x.score for x in rows) / len(rows)),
            confidence=min(x.confidence or 0 for x in rows),
            item_count=len(rows),
        )
        for name, rows in groups.items()
    ]


def evaluation(db: Session, session: InterviewSession, configured_model: str) -> s.Evaluation:
    application = session.application
    status = session.ai_scoring_status
    qa_order = {q.id: q.seq for q in session.qa_items}
    ai_scores = sorted(
        (x for x in session.scores if x.evaluator_type is EvaluatorType.ai),
        key=lambda x: (qa_order.get(x.qa_item_id or "", 0), x.competency),
    )
    if status is not AiScoringStatus.completed:
        ai_scores = []
    model = ai_scores[0].model if ai_scores else None
    if model is None and status is not AiScoringStatus.not_started:
        model = configured_model
    return s.Evaluation(
        session=session_view(session),
        candidate=candidate_ref(application.candidate),
        posting=s.PostingRef(id=application.posting.id, title=application.posting.title),
        competency_set=competency_set(session_competency_set(db, session)),
        qa_items=[s.QAItem.model_validate(q) for q in session.qa_items],
        ai=s.AiEvaluation(
            status=status.value,
            model=model,
            prompt_version=None if status is AiScoringStatus.not_started else SCORING_PROMPT,
            samples=SAMPLES,
            scores=[s.Score.model_validate(x) for x in ai_scores],
            summary=ai_summary(ai_scores),
        ),
        interviewers=[
            s.InterviewerEvaluation(
                interviewer=s.Interviewer.model_validate(link.interviewer),
                role=link.role,
                submitted_at=link.submitted_at,
                scores=[
                    s.Score.model_validate(x)
                    for x in session.scores
                    if x.evaluator_type is EvaluatorType.interviewer
                    and x.evaluator_id == link.interviewer_id
                ],
            )
            for link in panel_links(session)
        ],
    )


def same_kst_day(a: datetime, b: datetime) -> bool:
    return as_utc(a).astimezone(KST).date() == as_utc(b).astimezone(KST).date()


def activity(db: Session, rows: Sequence[AuditLog]) -> list[s.ActivityItem]:
    return [
        s.ActivityItem(
            **s.AuditLog.model_validate(row).model_dump(),
            actor_label=_actor_label(db, row),
            target_label=_target_label(db, row),
        )
        for row in rows
    ]


def _actor_label(db: Session, row: AuditLog) -> str:
    if row.actor_type is ActorType.ai:
        return "AI"
    if row.actor_type is ActorType.system:
        return "시스템"
    person = db.get(Interviewer, row.actor_id) if row.actor_id else None
    return person.name if person else "사용자"


def _target_label(db: Session, row: AuditLog) -> str | None:
    if not row.target_id:
        return None
    match row.target_type:
        case "interview_session":
            session = db.get(InterviewSession, row.target_id)
            return session.application.candidate.pseudonym if session else None
        case "screening":
            found = db.get(Screening, row.target_id)
            return found.application.candidate.pseudonym if found else None
        case "application":
            application = db.get(Application, row.target_id)
            return application.candidate.pseudonym if application else None
        case "competency_set":
            cs = db.get(CompetencySet, row.target_id)
            return f"{cs.posting.title} v{cs.version}" if cs else None
        case "job_posting":
            posting = db.get(JobPosting, row.target_id)
            return posting.title if posting else None
    return None


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, round((as_utc(end) - as_utc(start)).total_seconds() * 1000))


def intake_event(row: IntakeEvent, linked: dict[str, JobPosting] | None = None) -> s.IntakeEvent:
    """A site event for 연동 현황: the pseudonym once a candidate is known, never the name or
    the applicant number (neither is stored). `linked` (site posting number -> posting) names the
    posting of events that never got as far as resolving it."""
    candidate = row.candidate or (row.application.candidate if row.application else None)
    posting = row.posting or (linked or {}).get(row.posting_no or "")
    return s.IntakeEvent(
        id=row.id,
        event_id=row.event_id,
        event_type=row.event_type.value if row.event_type else None,
        status=row.status.value,
        revision=row.revision,
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        processing_ms=_ms(row.started_at, row.finished_at),
        attempts=row.attempts,
        posting_no=row.posting_no,
        posting=s.PostingRef(id=posting.id, title=posting.title) if posting else None,
        application_no=row.application_no,
        candidate=candidate_ref(candidate) if candidate else None,
        failure=(
            s.IntakeFailure(
                code=row.failure_code,
                message=row.failure_message or "",
                fields=list(row.failure_fields or []),
            )
            if row.failure_code
            else None
        ),
        dropped_fields=list(row.dropped_fields or []),
        retriable=row.status is IntakeStatus.failed and row.encrypted_payload is not None,
        result=row.result,
    )


def _percentile(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(share * len(ordered)) - 1)]


def linked_postings(db: Session) -> dict[str, JobPosting]:
    return {p.site_posting_no: p for p in db.scalars(select(JobPosting)).all() if p.site_posting_no}


def intake_summary(db: Session, *, configured: bool, workers: int) -> s.IntakeSummary:
    rows = db.scalars(select(IntakeEvent).where(IntakeEvent.channel == ApplicationChannel.site)).all()
    postings = linked_postings(db)
    for row in rows:  # a row resolved to a posting since unlinked still counts under it
        if row.posting is not None and row.posting_no and row.posting_no not in postings:
            postings[row.posting_no] = row.posting
    totals = dict.fromkeys(s.IntakeTotals.model_fields, 0)
    per: dict[str | None, dict[str, int]] = {}
    failures: dict[str, list[int]] = {}
    for row in rows:
        totals["received"] += 1
        totals[row.status.value] += 1
        c = per.setdefault(
            row.posting_no,
            dict.fromkeys(("received", "submitted", "updated", "withdrawn", "done", "skipped", "failed", "rejected", "pending"), 0),
        )
        c["received"] += 1
        if row.event_type is not None:
            c[row.event_type.value] += 1
        if row.status in (IntakeStatus.queued, IntakeStatus.processing):
            c["pending"] += 1
        else:
            c[row.status.value] += 1
        if row.status in (IntakeStatus.failed, IntakeStatus.rejected) and row.failure_code:
            entry = failures.setdefault(row.failure_code, [0, 0])
            entry[0] += 1
            entry[1] += row.status is IntakeStatus.failed and row.encrypted_payload is not None
    active = Counter(
        a.posting_id
        for a in db.scalars(
            select(Application).where(
                Application.channel == ApplicationChannel.site,
                Application.withdrawn_at.is_(None),
                Application.deleted_at.is_(None),
            )
        ).all()
    )
    posting_rows = []
    for number in sorted(per, key=lambda n: (n is None, n not in postings, n or "")):
        posting = postings.get(number)
        posting_rows.append(
            s.IntakePostingCount(
                posting_no=number,
                posting=s.PostingRef(id=posting.id, title=posting.title) if posting else None,
                applications=active.get(posting.id, 0) if posting else 0,
                **per[number],
            )
        )
    for number, posting in postings.items():  # linked postings with nothing received yet
        if number not in per:
            posting_rows.append(
                s.IntakePostingCount(
                    posting_no=number,
                    posting=s.PostingRef(id=posting.id, title=posting.title),
                    applications=active.get(posting.id, 0),
                    **dict.fromkeys(("received", "submitted", "updated", "withdrawn", "done", "skipped", "failed", "rejected", "pending"), 0),
                )
            )

    applied = [r for r in rows if r.status in (IntakeStatus.done, IntakeStatus.skipped) and r.started_at and r.finished_at]
    took = [m for r in applied if (m := _ms(r.started_at, r.finished_at)) is not None]
    waited = [m for r in applied if (m := _ms(r.received_at, r.started_at)) is not None]
    first = min((as_utc(r.received_at) for r in applied), default=None)
    last = max((as_utc(r.finished_at) for r in applied if r.finished_at), default=None)
    minutes = (last - first).total_seconds() / 60 if first and last and last > first else None
    return s.IntakeSummary(
        configured=configured,
        workers=workers,
        totals=s.IntakeTotals(**totals),
        postings=posting_rows,
        failures=[
            s.IntakeFailureCount(code=code, count=n, retriable=r)
            for code, (n, r) in sorted(failures.items(), key=lambda kv: -kv[1][0])
        ],
        timing=s.IntakeTiming(
            processed=len(took),
            avg_ms=round(sum(took) / len(took)) if took else None,
            p50_ms=_percentile(took, 0.5),
            p95_ms=_percentile(took, 0.95),
            max_ms=max(took, default=None),
            avg_wait_ms=round(sum(waited) / len(waited)) if waited else None,
            first_received_at=first,
            last_finished_at=last,
            per_minute=round(len(applied) / minutes, 1) if minutes else None,
        ),
    )


def feed(db: Session, limit: int) -> list[s.ActivityItem]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(FEED_ACTIONS))
        .order_by(AuditLog.occurred_at.desc())
        .limit(limit)
    ).all()
    return activity(db, rows)
