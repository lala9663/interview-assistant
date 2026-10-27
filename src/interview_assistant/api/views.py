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
    Step,
    approved_set,
    counts,
    current_decision,
    decision_history,
    earlier_sessions,
    first_round,
    is_last_round,
    latest_set,
    later_round_sessions,
    next_round,
    progress,
    round_session,
    rounds_of,
    session_competency_set,
    stage,
    submitted,
)
from interview_assistant.models import (
    ActorType,
    AiScoringStatus,
    Application,
    ApplicationChannel,
    AuditLog,
    Candidate,
    CheckPoint,
    CompetencySet,
    EvaluatorType,
    IntakeEvent,
    IntakeStatus,
    Interviewer,
    InterviewerRole,
    InterviewRound,
    InterviewSession,
    JobPosting,
    PresetQuestion,
    QAItem,
    RoundDecision,
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
    "round.decided",
    "round.decision_changed",
)


def candidate_ref(candidate: Candidate) -> s.CandidateRef:
    return s.CandidateRef(id=candidate.id, pseudonym=candidate.pseudonym)


def posting_ref(posting: JobPosting) -> s.PostingRefWithFamily:
    return s.PostingRefWithFamily(id=posting.id, title=posting.title, job_family=posting.job_family)


def round_ref(round_: InterviewRound) -> s.RoundRef:
    return s.RoundRef(
        id=round_.id,
        position=round_.position,
        label=round_.label,
        name=round_.name,
        is_last=is_last_round(round_),
    )


def round_view(round_: InterviewRound) -> s.RoundView:
    return s.RoundView(
        **round_ref(round_).model_dump(),
        rounds=len(round_.posting.rounds),
        show_previous_scores=round_.show_previous_scores,
    )


def round_entity(round_: InterviewRound) -> s.InterviewRound:
    return s.InterviewRound.model_validate(round_)


def round_summary(round_: InterviewRound) -> s.RoundSummary:
    approved = approved_set(round_)
    held = [
        x
        for a in round_.posting.applications
        for x in a.sessions
        if x.round_id == round_.id and x.status is not SessionStatus.cancelled
    ]
    decided = any(d.round_id == round_.id for a in round_.posting.applications for d in a.decisions)
    return s.RoundSummary(
        **round_entity(round_).model_dump(),
        is_last=is_last_round(round_),
        latest_competency_set=set_brief(latest_set(round_)),
        approved_competency_set=set_brief(approved),
        preset_count=len(approved.preset_questions) if approved else 0,
        sessions=len(held),
        locked=bool(held) or decided,
    )


def session_view(session: InterviewSession) -> s.InterviewSession:
    return s.InterviewSession(
        id=session.id,
        application_id=session.application_id,
        round_id=session.round_id,
        mode=session.mode,
        status=session.status,
        scheduled_at=session.scheduled_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        has_recording=session.recording_uri is not None,
        created_at=session.created_at,
    )


def brief(session: InterviewSession) -> s.SessionBrief:
    return s.SessionBrief(
        id=session.id,
        round=round_ref(session.round),
        status=session.status,
        mode=session.mode,
        scheduled_at=session.scheduled_at,
        ended_at=session.ended_at,
    )


def step_view(step: Step) -> s.ProgressStep:
    return s.ProgressStep(
        kind=step.kind,
        round=round_ref(step.round) if step.round is not None else None,
        status=step.status,
        at=step.at,
        session_id=step.session.id if step.session is not None else None,
    )


def round_status(session: InterviewSession) -> str:
    """The application's status in the session's round."""
    step = next(x for x in progress(session.application) if x.round is session.round)
    return step.status or "waiting"


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
        round=round_ref(session.round),
        round_status=round_status(session),
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


def posting_counts(posting: JobPosting) -> s.PostingCounts:
    tally = counts(posting)
    return s.PostingCounts(
        applications=tally.applications,
        passed=tally.passed,
        hold=tally.hold,
        rejected=tally.rejected,
        interviewing=tally.interviewing,
        interviewed=tally.interviewed,
        evaluated=tally.evaluated,
        rounds=[
            s.RoundCount(round=round_ref(t.round), reached=t.reached, **t.statuses)
            for t in tally.rounds
        ],
        final=tally.final,
    )


