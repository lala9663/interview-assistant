/**
 * API types. Section 1 mirrors the ORM models in `src/interview_assistant/models/` field for field
 * (snake_case, same enum values). Section 2 holds the composite view models the REST API returns.
 * The contract is written up in `docs/api-contract.md`; keep the two in sync.
 *
 * Conventions: ids are UUID strings, datetimes are ISO 8601 strings with a UTC offset, nullable
 * columns are `T | null`. Raw-zone fields never cross the API: `Candidate.encrypted_identity`,
 * `Application.source_file_uri`, `InterviewSession.recording_uri` (only `has_recording`) and
 * `QAItem.answer_text` (only `answer_deidentified`) stay on the server.
 */

// ---------------------------------------------------------------------------------------------
// 1. Enums (models/recruiting.py, models/interview.py, models/audit.py)
// ---------------------------------------------------------------------------------------------

export const POSTING_STATUSES = ['draft', 'open', 'closed'] as const
export type PostingStatus = (typeof POSTING_STATUSES)[number]

export const SCREENING_STATUSES = ['passed', 'hold', 'rejected'] as const
export type ScreeningStatus = (typeof SCREENING_STATUSES)[number]

export const SESSION_MODES = ['onsite', 'remote'] as const
export type SessionMode = (typeof SESSION_MODES)[number]

export const SESSION_STATUSES = ['scheduled', 'in_progress', 'completed', 'cancelled'] as const
export type SessionStatus = (typeof SESSION_STATUSES)[number]

export const INTERVIEWER_ROLES = ['lead', 'panel'] as const
export type InterviewerRole = (typeof INTERVIEWER_ROLES)[number]

export const QUESTION_SOURCES = ['preset', 'ai_suggested', 'interviewer'] as const
export type QuestionSource = (typeof QUESTION_SOURCES)[number]

export const EVALUATOR_TYPES = ['ai', 'interviewer'] as const
export type EvaluatorType = (typeof EVALUATOR_TYPES)[number]

export const AVAILABILITY_SOURCES = ['manual', 'calendar'] as const
export type AvailabilitySource = (typeof AVAILABILITY_SOURCES)[number]

export const ACTOR_TYPES = ['user', 'system', 'ai'] as const
export type ActorType = (typeof ACTOR_TYPES)[number]

/** 수신 경로: uploaded on the screening screen, or sent by the recruiting site. */
export const APPLICATION_CHANNELS = ['upload', 'site'] as const
export type ApplicationChannel = (typeof APPLICATION_CHANNELS)[number]

// ---------------------------------------------------------------------------------------------
// 1. Entities
// ---------------------------------------------------------------------------------------------

/** models.JobPosting */
export interface JobPosting {
  id: string
  title: string
  job_family: string
  jd_text: string
  status: PostingStatus
  /** 채용 사이트 공고 번호; site events name the posting by it (null: not linked) */
  site_posting_no: string | null
  created_at: string
}

/** BARS: observable behaviour for each score 1-5. Keys are strings, as stored in JSON. */
export type BarsLevel = '1' | '2' | '3' | '4' | '5'
export const BARS_LEVELS: readonly BarsLevel[] = ['1', '2', '3', '4', '5']
export type Bars = Record<BarsLevel, string>

/** One element of `CompetencySet.competencies` ({name, description, bars}). */
export interface Competency {
  name: string
  description: string
  bars: Bars
}

/**
 * models.CompetencySet. Approved when `approved_at` is set; approved versions are read-only.
 * `approved_by` holds the approver's interviewer id (SSO user id later).
 */
export interface CompetencySet {
  id: string
  posting_id: string
  version: number
  competencies: Competency[]
  approved_by: string | null
  approved_at: string | null
  created_at: string
}

/** models.Candidate without `encrypted_identity`. The UI only ever shows `pseudonym`. */
export interface Candidate {
  id: string
  pseudonym: string
  consent_recording: boolean
  consent_at: string | null
  deleted_at: string | null
  created_at: string
}

