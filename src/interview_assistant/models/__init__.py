"""ORM models. Import this package so every table is registered on `Base.metadata`."""

from interview_assistant.models.audit import ActorType, AuditLog
from interview_assistant.models.base import Base
from interview_assistant.models.deid import DeidCategory, DeidMapping
from interview_assistant.models.interview import (
    Availability,
    AvailabilitySource,
    CandidateNote,
    EvaluatorType,
    Interviewer,
    InterviewerRole,
    InterviewSession,
    QAItem,
    QuestionSource,
    Score,
    SessionInterviewer,
    SessionMode,
    SessionStatus,
)
from interview_assistant.models.recruiting import (
    Application,
    Candidate,
    CompetencySet,
    JobPosting,
    PostingStatus,
    Screening,
    ScreeningStatus,
)

__all__ = [
    "ActorType",
    "Application",
    "AuditLog",
    "Availability",
    "AvailabilitySource",
    "Base",
    "Candidate",
    "CandidateNote",
    "CompetencySet",
    "DeidCategory",
    "DeidMapping",
    "EvaluatorType",
    "Interviewer",
    "InterviewerRole",
    "InterviewSession",
    "JobPosting",
    "PostingStatus",
    "QAItem",
    "QuestionSource",
    "Score",
    "Screening",
    "ScreeningStatus",
    "SessionInterviewer",
    "SessionMode",
    "SessionStatus",
]
