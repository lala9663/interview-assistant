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
    CheckPointSource,
    DecisionStatus,
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
Channel = Literal["upload", "site"]
StepKind = Literal["screening", "round", "final"]
# interviews.py: where an application stands in a step (screening uses passed / hold / rejected).
StepStatus = Literal[
    "waiting", "scheduled", "in_progress", "evaluating", "deciding", "passed", "hold", "rejected"
]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- 1. entities --------------------------------------------------------------------------


class JobPosting(Schema):
    id: str
    title: str
    job_family: str
    jd_text: str
    status: PostingStatus
    site_posting_no: str | None
    created_at: Timestamp


class InterviewRound(Schema):
    id: str
    posting_id: str
    position: int
    label: str  # "1차", "2차" ... (always from the position)
    name: str  # what the round is for: "직무 면접", "임원 면접"
    default_mode: SessionMode
    recommended_interviewers: int
    show_previous_scores: bool  # interviewers of this round see earlier rounds' scores
    created_at: Timestamp


class CompetencySet(Schema):
    id: str
    posting_id: str
    round_id: str
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
    channel: Channel
    withdrawn_at: Timestamp | None
    deleted_at: Timestamp | None
    created_at: Timestamp


class RequirementCheck(BaseModel):
    kind: Literal["required", "preferred"]  # 필수 / 우대
    requirement: str
    verdict: Literal["met", "unmet", "unclear"]  # 충족 / 미충족 / 확인 필요
    evidence: str
    source: str  # where in the document ("경력 · [회사-1]"); "" when nothing was found


class ScreeningAssessment(BaseModel):
    summary: str
    requirements: list[RequirementCheck]
    interview_checks: list[str]  # 면접에서 확인할 점


class Screening(Schema):
    id: str
    application_id: str
    fit_score: float
    # Plain text: summary, `+ ` lines, `- ` lines. Rows screened before screening-v0.5 have only this.
    rationale: str
    assessment: ScreeningAssessment | None  # screening-v0.5 and later
    recommendation: ScreeningStatus | None  # the AI's recommendation, reference only
    status: ScreeningStatus
    reject_reason: str | None  # de-identified; set while status is rejected
    model: str | None
    prompt_version: str | None
    created_at: Timestamp


class Interviewer(Schema):
    id: str
    employee_no: str
    name: str
    job_family: str | None
    department: str | None
    is_admin: bool
    created_at: Timestamp


class InterviewSession(Schema):
    id: str
    application_id: str
    round_id: str
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


class RoundDecision(BaseModel):
    """One revision of a person's decision on an application in a round. Newest revision wins."""

    id: str
    application_id: str
    round_id: str
    session_id: str | None
    revision: int
    decision: DecisionStatus
    reason: str  # de-identified
    decided_by: str
    decided_by_name: str
    created_at: Timestamp


class CheckPoint(BaseModel):
    """확인이 필요한 점 for a later round. AI ones quote the de-identified answer in `evidence`."""

    id: str
    session_id: str
    source: CheckPointSource
    competency: str | None
    text: str
    evidence: str | None
    qa_item_id: str | None
    author_id: str | None
    author_name: str | None
    model: str | None
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


class RoundRef(BaseModel):
    id: str
    position: int
    label: str
    name: str
    is_last: bool


class RoundView(RoundRef):
    """The round of a session, with what its interviewers may see of earlier rounds."""

    rounds: int  # how many rounds the posting has
    show_previous_scores: bool


class RoundCount(BaseModel):
    """Applications that reached the round, and how many are at each status in it."""

    round: RoundRef
    reached: int
    waiting: int
    scheduled: int
    in_progress: int
    evaluating: int
    deciding: int
    passed: int
    hold: int
    rejected: int


class PostingCounts(BaseModel):
    applications: int
    passed: int
    hold: int
    rejected: int
    interviewing: int
    interviewed: int
    evaluated: int
    rounds: list[RoundCount]
    final: int  # passed the last round: 최종 합격 후보 (the official result is the site's)


class CompetencySetBrief(Schema):
    id: str
    version: int
    approved_at: Timestamp | None


class PostingSummary(Schema):
    id: str
    title: str
    job_family: str
    status: PostingStatus
    site_posting_no: str | None
    created_at: Timestamp
    counts: PostingCounts
    rounds: list[RoundRef]
    # Round 1's dictionary (screening uses its approved version).
    latest_competency_set: CompetencySetBrief | None
    approved_competency_set: CompetencySetBrief | None