/**
 * Shape of `Application.profile` (JSON). Produced by step 5 from the de-identified document text,
 * so schools/companies appear as tokens such as `[학교-1]`, `[회사-2]`.
 */
export interface CandidateProfile {
  summary: string
  years_experience: number
  skills: string[]
  experience: { company: string; role: string; period: string; highlights: string[] }[]
  education: { school: string; degree: string; major: string }[]
  projects: { name: string; description: string; tech: string[] }[]
  certifications: string[]
}

/** models.Application without `source_file_uri` and the site's application number. */
export interface Application {
  id: string
  candidate_id: string
  posting_id: string
  profile: CandidateProfile | null
  channel: ApplicationChannel
  /** withdrawn on the recruiting site: out of every list, detail still opens */
  withdrawn_at: string | null
  deleted_at: string | null
  created_at: string
}

/** models.Screening */
export interface Screening {
  id: string
  application_id: string
  fit_score: number
  /** Free text. Lines starting with `+ ` are strengths, `- ` concerns, others summary. */
  rationale: string
  status: ScreeningStatus
  model: string | null
  prompt_version: string | null
  created_at: string
}

/** models.Interviewer */
export interface Interviewer {
  id: string
  employee_no: string
  name: string
  job_family: string | null
  department: string | null
  /** may change AI model settings (관리자 > 모델 설정); SSO will set it from a group */
  is_admin: boolean
  created_at: string
}

/** models.InterviewSession with `recording_uri` reduced to a flag. */
export interface InterviewSession {
  id: string
  application_id: string
  mode: SessionMode
  status: SessionStatus
  scheduled_at: string | null
  started_at: string | null
  ended_at: string | null
  has_recording: boolean
  created_at: string
}

/** models.SessionInterviewer */
export interface SessionInterviewer {
  session_id: string
  interviewer_id: string
  role: InterviewerRole
}

/** models.QAItem without the raw `answer_text`. */
export interface QAItem {
  id: string
  session_id: string
  seq: number
  question: string
  question_source: QuestionSource
  answer_deidentified: string | null
  asked_at: string | null
  answered_at: string | null
  created_at: string
}

/**
 * models.Score. AI scores belong to one answer and always carry `evidence` (DB checks
 * `ai_requires_answer`, `ai_requires_evidence`); interviewer scores are per session (`qa_item_id` null).
 */
export interface Score {
  id: string
  qa_item_id: string | null
  competency: string
  score: number
  evidence: string | null
  confidence: number | null
  evaluator_type: EvaluatorType
  evaluator_id: string | null
  model: string | null
  prompt_version: string | null
  created_at: string
}

/** models.CandidateNote */
export interface CandidateNote {
  id: string
  session_id: string
  author_id: string
  content: string
  created_at: string
}

/** models.Availability */
export interface Availability {
  id: string
  interviewer_id: string
  start_at: string
  end_at: string
  source: AvailabilitySource
  created_at: string
}

/** models.AuditLog (payload_ref and token counts are not exposed to the UI). */
export interface AuditLog {
  id: string
  occurred_at: string
  actor_type: ActorType
  actor_id: string | null
  action: string
  target_type: string | null
  target_id: string | null
  model: string | null
  prompt_version: string | null
  details: Record<string, unknown> | null
}

// ---------------------------------------------------------------------------------------------
// 2. View models (composites returned by the REST API)
// ---------------------------------------------------------------------------------------------

/** FastAPI error body: `detail` is a string, or a list for 422 validation errors. */
export interface ApiErrorBody {
  detail: string | { loc: (string | number)[]; msg: string; type: string }[]
}

/** GET /api/me — the signed-in interviewer (SSO later; the mock picks one). */
export type Me = Interviewer

