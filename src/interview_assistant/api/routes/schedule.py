"""면접관 스케줄 (FR-09): interviewers, availability, slot suggestions.

An interviewer's blocks never touch or overlap: writing one (create, update) merges in the blocks
it touches, and clearing part of one leaves it shorter or split in two.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import select

from interview_assistant import schedule
from interview_assistant.api import schemas as s
from interview_assistant.api.agent_access import agent_may_call
from interview_assistant.api.deps import Db, Me, audit
from interview_assistant.api.errors import invalid, not_found
from interview_assistant.models import (
    Availability,
    AvailabilitySource,
    Interviewer,
    InterviewSession,
    SessionStatus,
)
from interview_assistant.models.base import as_utc, iso_z, utcnow

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


def _absorb(
    db: Db, interviewer_id: str, start: datetime, end: datetime, but: str | None = None
) -> tuple[datetime, datetime, list[str]]:
    """Deletes the interviewer's blocks that touch start–end (other than `but`) and returns the
    range they make together with it (schedule.absorb), so one person's blocks never overlap."""
    query = select(Availability).where(Availability.interviewer_id == interviewer_id)
    if but is not None:
        query = query.where(Availability.id != but)
    others = {row.id: row for row in db.scalars(query)}
    (a, b), ids = schedule.absorb(
        {i: (_ms(r.start_at), _ms(r.end_at)) for i, r in others.items()}, (_ms(start), _ms(end))
    )
    for i in ids:
        db.delete(others[i])
    return _at(a), _at(b), ids


def _range(row: Availability) -> list[str]:
    return [iso_z(row.start_at), iso_z(row.end_at)]


@router.post("/availabilities", response_model=s.Availability, status_code=201)
def create_availability(body: s.CreateAvailabilityRequest, db: Db, me: Me) -> s.Availability:
    if db.get(Interviewer, body.interviewer_id) is None:
        raise not_found("면접관")
    if body.end_at <= body.start_at:
        raise invalid("end_at", "종료 시각은 시작 시각보다 늦어야 합니다.")
    start, end, merged = _absorb(
        db, body.interviewer_id, as_utc(body.start_at), as_utc(body.end_at)
    )
    created = Availability(
        interviewer_id=body.interviewer_id,
        start_at=start,
        end_at=end,
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
        **({"merged": merged} if merged else {}),
    )
    db.commit()
    return s.Availability.model_validate(created)


@router.patch("/availabilities/{availability_id}", response_model=s.Availability)
def update_availability(
    availability_id: str, body: s.UpdateAvailabilityRequest, db: Db, me: Me
) -> s.Availability:
    found = db.get(Availability, availability_id)
    if found is None:
        raise not_found("가용 시간")
    start = as_utc(body.start_at or found.start_at)
    end = as_utc(body.end_at or found.end_at)
    if end <= start:
        raise invalid("end_at", "종료 시각은 시작 시각보다 늦어야 합니다.")
    before = _range(found)
    start, end, merged = _absorb(db, found.interviewer_id, start, end, but=found.id)
    found.start_at, found.end_at = start, end
    if _range(found) != before or merged:
        audit(
            db,
            me,
            "availability.updated",
            "interviewer",
            found.interviewer_id,
            availability_id=found.id,
            **{"from": before, "to": _range(found)},
            **({"merged": merged} if merged else {}),
        )
        db.commit()
    return s.Availability.model_validate(found)


@router.post("/availabilities/{availability_id}/clear", response_model=list[s.Availability])
def clear_availability(
    availability_id: str, body: s.ClearAvailabilityRequest, db: Db, me: Me
) -> list[s.Availability]:
    """Takes start–end out of one block: it gets shorter, splits in two or goes."""
    found = db.get(Availability, availability_id)
    if found is None:
        raise not_found("가용 시간")
    if body.end_at <= body.start_at:
        raise invalid("end_at", "종료 시각은 시작 시각보다 늦어야 합니다.")
    whole = (_ms(found.start_at), _ms(found.end_at))
    pieces = schedule.subtract([whole], [(_ms(body.start_at), _ms(body.end_at))])
    if pieces == [whole]:
        return [s.Availability.model_validate(found)]
    cleared = [iso_z(body.start_at), iso_z(body.end_at)]
    if not pieces:
        audit(
            db,
            me,
            "availability.deleted",
            "interviewer",
            found.interviewer_id,
            availability_id=found.id,
            cleared=cleared,
        )
        db.delete(found)
        db.commit()
        return []
    (a, b), *rest = pieces
    before = _range(found)
    found.start_at, found.end_at = _at(a), _at(b)
    audit(
        db,
        me,
        "availability.updated",
        "interviewer",
        found.interviewer_id,
        availability_id=found.id,
        **{"from": before, "to": _range(found)},
        cleared=cleared,
    )
    kept = [found]
    for a, b in rest:  # at most one: the part after the cleared time
        piece = Availability(
            interviewer_id=found.interviewer_id, start_at=_at(a), end_at=_at(b), source=found.source
        )
        db.add(piece)
        db.flush()
        audit(
            db,
            me,
            "availability.created",
            "interviewer",
            found.interviewer_id,
            availability_id=piece.id,
            split_from=found.id,
        )
        kept.append(piece)
    db.commit()
    return [s.Availability.model_validate(x) for x in kept]


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
@agent_may_call
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