class PostingDetail(JobPosting):
    counts: PostingCounts
    rounds: list[RoundRef]


class RoundSummary(InterviewRound):
    """GET /postings/{id}/rounds item: a round with its dictionary and how far it is in use."""

    is_last: bool
    latest_competency_set: CompetencySetBrief | None
    approved_competency_set: CompetencySetBrief | None
    preset_count: int  # preset questions of the approved version
    sessions: int  # sessions held or scheduled in the round (not cancelled)
    # A round with sessions or decisions keeps its place: it cannot move or be deleted.
    locked: bool


class ProgressStep(BaseModel):
    """One step of an application: 서류, a round, or 최종 (status null: not reached yet)."""

    kind: StepKind
    round: RoundRef | None
    status: StepStatus | None
    at: Timestamp | None
    session_id: str | None


class ApplicationRow(BaseModel):
    application_id: str
    candidate: CandidateRef
    screening: Screening | None
    years_experience: float | None
    top_skills: list[str]
    stage: ProgressStep  # the current step
    progress: list[ProgressStep]  # 서류 → each round → 최종
    channel: Channel  # 수신 경로: site 연동 or 직접 upload
    created_at: Timestamp


class SessionBrief(BaseModel):
    id: str
    round: RoundRef
    status: SessionStatus
    mode: SessionMode
    scheduled_at: Timestamp | None
    ended_at: Timestamp | None


class ReadingFile(BaseModel):
    format: str
    converted_from: str | None = None  # "doc" / "ppt": read after LibreOffice converted it
    pages: int
    ocr_pages: list[int]
    ocr_confidence: float | None = None  # lowest page confidence among the OCR'd pages
    pictures_read: int  # pictures in the document read by OCR (certificates, captures)
    photos_dropped: int  # pictures taken for ID photos and dropped unread
    garbled_pages: list[int]  # pages whose text layer was garbled and re-read by OCR


class ReadingInfo(BaseModel):
    """How the attachments were read (서류 읽기 settings in force when processing started)."""

    revision: int | None
    mode: Literal["auto", "always_ocr", "text_only"]
    embedded_images: bool
    sensitivity: str
    tools: list[str]  # every reader and OCR engine used, with its version
    files: list[ReadingFile]


class DocumentInfo(BaseModel):
    """What an uploaded file held, counts only. Hidden blocks were left out of screening."""

    format: str
    blocks: int
    hidden_blocks: int
    images_dropped: int
    replacements: int
    reading: ReadingInfo | None = None  # absent for applications read before 서류 읽기 settings


class ApplicationDetail(BaseModel):
    application: Application
    candidate: Candidate
    posting: PostingRefWithFamily
    screening: Screening | None
    sessions: list[SessionBrief]
    document: DocumentInfo | None
    stage: ProgressStep
    progress: list[ProgressStep]
    decisions: list[RoundDecision]  # every revision of every round, newest first


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
    """An application waiting for a session of `round` (round 1: passed screening; round N:
    passed round N-1). `mode` and `recommended_interviewers` are the round's defaults."""

    application_id: str
    candidate: CandidateRef
    posting: PostingRefWithFamily
    fit_score: float
    round: RoundRef
    mode: SessionMode
    recommended_interviewers: int
    since: Timestamp | None  # when the previous step was passed


class SessionInterviewerView(SessionInterviewer):
    interviewer: Interviewer


class SessionSummary(InterviewSession):
    candidate: CandidateRef
    posting: PostingRef
    round: RoundRef
    # The application's status in this session's round (예정 … 합격·보류·불합격).
    round_status: StepStatus
    interviewers: list[SessionInterviewerView]
    qa_count: int
    ai_scoring: AiScoringState
    submitted_interviewer_ids: list[str]


class CarryoverOrigin(BaseModel):
    """What an AI carry-over question (이어 질문) builds on: an earlier round's answer."""

    round: RoundRef
    question: str  # the earlier question, de-identified
    grounding: str  # verbatim quote of the earlier answer
    rationale: str
    model: str | None


class PresetQuestion(BaseModel):
    id: str
    competency: str
    question: str
    intent: str
    origin: CarryoverOrigin | None = None  # set on carry-over questions only


class CardCandidate(Schema):
    id: str
    pseudonym: str
    consent_recording: bool
    consent_at: Timestamp | None


class CardScreening(Schema):
    fit_score: float
    status: ScreeningStatus
    rationale: str