export interface PostingCounts {
  applications: number
  passed: number
  hold: number
  rejected: number
  /** applications with a session that is scheduled or in progress */
  interviewing: number
  /** applications with a completed session */
  interviewed: number
  /** of those, AI scoring finished and every session interviewer submitted */
  evaluated: number
}

export interface CompetencySetBrief {
  id: string
  version: number
  approved_at: string | null
}

/** GET /api/postings item */
export interface PostingSummary extends Omit<JobPosting, 'jd_text'> {
  counts: PostingCounts
  latest_competency_set: CompetencySetBrief | null
  approved_competency_set: CompetencySetBrief | null
}

/** GET /api/postings/{id} */
export interface PostingDetail extends JobPosting {
  counts: PostingCounts
}

export type ApplicationStage = 'screening' | 'interview_scheduled' | 'interviewing' | 'interviewed' | 'evaluated'

/** GET /api/postings/{id}/applications item: one row of the screening table. */
export interface ApplicationRow {
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  screening: Screening | null
  years_experience: number | null
  top_skills: string[]
  stage: ApplicationStage
  channel: ApplicationChannel
  created_at: string
}

export interface SessionBrief {
  id: string
  status: SessionStatus
  mode: SessionMode
  scheduled_at: string | null
  ended_at: string | null
}

/** How one attachment was read. Labels and numbers only, nothing from the file. */
export interface ReadingFile {
  format: string
  /** "doc" / "ppt": read after LibreOffice converted it */
  converted_from: string | null
  pages: number
  ocr_pages: number[]
  /** lowest page confidence among the OCR'd pages (0..1) */
  ocr_confidence: number | null
  /** pictures in the document read by OCR (certificates, captures) */
  pictures_read: number
  /** pictures taken for ID photos and dropped unread */
  photos_dropped: number
  /** pages whose text layer was garbled and re-read by OCR */
  garbled_pages: number[]
}

export const READING_MODES = ['auto', 'always_ocr', 'text_only'] as const
export type ReadingMode = (typeof READING_MODES)[number]

/** The 서류 읽기 settings an application was read with (taken when its processing started). */
export interface ReadingInfo {
  revision: number | null
  mode: ReadingMode
  embedded_images: boolean
  sensitivity: string
  /** every reader and OCR engine used, with its version */
  tools: string[]
  files: ReadingFile[]
}

/** What an uploaded file held, counts only. Hidden blocks were left out of the screening prompt. */
export interface DocumentInfo {
  format: string
  blocks: number
  hidden_blocks: number
  images_dropped: number
  replacements: number
  /** absent for applications read before 서류 읽기 settings existed */
  reading?: ReadingInfo | null
}

/** GET /api/applications/{id} */
export interface ApplicationDetail {
  application: Application
  candidate: Candidate
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family'>
  screening: Screening | null
  sessions: SessionBrief[]
  /** null for applications that did not come from an upload */
  document: DocumentInfo | null
}

/**
 * POST /api/postings/{id}/applications (multipart). Identity fields are what the application form
 * says; the server seals them and uses them only to de-identify. Multiple values: one per line.
 */
export interface UploadApplicationRequest {
  file: File
  name: string
  /** other spellings of the name (English, Hanja) */
  aliases?: string
  phone?: string
  email?: string
}

export interface UploadResult {
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  screening: Screening
  document: DocumentInfo
}

/** GET /api/candidates item: lightweight index for search (command palette). */
export interface CandidateIndexItem {
  candidate_id: string
  pseudonym: string
  application_id: string
  posting_id: string
  posting_title: string
  screening_status: ScreeningStatus | null
  fit_score: number | null
}

/** GET /api/applications/schedulable item: passed applications without an active session. */
export interface SchedulableApplication {
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family'>
  fit_score: number
}

export interface SessionInterviewerView extends SessionInterviewer {
  interviewer: Interviewer
}

/** GET /api/sessions item */
export interface SessionSummary extends InterviewSession {
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title'>
  interviewers: SessionInterviewerView[]
  qa_count: number
  ai_scoring: AiScoringStatus
  /** interviewer ids that submitted scores */
  submitted_interviewer_ids: string[]
}

