"""공통·대시보드: who is signed in, the dashboard digest, the activity feed."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from interview_assistant.api import schemas as s
from interview_assistant.api import views
from interview_assistant.api.deps import Db, Me
from interview_assistant.models import (
    Application,
    InterviewSession,
    JobPosting,
    PostingStatus,
    Screening,
    ScreeningStatus,
    SessionStatus,
)
from interview_assistant.models.base import utcnow

router = APIRouter(tags=["dashboard"])


@router.get("/me", response_model=s.Interviewer)
def me(me: Me) -> s.Interviewer:
    return s.Interviewer.model_validate(me)


@router.get("/dashboard", response_model=s.DashboardSummary)
def dashboard(db: Db, me: Me) -> s.DashboardSummary:
    now = utcnow()
    postings = db.scalars(
        select(JobPosting)
        .where(JobPosting.status != PostingStatus.closed)
        .order_by(JobPosting.created_at)
    ).all()
    sessions = db.scalars(select(InterviewSession)).all()
    today = [
        x
        for x in sessions
        if x.status is not SessionStatus.cancelled
        and x.scheduled_at
        and views.same_kst_day(x.scheduled_at, now)
    ]
    pending = [
        x
        for x in sessions
        if x.status is SessionStatus.completed
        and any(
            link.interviewer_id == me.id and link.submitted_at is None for link in x.interviewers
        )
    ]
    hold = db.scalar(
        select(func.count())
        .select_from(Screening)
        .join(Application)
        .where(Screening.status == ScreeningStatus.hold, Application.deleted_at.is_(None))
    )
    return s.DashboardSummary(
        pipeline=[
            s.PipelineRow(
                posting=s.PipelinePosting.model_validate(p),
                counts=views.posting_summary(p).counts,
            )
            for p in postings
        ],
        today_sessions=[
            views.session_summary(x) for x in views.sort_sessions(today, newest_first=False)
        ],
        pending_my_scores=[
            views.session_summary(x) for x in views.sort_sessions(pending, newest_first=True)
        ],
        hold_count=hold or 0,
    )


@router.get("/activity", response_model=list[s.ActivityItem])
def activity(db: Db, limit: int = Query(20, ge=1, le=100)) -> list[s.ActivityItem]:
    return views.feed(db, limit)