class PreviousNote(BaseModel):
    id: str
    content: str  # de-identified
    author_name: str
    created_at: Timestamp


class PreviousScore(BaseModel):
    """An earlier round's scores per competency, only when the round allows it. Interviewer and
    AI means stay apart."""

    competency: str
    interviewer_mean: float | None
    ai_mean: float | None


class PreviousRound(BaseModel):
    """이전 차수 요약 on the candidate card. Points to check and notes always; scores, and the
    decision reason that may echo them, only when this round shows earlier scores."""

    round: RoundRef
    session: SessionBrief
    decision: DecisionStatus | None
    qa_count: int
    check_points: list[CheckPoint]
    notes: list[PreviousNote]
    scores_visible: bool
    scores: list[PreviousScore] | None
    decision_reason: str | None


class CandidateCard(BaseModel):
    candidate: CardCandidate
    profile: CandidateProfile | None
    screening: CardScreening | None
    previous_sessions: list[SessionBrief]
    previous_rounds: list[PreviousRound]


class SessionDetail(BaseModel):
    session: InterviewSession
    posting: PostingRefWithFamily
    round: RoundView
    card: CandidateCard
    interviewers: list[SessionInterviewerView]
    competency_set: CompetencySet | None
    preset_questions: list[PresetQuestion]
    # 이어 질문: AI questions for this candidate built on earlier rounds' answers.
    carryover_questions: list[PresetQuestion]
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
    # True while the signed-in interviewer of this session has not submitted their own scores
    # (and did not choose to see AI first): scores and summary are then empty.
    hidden: bool = False
    scores: list[Score]
    summary: list[AiCompetencySummary]


class InterviewerEvaluation(BaseModel):
    interviewer: Interviewer
    role: InterviewerRole
    submitted_at: Timestamp | None
    scores: list[Score]


class DecisionPanel(BaseModel):
    """N차 결정 on the evaluation screen. A person decides; AI scores are reference only."""

    current: RoundDecision | None
    history: list[RoundDecision]  # newest first
    can_decide: bool
    blocked_reason: str | None  # why not, when can_decide is false
    is_last_round: bool  # a pass makes a final candidate (recorded officially on the site)
    next_round: RoundRef | None


class Evaluation(BaseModel):
    session: InterviewSession
    candidate: CandidateRef
    posting: PostingRef
    round: RoundView
    competency_set: CompetencySet | None
    qa_items: list[QAItem]
    ai: AiEvaluation
    interviewers: list[InterviewerEvaluation]
    decision: DecisionPanel
    check_points: list[CheckPoint]  # for later rounds: interviewers' and AI's


class PipelinePosting(Schema):
    id: str
    title: str
    job_family: str
    status: PostingStatus


class PipelineRow(BaseModel):
    posting: PipelinePosting
    counts: PostingCounts


class PendingDecision(BaseModel):
    """An evaluated round waiting for a decision, or one decided 보류 (it stays here)."""

    session_id: str
    application_id: str
    candidate: CandidateRef
    posting: PostingRef
    round: RoundRef
    status: Literal["deciding", "hold"]
    since: Timestamp | None


class DashboardSummary(BaseModel):
    pipeline: list[PipelineRow]
    today_sessions: list[SessionSummary]
    pending_my_scores: list[SessionSummary]
    pending_decisions: list[PendingDecision]
    hold_count: int


class ActivityItem(AuditLog):
    actor_label: str
    target_label: str | None


class ScheduleSuggestion(BaseModel):
    start_at: Timestamp
    end_at: Timestamp
    interviewer_ids: list[str]


# --- 4. admin: AI model settings (관리자 > 모델 설정) ----------------------------------------

DataLocationValue = Literal["local", "server", "gcp", "external"]
ModelChangeKindValue = Literal["initial", "apply", "rollback"]
DownloadStatus = Literal["missing", "downloading", "done", "failed", "cancelled"]


class ModelSpec(BaseModel):
    impl: str
    options: dict[str, Any] = {}


