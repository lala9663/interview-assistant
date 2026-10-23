"""면접관 스케줄 (FR-09): interviewers, availability, slot suggestions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import select

from interview_assistant import schedule
from interview_assistant.api import schemas as s
from interview_assistant.api.deps import Db, Me, audit
from interview_assistant.api.errors import invalid, not_found
from interview_assistant.models import (
    Availability,
    AvailabilitySource,
    Interviewer,
    InterviewSession,
    SessionStatus,
)
from interview_assistant.models.base import as_utc, utcnow

router = APIRouter(tags=["schedule"])

# Sessions have no end time until they run; a booked interview blocks this long.
BOOKED_MINUTES = 60


def _ms(value: datetime) -> int:
    return int(as_utc(value).timestamp() * 1000)


def _at(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@router.get("/interviewers", response_model=list[s.Interviewer])
def interviewers(db: Db) -> list[s.Interviewer]:
    rows = db.scalars(select(Interviewer).order_by(Interviewer.created_at, Interviewer.employee_no))
    return [s.Interviewer.model_validate(x) for x in rows]


@router.get("/availabilities", response_model=list[s.Availability])
def availabilities(
    db: Db,
    from_: AwareDatetime | None = Query(None, alias="from"),
    to: AwareDatetime | None = Query(None),
) -> list[s.Availability]:
    query = select(Availability).order_by(Availability.start_at)
    if from_ is not None:
        query = query.where(Availability.end_at > as_utc(from_))
    if to is not None:
        query = query.where(Availability.start_at < as_utc(to))
    return [s.Availability.model_validate(x) for x in db.scalars(query)]


@router.post("/availabilities", response_model=s.Availability, status_code=201)
def create_availability(body: s.CreateAvailabilityRequest, db: Db, me: Me) -> s.Availability:
    if db.get(Interviewer, body.interviewer_id) is None:
        raise not_found("면접관")
    if body.end_at <= body.start_at:
        raise invalid("end_at", "종료 시각은 시작 시각보다 늦어야 합니다.")
    created = Availability(
        interviewer_id=body.interviewer_id,
        start_at=as_utc(body.start_at),
        end_at=as_utc(body.end_at),
        source=AvailabilitySource.manual,
    )
    db.add(created)
    db.flush()
    audit(
        db,
        me,
        "availability.created",
        "interviewer",
        body.interviewer_id,
        availability_id=created.id,
    )
    db.commit()
    return s.Availability.model_validate(created)


@router.delete("/availabilities/{availability_id}", status_code=204)
def delete_availability(availability_id: str, db: Db, me: Me) -> Response:
    found = db.get(Availability, availability_id)
    if found is None:
        raise not_found("가용 시간")
    audit(
        db,
        me,
        "availability.deleted",
        "interviewer",
        found.interviewer_id,
        availability_id=found.id,
    )
    db.delete(found)
    db.commit()
    return Response(status_code=204)


@router.post("/schedule/suggestions", response_model=list[s.ScheduleSuggestion])
def suggestions(body: s.ScheduleSuggestionRequest, db: Db) -> list[s.ScheduleSuggestion]:
    if not body.interviewer_ids:
        raise invalid("interviewer_ids", "면접관을 한 명 이상 선택하세요.")
    start, end = as_utc(body.from_), as_utc(body.to)
    rows = db.scalars(
        select(Availability).where(
            Availability.interviewer_id.in_(body.interviewer_ids),
            Availability.end_at > start,
            Availability.start_at < end,
        )
    ).all()
    free: dict[str, list[schedule.Interval]] = {}
    for row in rows:
        free.setdefault(row.interviewer_id, []).append((_ms(row.start_at), _ms(row.end_at)))

    booked = db.scalars(
        select(InterviewSession).where(
            InterviewSession.status.in_([SessionStatus.scheduled, SessionStatus.in_progress]),
            InterviewSession.scheduled_at < end,
            InterviewSession.scheduled_at > start - timedelta(minutes=BOOKED_MINUTES),
        )
    ).all()
    busy: dict[str, list[schedule.Interval]] = {}
    for session in booked:
        begin = _ms(session.scheduled_at)
        for link in session.interviewers:
            busy.setdefault(link.interviewer_id, []).append(
                (begin, begin + BOOKED_MINUTES * schedule.MINUTE)
            )
    free = {i: schedule.subtract(v, busy.get(i, [])) for i, v in free.items()}

    slots = schedule.suggest_slots(
        free,
        body.interviewer_ids,
        body.duration_minutes,
        min_count=body.min_interviewers or len(body.interviewer_ids),
        start_from=max(_ms(start), _ms(utcnow())),
        until=_ms(end),
    )
    return [
        s.ScheduleSuggestion(start_at=_at(a), end_at=_at(b), interviewer_ids=ids)
        for a, b, ids in slots
    ]