/** Preset question (FR-06 사전 질문 세트). Not a table yet; see api-contract.md. */
export interface PresetQuestion {
  id: string
  competency: string
  question: string
  intent: string
}

/** Candidate summary card (FR-04): de-identified profile + screening digest + previous sessions. */
export interface CandidateCard {
  candidate: Pick<Candidate, 'id' | 'pseudonym' | 'consent_recording' | 'consent_at'>
  profile: CandidateProfile | null
  screening: Pick<Screening, 'fit_score' | 'status' | 'rationale'> | null
  previous_sessions: SessionBrief[]
}

/** GET /api/sessions/{id} */
export interface SessionDetail {
  session: InterviewSession
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family'>
  card: CandidateCard
  interviewers: SessionInterviewerView[]
  competency_set: CompetencySet | null
  preset_questions: PresetQuestion[]
  qa_items: QAItem[]
  notes: CandidateNote[]
}

export interface ConsentRequest {
  consent_recording: boolean
}

export interface CreateQARequest {
  question: string
  question_source: QuestionSource
  /** set when question_source = preset */
  preset_question_id?: string
  /** set when question_source = ai_suggested: which suggestion was used and whether it was edited */
  suggestion?: { batch_id: string; suggestion_id: string; edited: boolean; original_question: string }
}

export interface UpdateQARequest {
  /** raw answer typed in manual mode; the server de-identifies it and returns answer_deidentified */
  answer_text: string
}

export interface CreateNoteRequest {
  content: string
}

// --- Transcript stream (SSE: GET /api/sessions/{id}/transcript/stream) -------------------------

export type Speaker = 'interviewer' | 'candidate'

/** One STT segment. `text` is already de-identified. */
export interface TranscriptSegment {
  segment_id: string
  qa_item_id: string | null
  speaker: Speaker
  text: string
  is_final: boolean
  start_ms: number
  end_ms: number | null
}

export type RecordingState = 'recording' | 'paused' | 'stopped' | 'off'
export type SttState = 'ok' | 'degraded' | 'down' | 'off'

export interface StreamStatus {
  recording: RecordingState
  stt: SttState
  latency_ms: number | null
}

export type TranscriptEvent =
  | { event: 'status'; data: StreamStatus }
  | { event: 'segment.partial'; data: TranscriptSegment }
  | { event: 'segment.final'; data: TranscriptSegment }
  | { event: 'qa.answered'; data: { qa_item_id: string; answer_deidentified: string; answered_at: string } }

/** GET /api/sessions/{id}/transcript: final segments so far (history on (re)connect). */
export interface TranscriptHistory {
  segments: TranscriptSegment[]
}

// --- Follow-up suggestions (SSE: POST /api/sessions/{id}/follow-ups) --------------------------

export interface FollowUpRequest {
  qa_item_id: string
}

export interface SuggestionMeta {
  batch_id: string
  suggestion_id: string
  index: number
  competency: string
}

export interface SuggestionDone extends SuggestionMeta {
  question: string
  /** why this follow-up (생성 근거) */
  rationale: string
  /** quote from the de-identified answer the question builds on */
  grounding: string
}

export type FollowUpEvent =
  | { event: 'batch.start'; data: { batch_id: string; qa_item_id: string; model: string; prompt_version: string } }
  | { event: 'suggestion.start'; data: SuggestionMeta }
  | { event: 'suggestion.delta'; data: { batch_id: string; suggestion_id: string; text: string } }
  | { event: 'suggestion.done'; data: SuggestionDone }
  | { event: 'batch.done'; data: { batch_id: string } }
  | { event: 'error'; data: { message: string } }

// --- Evaluation (FR-07, FR-08) ----------------------------------------------------------------

export type AiScoringStatus = 'not_started' | 'running' | 'completed' | 'failed'