class ModelRequirement(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str
    fix: str | None


class ModelOptionChoice(BaseModel):
    value: str
    label: str
    note: str
    size_bytes: int | None
    recommended_for: list[str]
    downloaded: bool | None  # null: nothing to download


class ModelOptionField(BaseModel):
    key: str
    label: str
    type: Literal["string", "text", "integer", "number", "boolean", "select"]
    default: Any
    help: str
    minimum: float | None
    maximum: float | None
    max_length: int
    choices: list[ModelOptionChoice]
    roles: list[str]
    fixed: bool


class ModelImpl(BaseModel):
    kind: str
    impl: str
    label: str
    description: str
    data_location: DataLocationValue
    data_note: str
    license: str
    roles: list[str]
    options: list[ModelOptionField]
    role_defaults: dict[str, dict[str, Any]]
    role_notes: dict[str, str]
    # What this machine lacks regardless of the options (package, credentials ...). Downloads
    # per model are in the "model" option's choices.
    requirements: list[ModelRequirement]


class ModelActor(Schema):
    id: str
    employee_no: str
    name: str


class ModelChange(BaseModel):
    id: str
    revision: int
    occurred_at: Timestamp
    role: str
    role_label: str
    kind: ModelChangeKindValue
    actor: ModelActor | None
    previous: ModelSpec | None
    new: ModelSpec
    previous_label: str | None
    new_label: str
    reason: str | None
    reverts_change_id: str | None
    details: dict[str, Any] | None


class ModelRoleState(BaseModel):
    role: str
    label: str
    description: str
    kind: str
    group: Literal["ai", "documents", "audio"]  # heading on the screen: AI 모델 / 서류 읽기 / 음성 입력
    spec: ModelSpec
    impl_label: str
    model: str  # the model name results and the audit log carry
    data_location: DataLocationValue
    status: Literal["ready", "unavailable"]
    status_detail: str | None
    requirements: list[ModelRequirement]
    note: str | None
    last_change: ModelChange | None
    # Interviews in progress (or being scored) that still use an earlier config of this role.
    pinned_sessions: int


class ModelSettings(BaseModel):
    revision: int
    persistent: bool  # false: the settings tables are missing, nothing can be saved
    roles: list[ModelRoleState]


class ModelCheck(BaseModel):
    role: str
    spec: ModelSpec
    data_location: DataLocationValue
    external: bool
    requirements: list[ModelRequirement]
    ready: bool
    same_as_active: bool


class ModelTestResult(BaseModel):
    ok: bool
    model: str
    latency_ms: int
    summary: str
    output: dict[str, Any]
    error: str | None
    audio: Literal["sample", "upload"] | None
    document: Literal["sample", "upload"] | None = None  # 서류 읽기 roles: what was read


class ModelDownload(BaseModel):
    impl: str
    model: str
    status: DownloadStatus
    total_bytes: int
    downloaded_bytes: int
    error: str | None


# --- 5. intake: applications from the recruiting site (채용 사이트 연동) ----------------------

IntakeEventTypeValue = Literal["submitted", "updated", "withdrawn"]
IntakeStatusValue = Literal["queued", "processing", "done", "skipped", "failed", "rejected"]


class IntakeFailure(BaseModel):
    code: str
    message: str
    fields: list[str]  # field paths only, never values


class IntakeEvent(BaseModel):
    """One event the site sent, for 관리자 > 연동 현황. No name, no applicant number."""

    id: str
    event_id: str
    event_type: IntakeEventTypeValue | None
    status: IntakeStatusValue
    revision: int | None
    occurred_at: Timestamp | None
    received_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None
    processing_ms: int | None
    attempts: int
    posting_no: str | None
    posting: PostingRef | None
    application_no: str | None
    candidate: CandidateRef | None
    failure: IntakeFailure | None
    dropped_fields: list[str]
    retriable: bool
    result: dict[str, Any] | None


class IntakeTotals(BaseModel):
    received: int
    queued: int
    processing: int
    done: int
    skipped: int
    failed: int
    rejected: int


class IntakePostingCount(BaseModel):
    posting_no: str | None
    posting: PostingRef | None  # null: no posting carries this number yet
    received: int
    submitted: int
    updated: int
    withdrawn: int
    done: int
    skipped: int
    failed: int
    rejected: int
    pending: int  # queued + processing
    applications: int  # active applications from the site on the posting


class IntakeFailureCount(BaseModel):
    code: str
    count: int
    retriable: int  # failed events with the payload kept, which 다시 처리 can queue again


class IntakeTiming(BaseModel):
    processed: int
    avg_ms: int | None
    p50_ms: int | None
    p95_ms: int | None
    max_ms: int | None
    avg_wait_ms: int | None  # received -> started
    first_received_at: Timestamp | None
    last_finished_at: Timestamp | None
    per_minute: float | None  # applied events per minute between those two


class IntakeSummary(BaseModel):
    configured: bool  # the site's signing key is set (IA_SITE_SECRET)
    workers: int
    totals: IntakeTotals
    postings: list[IntakePostingCount]
    failures: list[IntakeFailureCount]
    timing: IntakeTiming


class IntakeRetried(BaseModel):
    requeued: int


class SiteEventStatus(BaseModel):
    """What the recruiting site gets back (202 and the status lookup): no pseudonym, no ids."""

    event_id: str
    status: IntakeStatusValue
    event_type: str | None
    revision: int | None
    received_at: str
    finished_at: str | None
    dropped_fields: list[str]
    duplicate: bool
    code: str | None = None
    detail: str | None = None
    fields: list[str] | None = None
    status_url: str | None = None


# --- requests -----------------------------------------------------------------------------


class CompetenciesBody(BaseModel):
    competencies: list[Competency]


class ScreeningUpdate(BaseModel):
    status: ScreeningStatus
    # Required with `rejected` (why, in a sentence); ignored otherwise.
    reason: str | None = None


class UpdatePostingRequest(BaseModel):
    # 채용 사이트 공고 번호; null or "" unlinks the posting.
    site_posting_no: str | None = Field(default=None, max_length=64)


class RetryIntakeRequest(BaseModel):
    failure_code: str | None = None  # only failures with this code (e.g. unknown_posting)
    posting_no: str | None = None


class PanelMember(BaseModel):
    interviewer_id: str
    role: InterviewerRole


class CreateSessionRequest(BaseModel):
    application_id: str
    # The round of the new session; left out, the round the application is waiting for.
    round_id: str | None = None
    mode: SessionMode
    scheduled_at: AwareDatetime
    interviewers: list[PanelMember]


class CreateRoundRequest(BaseModel):
    name: str = Field(max_length=100)
    default_mode: SessionMode = SessionMode.remote
    recommended_interviewers: int = 2
    show_previous_scores: bool = False


class UpdateRoundRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    default_mode: SessionMode | None = None
    recommended_interviewers: int | None = None
    show_previous_scores: bool | None = None


class ReorderRoundsRequest(BaseModel):
    round_ids: list[str]


class PresetQuestionBody(BaseModel):
    competency: str
    question: str
    intent: str = ""


class DecisionRequest(BaseModel):
    decision: DecisionStatus
    reason: str


class CreateCheckPointRequest(BaseModel):
    text: str
    competency: str | None = None


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


# --- microphone (docs/api-contract.md 3.3) ---------------------------------------------------


class MicRoleRequest(BaseModel):
    # candidate: 답변 듣는 중, interviewer: 질문 중 (one microphone, face to face)
    role: Literal["candidate", "interviewer"]


class MicRoleResult(BaseModel):
    role: Literal["candidate", "interviewer"]
    # The question asked aloud while the role was interviewer, recorded as the next question.
    qa_item: QAItem | None = None


class AudioChunkResult(BaseModel):
    speaking: bool
    role: Literal["candidate", "interviewer"]
    notices: list[str]


class AudioSample(BaseModel):
    name: str
    label: str
    seconds: float
    text: str
    note: str


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


class ModelSpecRequest(BaseModel):
    impl: str
    options: dict[str, Any] = {}


class ApplyModelRequest(ModelSpecRequest):
    reason: str = ""
    confirm_external: bool = False


class RevertModelRequest(BaseModel):
    reason: str = ""
    confirm_external: bool = False


class DownloadRequest(BaseModel):
    impl: str
    model: str


# --- 질문 은행·평점 기준 예시·임베딩 색인 (retrieval) -------------------------------------------

BankStatusValue = Literal["draft", "approved", "retired"]


class BankFlag(BaseModel):
    """A prohibited-question warning: rule match or AI check (question_rules.py)."""

    category: str
    label: str
    basis: str
    matched: str
    source: Literal["rule", "ai"]
    note: str = ""


class BankPerson(Schema):
    id: str
    name: str


class QuestionBankItem(BaseModel):
    id: str
    job_family: str
    competency: str
    round_position: int | None
    question: str
    intent: str
    follow_ups: list[str]
    status: BankStatusValue
    flags: list[BankFlag]
    source: Literal["manual", "csv", "seed"]
    created_by: BankPerson | None
    approved_by: BankPerson | None
    created_at: Timestamp
    updated_at: Timestamp
    approved_at: Timestamp | None
    retired_at: Timestamp | None


class BankFamily(BaseModel):
    """A job family with the competencies used in it: the bank's, and those of postings' dictionaries."""

    job_family: str
    competencies: list[str]


class QuestionBankList(BaseModel):
    items: list[QuestionBankItem]
    families: list[BankFamily]
    counts: dict[str, int]  # draft / approved / retired, of the filtered list
    total: int


class BankQuestionBody(BaseModel):
    job_family: str = Field(max_length=100)
    competency: str = Field(max_length=100)
    round_position: int | None = Field(default=None, ge=1, le=6)
    question: str
    intent: str = Field(default="", max_length=200)
    follow_ups: list[str] = []


class BankCheckRequest(BaseModel):
    question: str
    follow_ups: list[str] = []


class BankCheckResult(BaseModel):
    flags: list[BankFlag]


class ApproveRequest(BaseModel):
    # Approve although the question has prohibited-question warnings (recorded in the audit log).
    confirm_warnings: bool = False


class ImportRowIssue(BaseModel):
    row: int  # 1-based data row (the header is row 0)
    message: str


class ImportResult(BaseModel):
    dry_run: bool
    rows: int
    created: int
    skipped: int  # same question already in the bank for that job family and competency
    errors: list[ImportRowIssue]
    warnings: list[ImportRowIssue]  # prohibited-question warnings on imported drafts


class RubricOverlap(BaseModel):
    """An approved example of the same competency at another score that reads almost the same:
    two anchors that close make the levels ambiguous."""

    id: str
    score: int
    similarity: float


class RubricExample(BaseModel):
    id: str
    job_family: str
    competency: str
    score: int
    question: str
    answer: str
    rationale: str
    status: BankStatusValue
    source: Literal["manual", "csv", "seed"]
    created_by: BankPerson | None
    approved_by: BankPerson | None
    created_at: Timestamp
    updated_at: Timestamp
    approved_at: Timestamp | None
    retired_at: Timestamp | None
    overlaps: list[RubricOverlap] = []


class RubricExampleBody(BaseModel):
    job_family: str = Field(max_length=100)
    competency: str = Field(max_length=100)
    score: int = Field(ge=1, le=5)
    question: str = ""
    answer: str
    rationale: str = ""


class RubricList(BaseModel):
    items: list[RubricExample]
    families: list[BankFamily]
    counts: dict[str, int]


class EmbeddingIndexState(BaseModel):
    index_key: str
    model: str
    dimensions: int
    status: Literal["building", "ready", "failed"]
    total: int
    done: int
    started_at: Timestamp
    finished_at: Timestamp | None
    error: str | None
    serving: bool  # searches use this one now


class EmbeddingIndexStatus(BaseModel):
    """관리자 > 모델 설정 > 임베딩: what searches use now and any index being built."""

    active_model: str | None  # the embedding role's provider now
    active_index_key: str | None
    serving_index_key: str | None
    counts: dict[str, int]  # vectors searched now, by owner type
    indexes: list[EmbeddingIndexState]


class SourceMetrics(BaseModel):
    source: Literal["bank", "ai"]
    shown: int
    used: int
    edited: int
    adoption_rate: float | None
    batches: int  # batches with at least one suggestion of this source
    first_ms_median: int | None  # request -> first card of this source, per batch
    first_ms_p90: int | None


class FollowUpMetrics(BaseModel):
    since: Timestamp
    days: int
    batches: int
    sources: list[SourceMetrics]
    duplicates: dict[str, int]  # bank / ai / total candidates dropped as already asked
    retrieval_model: str | None


# --- agent proposals (docs/agent-integration.md) ------------------------------------------------

ProposalKind = Literal["interview_booking", "screening_decision", "round_decision"]


class AgentProposalRequest(BaseModel):
    """What an agent proposes, recorded for the audit log only: nothing changes until a person
    confirms it on the web screen. Structured fields only; the agent's free text is not kept."""

    kind: ProposalKind
    application_id: str
    round_id: str | None = None
    session_id: str | None = None
    decision: Literal["passed", "hold", "rejected"] | None = None
    start_at: AwareDatetime | None = None
    interviewer_ids: list[str] = Field(default_factory=list, max_length=10)
    mode: SessionMode | None = None


class AgentProposalRecorded(BaseModel):
    id: str  # the audit row
    kind: ProposalKind
    application_id: str
    recorded_at: Timestamp