def posting_summary(posting: JobPosting) -> s.PostingSummary:
    first = first_round(posting)
    return s.PostingSummary(
        id=posting.id,
        title=posting.title,
        job_family=posting.job_family,
        status=posting.status,
        site_posting_no=posting.site_posting_no,
        created_at=posting.created_at,
        counts=posting_counts(posting),
        rounds=[round_ref(r) for r in rounds_of(posting)],
        latest_competency_set=set_brief(latest_set(first)) if first else None,
        approved_competency_set=set_brief(approved_set(first)) if first else None,
    )


def posting_detail(posting: JobPosting) -> s.PostingDetail:
    return s.PostingDetail(
        **s.JobPosting.model_validate(posting).model_dump(),
        counts=posting_counts(posting),
        rounds=[round_ref(r) for r in rounds_of(posting)],
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
        stage=step_view(stage(application)),
        progress=[step_view(x) for x in progress(application)],
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
        stage=step_view(stage(application)),
        progress=[step_view(x) for x in progress(application)],
        decisions=[
            decision_view(d)
            for d in sorted(
                application.decisions,
                key=lambda d: (d.round.position, d.revision),
                reverse=True,
            )
        ],
    )


def decision_view(row: RoundDecision) -> s.RoundDecision:
    return s.RoundDecision(
        id=row.id,
        application_id=row.application_id,
        round_id=row.round_id,
        session_id=row.session_id,
        revision=row.revision,
        decision=row.decision,
        reason=row.reason,
        decided_by=row.decided_by,
        decided_by_name=row.decider.name,
        created_at=row.created_at,
    )


def check_point_view(row: CheckPoint) -> s.CheckPoint:
    return s.CheckPoint(
        id=row.id,
        session_id=row.session_id,
        source=row.source,
        competency=row.competency,
        text=row.text,
        evidence=row.evidence,
        qa_item_id=row.qa_item_id,
        author_id=row.author_id,
        author_name=row.author.name if row.author else None,
        model=row.model,
        created_at=row.created_at,
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


def schedulable(
    applications: Iterable[Application], position: int | None = None
) -> list[s.SchedulableApplication]:
    """Applications waiting for their next round (round 1: passed screening; round N: passed
    round N-1), optionally only those waiting for the round at `position`."""
    rows = []
    for a in applications:
        waiting = next_round(a)
        if waiting is None or a.screening is None:
            continue
        if position is not None and waiting.position != position:
            continue
        steps = progress(a)
        before = steps[next(i for i, x in enumerate(steps) if x.round is waiting) - 1]
        rows.append(
            s.SchedulableApplication(
                application_id=a.id,
                candidate=candidate_ref(a.candidate),
                posting=posting_ref(a.posting),
                fit_score=a.screening.fit_score,
                round=round_ref(waiting),
                mode=waiting.default_mode,
                recommended_interviewers=waiting.recommended_interviewers,
                since=before.at,
            )
        )
    return rows


def competency_set(row: CompetencySet | None) -> s.CompetencySet | None:
    return s.CompetencySet.model_validate(row) if row else None


def preset_view(db: Session, row: PresetQuestion) -> s.PresetQuestion:
    origin = None
    if row.session_id is not None:
        earlier = db.get(QAItem, row.based_on_qa_item_id) if row.based_on_qa_item_id else None
        if earlier is not None:
            origin = s.CarryoverOrigin(
                round=round_ref(earlier.session.round),
                question=earlier.question,
                grounding=row.grounding or "",
                rationale=row.rationale or "",
                model=row.model,
            )
    return s.PresetQuestion(
        id=row.id,
        competency=row.competency,
        question=row.question,
        intent=row.intent,
        origin=origin,
    )


def _mean(values: Sequence[float]) -> float | None:
    return _round1(sum(values) / len(values)) if values else None


def previous_round(current: InterviewSession, earlier: InterviewSession) -> s.PreviousRound:
    """이전 차수 요약. Scores (and the decision reason) only when the current round shows them."""
    application = earlier.application
    decision = current_decision(application, earlier.round)
    visible = current.round.show_previous_scores
    scores = None
    if visible:
        names = list(
            dict.fromkeys(x.competency for x in earlier.scores)
        )  # first-seen order (rubric order for AI and interviewers alike)
        scores = [
            s.PreviousScore(
                competency=name,
                interviewer_mean=_mean(
                    [
                        x.score
                        for x in earlier.scores
                        if x.competency == name and x.evaluator_type is EvaluatorType.interviewer
                    ]
                ),
                ai_mean=_mean(
                    [
                        x.score
                        for x in earlier.scores
                        if x.competency == name and x.evaluator_type is EvaluatorType.ai
                    ]
                ),
            )
            for name in names
        ]
    return s.PreviousRound(
        round=round_ref(earlier.round),
        session=brief(earlier),
        decision=decision.decision if decision else None,
        qa_count=len(earlier.qa_items),
        check_points=[check_point_view(x) for x in earlier.check_points],
        notes=[
            s.PreviousNote(
                id=n.id, content=n.content, author_name=n.author.name, created_at=n.created_at
            )
            for n in sorted(earlier.notes, key=lambda n: as_utc(n.created_at))
        ],
        scores_visible=visible,
        scores=scores,
        decision_reason=decision.reason if decision and visible else None,
    )


def session_detail(db: Session, session: InterviewSession) -> s.SessionDetail:
    application = session.application
    candidate = application.candidate
    pinned = session_competency_set(db, session)
    return s.SessionDetail(
        session=session_view(session),
        posting=posting_ref(application.posting),
        round=round_view(session.round),
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
            previous_rounds=[previous_round(session, x) for x in earlier_sessions(session)],
        ),
        interviewers=panel(session),
        competency_set=competency_set(pinned),
        preset_questions=[preset_view(db, q) for q in pinned.preset_questions] if pinned else [],
        carryover_questions=[preset_view(db, q) for q in session.carryover_questions],
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
        round=round_view(session.round),
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
        decision=decision_panel(session),
        check_points=[check_point_view(x) for x in session.check_points],
    )