/** Per-competency digest of the AI item scores. Never mixed with interviewer scores. */
export interface AiCompetencySummary {
  competency: string
  /** mean of the AI item scores for this competency, 1 decimal */
  score: number
  /** lowest confidence among those items */
  confidence: number
  item_count: number
}

export interface InterviewerEvaluation {
  interviewer: Interviewer
  role: InterviewerRole
  submitted_at: string | null
  scores: Score[]
}

/** GET /api/sessions/{id}/evaluation */
export interface Evaluation {
  session: InterviewSession
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title'>
  competency_set: CompetencySet | null
  qa_items: QAItem[]
  ai: {
    status: AiScoringStatus
    model: string | null
    prompt_version: string | null
    /** number of samples aggregated per item (FR-07 다중 샘플) */
    samples: number
    scores: Score[]
    summary: AiCompetencySummary[]
  }
  interviewers: InterviewerEvaluation[]
}

export interface InterviewerScoreInput {
  competency: string
  score: number
  /** interviewer comment; stored in Score.evidence */
  comment: string
}

/** PUT /api/sessions/{id}/scores/{interviewer_id} */
export interface SubmitInterviewerScoresRequest {
  scores: InterviewerScoreInput[]
}

// --- Dashboard ---------------------------------------------------------------------------------

export interface PipelineRow {
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family' | 'status'>
  counts: PostingCounts
}

/** GET /api/dashboard */
export interface DashboardSummary {
  pipeline: PipelineRow[]
  today_sessions: SessionSummary[]
  /** completed sessions where the signed-in interviewer has not submitted scores */
  pending_my_scores: SessionSummary[]
  hold_count: number
}

/** GET /api/activity item: an AuditLog row with display labels. */
export interface ActivityItem extends AuditLog {
  actor_label: string
  target_label: string | null
}

// --- Schedule (FR-09) --------------------------------------------------------------------------

export interface CreateAvailabilityRequest {
  interviewer_id: string
  start_at: string
  end_at: string
}

export interface ScheduleSuggestionRequest {
  interviewer_ids: string[]
  /** search range, ISO */
  from: string
  to: string
  duration_minutes: number
  /** minimum number of the selected interviewers that must be free (default: all) */
  min_interviewers?: number
}

export interface ScheduleSuggestion {
  start_at: string
  end_at: string
  interviewer_ids: string[]
}

export interface CreateSessionRequest {
  application_id: string
  mode: SessionMode
  scheduled_at: string
  interviewers: { interviewer_id: string; role: InterviewerRole }[]
}

// --- 관리자 > 모델 설정 (admin only) ------------------------------------------------------------

/** Where a provider sends data: this PC, the company GCP project, or an API outside the company. */
export const DATA_LOCATIONS = ['local', 'gcp', 'external'] as const
export type DataLocation = (typeof DATA_LOCATIONS)[number]

/** The AI roles, then the 서류 읽기 roles, in display order. */
export const MODEL_ROLES = [
  'llm.primary',
  'llm.screening',
  'stt.streaming',
  'stt.batch',
  'embedding',
  'diarization',
  'document.reading',
  'document.ocr',
  'document.pdf',
  'document.hwp',
  'document.legacy',
] as const
export type ModelRole = (typeof MODEL_ROLES)[number]
/** Heading the role is shown under: AI 모델 or 서류 읽기. */
export type ModelGroup = 'ai' | 'documents'
export const isDocumentRole = (role: string) => role.startsWith('document.')

