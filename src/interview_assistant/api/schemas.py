"""Request and response bodies, field for field what `frontend/src/api/types.ts` declares.

Raw-zone fields have no place here: `Candidate.encrypted_identity`, `Application.source_file_uri`,
`InterviewSession.recording_uri` (only `has_recording`) and `QAItem.answer_text` (only
`answer_deidentified`; manual answers come in as `answer_text` and are de-identified first).
Datetimes go out as UTC ISO 8601 with milliseconds and `Z`; incoming ones must carry an offset.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

from interview_assistant.domain import CandidateProfile, Competency
from interview_assistant.models import (
    ActorType,
    AvailabilitySource,
    EvaluatorType,
    InterviewerRole,
    PostingStatus,
    QuestionSource,
    ScreeningStatus,
    SessionMode,
    SessionStatus,
)
from interview_assistant.models.base import iso_z

Timestamp = Annotated[datetime, PlainSerializer(iso_z, return_type=str, when_used="json")]
AiScoringState = Literal["not_started", "running", "completed", "failed"]
Stage = Literal["screening", "interview_scheduled", "interviewing", "interviewed", "evaluated"]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- 1. entities --------------------------------------------------------------------------


class JobPosting(Schema):
    id: str
    title: str
    job_family: str
    jd_text: str
    status: PostingStatus
    created_at: Timestamp


class CompetencySet(Schema):
    id: str
    posting_id: str
    version: int
    competencies: list[Competency]
    approved_by: str | None
    approved_at: Timestamp | None
    created_at: Timestamp


class Candidate(Schema):
    id: str
    pseudonym: str
    consent_recording: bool
    consent_at: Timestamp | None
    deleted_at: Timestamp | None
    created_at: Timestamp


class Application(Schema):
    id: str
    candidate_id: str
    posting_id: str
    profile: CandidateProfile | None
    deleted_at: Timestamp | None
    created_at: Timestamp


class Screening(Schema):
    id: str
    application_id: str
    fit_score: float
    rationale: str
    status: ScreeningStatus
    model: str | None
    prompt_version: str | None
    created_at: Timestamp


class Interviewer(Schema):
    id: str
    employee_no: str
    name: str
    job_family: str | None
    department: str | None
    created_at: Timestamp


class InterviewSession(Schema):
    id: str
    application_id: str
    mode: SessionMode
    status: SessionStatus
    scheduled_at: Timestamp | None
    started_at: Timestamp | None
    ended_at: Timestamp | None
    has_recording: bool
    created_at: Timestamp


class SessionInterviewer(Schema):
    session_id: str
    interviewer_id: str
    role: InterviewerRole


class QAItem(Schema):
    id: str
    session_id: str
    seq: int
    question: str
    question_source: QuestionSource
    answer_deidentified: str | None
    asked_at: Timestamp | None
    answered_at: Timestamp | None
    created_at: Timestamp


class Score(Schema):
    id: str
    # AI scores belong to an answer; interviewer scores are per session (null here).
    qa_item_id: str | None
    competency: str
    score: int
    evidence: str | None
    confidence: float | None
    evaluator_type: EvaluatorType
    evaluator_id: str | None
    model: str | None
    prompt_version: str | None
    created_at: Timestamp


class CandidateNote(Schema):
    id: str
    session_id: str
    author_id: str
    content: str
    created_at: Timestamp


class Availability(Schema):
    id: str
    interviewer_id: str
    start_at: Timestamp
    end_at: Timestamp
    source: AvailabilitySource
    created_at: Timestamp


class AuditLog(Schema):
    id: str
    occurred_at: Timestamp
    actor_type: ActorType
    actor_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    model: str | None
    prompt_version: str | None
    details: dict[str, Any] | None


# --- 2. view models -----------------------------------------------------------------------


class CandidateRef(Schema):
    id: str
    pseudonym: str


class PostingRef(Schema):
    id: str
    title: str


class PostingRefWithFamily(PostingRef):
    job_family: str


class PostingCounts(BaseModel):
    applications: int
    passed: int
    hold: int
    rejected: int
    interviewing: int
    interviewed: int
    evaluated: int


class CompetencySetBrief(Schema):
    id: str
    version: int
    approved_at: Timestamp | None


class PostingSummary(Schema):
    id: str
    title: str
    job_family: str
    status: PostingStatus
    created_at: Timestamp
    counts: PostingCounts
    latest_competency_set: CompetencySetBrief | None
    approved_competency_set: CompetencySetBrief | None


class PostingDetail(JobPosting):
    counts: PostingCounts


class ApplicationRow(BaseModel):
    application_id: str
    candidate: CandidateRef
    screening: Screening | None
    years_experience: float | None
    top_skills: list[str]
    stage: Stage
    created_at: Timestamp


class SessionBrief(Schema):
    id: str
    status: SessionStatus
    mode: SessionMode
    scheduled_at: Timestamp | None
    ended_at: Timestamp | None


class DocumentInfo(BaseModel):
    """What an uploaded file held, counts only. Hidden blocks were left out of screening."""

    format: str
    blocks: int
    hidden_blocks: int
    images_dropped: int
    replacements: int


class ApplicationDetail(BaseModel):
    application: Application
    candidate: Candidate
    posting: PostingRefWithFamily
    screening: Screening | None
    sessions: list[SessionBrief]
    document: DocumentInfo | None


class UploadResult(BaseModel):
    application_id: str
    candidate: CandidateRef
    screening: Screening
    document: DocumentInfo


class CandidateIndexItem(BaseModel):
    candidate_id: str
    pseudonym: str
    application_id: str
    posting_id: str
    posting_title: str
    screening_status: ScreeningStatus | None
    fit_score: float | None


class SchedulableApplication(BaseModel):
    application_id: str
    candidate: CandidateRef
    posting: PostingRefWithFamily
    fit_score: float


class SessionInterviewerView(SessionInterviewer):
    interviewer: Interviewer


class SessionSummary(InterviewSession):
    candidate: CandidateRef
    posting: PostingRef
    interviewers: list[SessionInterviewerView]
    qa_count: int
    ai_scoring: AiScoringState
    submitted_interviewer_ids: list[str]


class PresetQuestion(Schema):
    id: str
    competency: str
    question: str
    intent: str


class CardCandidate(Schema):
    id: str
    pseudonym: str
    consent_recording: bool
    consent_at: Timestamp | None


class CardScreening(Schema):
    fit_score: float
    status: ScreeningStatus
    rationale: str


class CandidateCard(BaseModel):
    candidate: CardCandidate
    profile: CandidateProfile | None
    screening: CardScreening | None
    previous_sessions: list[SessionBrief]


class SessionDetail(BaseModel):
    session: InterviewSession
    posting: PostingRefWithFamily
    card: CandidateCard
    interviewers: list[SessionInterviewerView]
    competency_set: CompetencySet | None
    preset_questions: list[PresetQuestion]
    qa_items: list[QAItem]
    notes: list[CandidateNote]


class TranscriptSegment(BaseModel):
    segment_id: str
    qa_item_id: str | None
    speaker: Literal["interviewer", "candidate"]
    text: str
    is_final: bool
    start_ms: int
    end_ms: int | None


class TranscriptHistory(BaseModel):
    segments: list[TranscriptSegment]


class AiCompetencySummary(BaseModel):
    competency: str
    score: float
    confidence: float
    item_count: int


class AiEvaluation(BaseModel):
    status: AiScoringState
    model: str | None
    prompt_version: str | None
    samples: int
    scores: list[Score]
    summary: list[AiCompetencySummary]


class InterviewerEvaluation(BaseModel):
    interviewer: Interviewer
    role: InterviewerRole
    submitted_at: Timestamp | None
    scores: list[Score]


class Evaluation(BaseModel):
    session: InterviewSession
    candidate: CandidateRef
    posting: PostingRef
    competency_set: CompetencySet | None
    qa_items: list[QAItem]
    ai: AiEvaluation
    interviewers: list[InterviewerEvaluation]


class PipelinePosting(Schema):
    id: str
    title: str
    job_family: str
    status: PostingStatus


class PipelineRow(BaseModel):
    posting: PipelinePosting
    counts: PostingCounts


class DashboardSummary(BaseModel):
    pipeline: list[PipelineRow]
    today_sessions: list[SessionSummary]
    pending_my_scores: list[SessionSummary]
    hold_count: int


class ActivityItem(AuditLog):
    actor_label: str
    target_label: str | None


class ScheduleSuggestion(BaseModel):
    start_at: Timestamp
    end_at: Timestamp
    interviewer_ids: list[str]


# --- requests -----------------------------------------------------------------------------


class CompetenciesBody(BaseModel):
    competencies: list[Competency]


class ScreeningUpdate(BaseModel):
    status: ScreeningStatus


class PanelMember(BaseModel):
    interviewer_id: str
    role: InterviewerRole


class CreateSessionRequest(BaseModel):
    application_id: str
    mode: SessionMode
    scheduled_at: AwareDatetime
    interviewers: list[PanelMember]


class ConsentRequest(BaseModel):
    consent_recording: bool


class SuggestionUse(BaseModel):
    batch_id: str
    suggestion_id: str
    edited: bool
    original_question: str


class CreateQARequest(BaseModel):
    question: str
    question_source: QuestionSource
    preset_question_id: str | None = None
    suggestion: SuggestionUse | None = None


class UpdateQARequest(BaseModel):
    answer_text: str


class CreateNoteRequest(BaseModel):
    content: str


class FollowUpRequest(BaseModel):
    qa_item_id: str


class InterviewerScoreInput(BaseModel):
    competency: str
    score: int
    comment: str = ""


class SubmitInterviewerScoresRequest(BaseModel):
    scores: list[InterviewerScoreInput]


class CreateAvailabilityRequest(BaseModel):
    interviewer_id: str
    start_at: AwareDatetime
    end_at: AwareDatetime


class ScheduleSuggestionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    interviewer_ids: list[str]
    from_: AwareDatetime = Field(alias="from")
    to: AwareDatetime
    duration_minutes: int = Field(ge=15, le=480)
    min_interviewers: int | None = None