def decision_refusal(session: InterviewSession) -> str | None:
    """Why no decision can be recorded on this session's round now (None: it can)."""
    application = session.application
    if application.withdrawn_at is not None or application.deleted_at is not None:
        return "지원자가 철회한 지원서라 결정할 수 없습니다."
    if session.status is not SessionStatus.completed:
        return "면접이 끝난 뒤에 결정할 수 있습니다."
    if not submitted(session):
        return "면접관 점수가 모두 제출된 뒤에 결정할 수 있습니다."
    if round_session(application, session.round) is not session:
        return "이 차수의 최근 면접에서 결정하세요."
    later = later_round_sessions(application, session.round)
    if later:
        return f"{later[0].round.label} 면접이 이미 있어 {session.round.label} 결정을 바꿀 수 없습니다."
    return None


def decision_panel(session: InterviewSession) -> s.DecisionPanel:
    application = session.application
    round_ = session.round
    current = current_decision(application, round_)
    after = next((r for r in rounds_of(round_.posting) if r.position == round_.position + 1), None)
    refusal = decision_refusal(session)
    return s.DecisionPanel(
        current=decision_view(current) if current else None,
        history=[decision_view(d) for d in decision_history(application, round_)],
        can_decide=refusal is None,
        blocked_reason=refusal,
        is_last_round=is_last_round(round_),
        next_round=round_ref(after) if after else None,
    )


def pending_decisions(applications: Iterable[Application]) -> list[s.PendingDecision]:
    """Rounds evaluated and waiting for a decision, and those decided 보류, oldest first."""
    rows = []
    for a in applications:
        for step in progress(a):
            if step.kind != "round" or step.status not in ("deciding", "hold"):
                continue
            assert step.round is not None
            held = step.session or (step.decision.session if step.decision else None)
            if held is None:
                continue
            rows.append(
                s.PendingDecision(
                    session_id=held.id,
                    application_id=a.id,
                    candidate=candidate_ref(a.candidate),
                    posting=s.PostingRef(id=a.posting.id, title=a.posting.title),
                    round=round_ref(step.round),
                    status=step.status,
                    since=step.at,
                )
            )
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda r: as_utc(r.since) if r.since else epoch)


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
            return f"{cs.posting.title} {cs.round.label} v{cs.version}" if cs else None
        case "interview_round":
            found_round = db.get(InterviewRound, row.target_id)
            return f"{found_round.posting.title} {found_round.label}" if found_round else None
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