export type ModelKind = 'llm' | 'stt' | 'embedding' | 'diarization' | 'reading' | 'ocr' | 'pdf_reader' | 'hwp_reader' | 'office_converter'
/** The provider kind each role picks from (providers/catalog.py ROLES). */
export const MODEL_ROLE_KIND: Record<ModelRole, ModelKind> = {
  'llm.primary': 'llm',
  'llm.screening': 'llm',
  'stt.streaming': 'stt',
  'stt.batch': 'stt',
  embedding: 'embedding',
  diarization: 'diarization',
  'document.reading': 'reading',
  'document.ocr': 'ocr',
  'document.pdf': 'pdf_reader',
  'document.hwp': 'hwp_reader',
  'document.legacy': 'office_converter',
}
export type ModelChangeKind = 'initial' | 'apply' | 'rollback'
export type ModelOptionType = 'string' | 'text' | 'integer' | 'number' | 'boolean' | 'select'
export type ModelOptionValue = string | number | boolean
export type DownloadStatus = 'missing' | 'downloading' | 'done' | 'failed' | 'cancelled'

export interface ModelSpec {
  impl: string
  options: Record<string, ModelOptionValue>
}

/** What this machine lacks for a provider. Never carries a secret, only whether it exists. */
export interface ModelRequirement {
  key: string
  label: string
  ok: boolean
  detail: string
  fix: string | null
}

export interface ModelOptionChoice {
  value: string
  label: string
  note: string
  /** weights to download for this choice */
  size_bytes: number | null
  recommended_for: string[]
  /** null: nothing to download */
  downloaded: boolean | null
}

export interface ModelOptionField {
  key: string
  label: string
  type: ModelOptionType
  default: ModelOptionValue | null
  help: string
  minimum: number | null
  maximum: number | null
  max_length: number
  choices: ModelOptionChoice[]
  /** shown for these roles only (empty: every role) */
  roles: string[]
  /** shown, not editable */
  fixed: boolean
}

export interface ModelImpl {
  kind: ModelKind
  impl: string
  label: string
  description: string
  data_location: DataLocation
  data_note: string
  license: string
  roles: string[]
  options: ModelOptionField[]
  role_defaults: Record<string, Record<string, ModelOptionValue>>
  role_notes: Record<string, string>
  /** machine-level requirements (package, credentials ...); downloads are per model choice */
  requirements: ModelRequirement[]
}

export interface ModelActor {
  id: string
  employee_no: string
  name: string
}

export interface ModelChange {
  id: string
  revision: number
  occurred_at: string
  role: string
  role_label: string
  kind: ModelChangeKind
  /** null: the system (first start, seeded from the providers YAML) */
  actor: ModelActor | null
  previous: ModelSpec | null
  new: ModelSpec
  previous_label: string | null
  new_label: string
  reason: string | null
  reverts_change_id: string | null
  details: Record<string, unknown> | null
}

export interface ModelRoleState {
  role: ModelRole
  label: string
  description: string
  kind: ModelKind
  group: ModelGroup
  spec: ModelSpec
  impl_label: string
  /** the model name stored next to results and in the audit log */
  model: string
  data_location: DataLocation
  status: 'ready' | 'unavailable'
  status_detail: string | null
  requirements: ModelRequirement[]
  note: string | null
  last_change: ModelChange | null
  /** interviews in progress (or being scored) still on an earlier config of this role */
  pinned_sessions: number
}

export interface ModelSettings {
  revision: number
  /** false: the settings tables are missing and nothing can be saved */
  persistent: boolean
  roles: ModelRoleState[]
}

export interface ModelCheck {
  role: string
  spec: ModelSpec
  data_location: DataLocation
  external: boolean
  requirements: ModelRequirement[]
  ready: boolean
  same_as_active: boolean
}

export interface ModelTestResult {
  ok: boolean
  model: string
  latency_ms: number
  summary: string
  /** role-specific: text / expected_text / cer / realtime_factor (STT), structured (LLM), dimensions,
   *  pages / images / tools / preview (서류 읽기: see ReadingTestOutput) ... */
  output: Record<string, unknown>
  error: string | null
  audio: 'sample' | 'upload' | null
  /** 서류 읽기 roles: the built-in fictional resume or the admin's file */
  document?: 'sample' | 'upload' | null
}

/** One page of a 서류 읽기 test: how it was read. */
export interface ReadingTestPage {
  page: number
  method: 'text' | 'ocr' | 'held'
  reason: string | null
  tool: string | null
  confidence: number | null
  elapsed_ms: number | null
  text_chars: number
}

/** One picture inside the document and what was done with it. */
export interface ReadingTestImage {
  label: string
  decision: 'photo' | 'ocr' | 'skipped' | 'small' | 'failed'
  confidence: number | null
  detail: string
}

/** `output` of a 서류 읽기 test. The preview is de-identified; the raw text never comes back. */
export interface ReadingTestOutput {
  format: string | null
  pages?: ReadingTestPage[]
  images?: ReadingTestImage[]
  tools?: string[]
  warnings?: string[]
  read_ms?: number
  cer?: number
  preview?: string
  preview_truncated?: boolean
  replacements?: number
}

export interface ModelDownload {
  impl: string
  model: string
  status: DownloadStatus
  total_bytes: number
  downloaded_bytes: number
  error: string | null
}

export interface ApplyModelRequest extends ModelSpec {
  reason: string
  confirm_external: boolean
}

export interface RevertModelRequest {
  reason: string
  confirm_external: boolean
}

// --- 관리자 > 연동 현황 (applications from the recruiting site, admin only) ------------------------

export interface UpdatePostingRequest {
  /** null or '' unlinks the posting */
  site_posting_no: string | null
}

export const INTAKE_EVENT_TYPES = ['submitted', 'updated', 'withdrawn'] as const
export type IntakeEventType = (typeof INTAKE_EVENT_TYPES)[number]
export const INTAKE_STATUSES = ['queued', 'processing', 'done', 'skipped', 'failed', 'rejected'] as const
export type IntakeStatus = (typeof INTAKE_STATUSES)[number]

export interface IntakeFailure {
  /** unknown_posting, posting_closed, unsupported_attachment, ocr_required, forbidden_field ... */
  code: string
  message: string
  /** field paths only, never values */
  fields: string[]
}

/** One event the site sent. No name and no applicant number exist to show. */
export interface IntakeEvent {
  id: string
  event_id: string
  event_type: IntakeEventType | null
  status: IntakeStatus
  revision: number | null
  occurred_at: string | null
  received_at: string
  started_at: string | null
  finished_at: string | null
  processing_ms: number | null
  attempts: number
  posting_no: string | null
  posting: Pick<JobPosting, 'id' | 'title'> | null
  application_no: string | null
  candidate: Pick<Candidate, 'id' | 'pseudonym'> | null
  failure: IntakeFailure | null
  /** fields outside the spec that were dropped before storing (paths) */
  dropped_fields: string[]
  /** failed with the payload kept: 다시 처리 can queue it again */
  retriable: boolean
  result: Record<string, unknown> | null
}

export interface IntakeTotals {
  received: number
  queued: number
  processing: number
  done: number
  skipped: number
  failed: number
  rejected: number
}

export interface IntakePostingCount {
  posting_no: string | null
  /** null: no posting carries this number yet */
  posting: Pick<JobPosting, 'id' | 'title'> | null
  received: number
  submitted: number
  updated: number
  withdrawn: number
  done: number
  skipped: number
  failed: number
  rejected: number
  /** queued + processing */
  pending: number
  /** active applications from the site on the posting */
  applications: number
}

export interface IntakeTiming {
  processed: number
  avg_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
  max_ms: number | null
  avg_wait_ms: number | null
  first_received_at: string | null
  last_finished_at: string | null
  per_minute: number | null
}

export interface IntakeSummary {
  /** the site's signing key is set on the server */
  configured: boolean
  workers: number
  totals: IntakeTotals
  postings: IntakePostingCount[]
  failures: { code: string; count: number; retriable: number }[]
  timing: IntakeTiming
}

export interface IntakeEventFilter {
  status?: IntakeStatus
  posting_no?: string
}
