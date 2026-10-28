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

/** A person's decision on a round (N차 결정): 합격 / 보류 / 불합격. */
export const DECISION_STATUSES = ['passed', 'hold', 'rejected'] as const
export type DecisionStatus = (typeof DECISION_STATUSES)[number]

/** Who noted a point for a later round to check (확인이 필요한 점). */
export const CHECK_POINT_SOURCES = ['interviewer', 'ai'] as const
export type CheckPointSource = (typeof CHECK_POINT_SOURCES)[number]

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
 * models.InterviewRound: one round of a posting's interview process (전형 차수). `label` is always
 * "{position}차"; `name` says what the round is for ("직무 면접"). Headers show "2차 · 임원 면접".
 */
export interface InterviewRound {
  id: string
  posting_id: string
  position: number
  label: string
  name: string
  default_mode: SessionMode
  recommended_interviewers: number
  /** interviewers of this round see earlier rounds' scores (off by default) */
  show_previous_scores: boolean
  created_at: string
}

/**
 * models.CompetencySet: one version of a round's dictionary. Approved when `approved_at` is set;
 * approved versions are read-only. `approved_by` holds the approver's interviewer id.
 */
export interface CompetencySet {
  id: string
  posting_id: string
  round_id: string
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
  round_id: string
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

/** models.RoundDecision: one revision of a decision on an application in a round. Newest wins. */
export interface RoundDecision {
  id: string
  application_id: string
  round_id: string
  session_id: string | null
  revision: number
  decision: DecisionStatus
  /** de-identified */
  reason: string
  decided_by: string
  decided_by_name: string
  created_at: string
}

/** models.CheckPoint: 확인이 필요한 점 for a later round. AI ones quote the answer in `evidence`. */
export interface CheckPoint {
  id: string
  session_id: string
  source: CheckPointSource
  competency: string | null
  text: string
  evidence: string | null
  qa_item_id: string | null
  author_id: string | null
  author_name: string | null
  model: string | null
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

export interface RoundRef {
  id: string
  position: number
  label: string
  name: string
  is_last: boolean
}

/** The round of a session, with what its interviewers may see of earlier rounds. */
export interface RoundView extends RoundRef {
  /** how many rounds the posting has */
  rounds: number
  show_previous_scores: boolean
}

export const STEP_KINDS = ['screening', 'round', 'final'] as const
export type StepKind = (typeof STEP_KINDS)[number]

/**
 * Where an application stands in a step (interviews.py). Rounds: waiting (일정 대기) → scheduled →
 * in_progress → evaluating (평가 대기) → deciding (결정 대기) → passed / hold / rejected. The
 * screening step uses passed / hold / rejected (waiting before screening), 최종 only passed.
 */
export const STEP_STATUSES = ['waiting', 'scheduled', 'in_progress', 'evaluating', 'deciding', 'passed', 'hold', 'rejected'] as const
export type StepStatus = (typeof STEP_STATUSES)[number]

/** One step of an application: 서류, a round, or 최종. `status` null: not reached yet. */
export interface ProgressStep {
  kind: StepKind
  round: RoundRef | null
  status: StepStatus | null
  at: string | null
  session_id: string | null
}

/** Applications that reached a round, and how many are at each status in it. */
export interface RoundCount extends Record<StepStatus, number> {
  round: RoundRef
  reached: number
}

export interface PostingCounts {
  applications: number
  passed: number
  hold: number
  rejected: number
  /** applications whose current step has a scheduled or running session */
  interviewing: number
  /** applications with a completed session */
  interviewed: number
  /** of those, AI scoring finished and every session interviewer submitted */
  evaluated: number
  /** per round: 서류 → 1차 → 2차 … */
  rounds: RoundCount[]
  /** passed the last round: 최종 합격 후보 (the official result is the recruiting site's) */
  final: number
}

export interface CompetencySetBrief {
  id: string
  version: number
  approved_at: string | null
}

/** GET /api/postings item */
export interface PostingSummary extends Omit<JobPosting, 'jd_text'> {
  counts: PostingCounts
  rounds: RoundRef[]
  /** round 1's dictionary (screening uses its approved version) */
  latest_competency_set: CompetencySetBrief | null
  approved_competency_set: CompetencySetBrief | null
}

/** GET /api/postings/{id} */
export interface PostingDetail extends JobPosting {
  counts: PostingCounts
  rounds: RoundRef[]
}

/** GET /api/postings/{id}/rounds item */
export interface RoundSummary extends InterviewRound {
  is_last: boolean
  latest_competency_set: CompetencySetBrief | null
  approved_competency_set: CompetencySetBrief | null
  /** preset questions of the approved version */
  preset_count: number
  /** sessions held or scheduled in the round */
  sessions: number
  /** has sessions or decisions: cannot move or be deleted */
  locked: boolean
}

/** GET /api/postings/{id}/applications item: one row of the screening table. */
export interface ApplicationRow {
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  screening: Screening | null
  years_experience: number | null
  top_skills: string[]
  /** the current step */
  stage: ProgressStep
  /** 서류 → each round → 최종 */
  progress: ProgressStep[]
  channel: ApplicationChannel
  created_at: string
}

export interface SessionBrief {
  id: string
  round: RoundRef
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
  stage: ProgressStep
  progress: ProgressStep[]
  /** every revision of every round, newest first */
  decisions: RoundDecision[]
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

/**
 * GET /api/applications/schedulable item: an application waiting for `round` (round 1: passed
 * screening; round N: passed round N-1). `mode` and `recommended_interviewers` are the round's.
 */
export interface SchedulableApplication {
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family'>
  fit_score: number
  round: RoundRef
  mode: SessionMode
  recommended_interviewers: number
  /** when the previous step was passed */
  since: string | null
}

export interface SessionInterviewerView extends SessionInterviewer {
  interviewer: Interviewer
}

/** GET /api/sessions item */
export interface SessionSummary extends InterviewSession {
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title'>
  round: RoundRef
  /** the application's status in this session's round */
  round_status: StepStatus
  interviewers: SessionInterviewerView[]
  qa_count: number
  ai_scoring: AiScoringStatus
  /** interviewer ids that submitted scores */
  submitted_interviewer_ids: string[]
}

/** What an AI carry-over question (이어 질문) builds on: an earlier round's answer. */
export interface CarryoverOrigin {
  round: RoundRef
  /** the earlier question, de-identified */
  question: string
  /** verbatim quote of the earlier answer */
  grounding: string
  rationale: string
  model: string | null
}

/** models.PresetQuestion (FR-06 사전 질문). `origin` is set on carry-over questions only. */
export interface PresetQuestion {
  id: string
  competency: string
  question: string
  intent: string
  origin?: CarryoverOrigin | null
}

export interface PreviousNote {
  id: string
  content: string
  author_name: string
  created_at: string
}

/** An earlier round's scores per competency, only when the round shows them. Never combined. */
export interface PreviousScore {
  competency: string
  interviewer_mean: number | null
  ai_mean: number | null
}

/**
 * 이전 차수 요약. Points to check and notes always; scores and the decision reason only when the
 * session's round shows earlier scores (`scores_visible`), otherwise the server leaves them null.
 */
export interface PreviousRound {
  round: RoundRef
  session: SessionBrief
  decision: DecisionStatus | null
  qa_count: number
  check_points: CheckPoint[]
  notes: PreviousNote[]
  scores_visible: boolean
  scores: PreviousScore[] | null
  decision_reason: string | null
}

/** Candidate summary card (FR-04): de-identified profile + screening digest + earlier rounds. */
export interface CandidateCard {
  candidate: Pick<Candidate, 'id' | 'pseudonym' | 'consent_recording' | 'consent_at'>
  profile: CandidateProfile | null
  screening: Pick<Screening, 'fit_score' | 'status' | 'rationale'> | null
  previous_sessions: SessionBrief[]
  previous_rounds: PreviousRound[]
}

/** GET /api/sessions/{id} */
export interface SessionDetail {
  session: InterviewSession
  posting: Pick<JobPosting, 'id' | 'title' | 'job_family'>
  round: RoundView
  card: CandidateCard
  interviewers: SessionInterviewerView[]
  competency_set: CompetencySet | null
  preset_questions: PresetQuestion[]
  /** 이어 질문: AI questions for this candidate built on earlier rounds' answers */
  carryover_questions: PresetQuestion[]
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
  /** why transcription is down: a short code to copy down by hand (docs/audio-input.md 6장) */
  error?: AudioErrorBody | null
  /** the session's microphone, once one was attached (null: the simulated candidate) */
  mic?: MicStatus | null
}

/** Whose speech the microphone carries: 답변 듣는 중 (candidate) or 질문 중 (interviewer). */
export type MicRole = 'candidate' | 'interviewer'

export interface AudioErrorBody {
  code: string
  message: string
}

export interface MicStatus {
  connected: boolean
  transport: 'websocket' | 'http' | null
  role: MicRole
  /** the server's VAD hears speech now */
  speaking: boolean
  /** the end-of-answer detector in use (silence-2000ms, smart-turn-v3.2-cpu) */
  turn: string | null
  /** codes of what runs degraded: VAD-MISSING, TURN-MISSING, STT-MISSING, REC-FAILED ... */
  notices: string[]
  /** how the last answer part ended */
  last_end: { reason: string | null; probability: number | null; at_ms: number } | null
}

/** POST /api/sessions/{id}/live/role */
export interface MicRoleResult {
  role: MicRole
  /** the question asked aloud while the role was interviewer, recorded as the next question */
  qa_item: QAItem | null
}

/** GET /api/live/audio-samples: bundled audio the browser can play instead of a microphone. */
export interface AudioSample {
  name: string
  label: string
  seconds: number
  text: string
  note: string
}

export type TranscriptEvent =
  | { event: 'status'; data: StreamStatus }
  | { event: 'segment.partial'; data: TranscriptSegment }
  | { event: 'segment.final'; data: TranscriptSegment }
  | { event: 'qa.answered'; data: { qa_item_id: string; answer_deidentified: string; answered_at: string } }
  | { event: 'qa.created'; data: QAItem }

/** GET /api/sessions/{id}/transcript: final segments so far (history on (re)connect). */
export interface TranscriptHistory {
  segments: TranscriptSegment[]
}

// --- Follow-up suggestions (SSE: POST /api/sessions/{id}/follow-ups) --------------------------

export interface FollowUpRequest {
  qa_item_id: string
}

/** Where a follow-up came from: the question bank (approved by recruiters) or the LLM. */
export type SuggestionSource = 'bank' | 'ai'

export interface SuggestionMeta {
  batch_id: string
  suggestion_id: string
  index: number
  competency: string
  source: SuggestionSource
}

export interface SuggestionDone extends SuggestionMeta {
  question: string
  /** why this follow-up (생성 근거; for the bank, the question's intent) */
  rationale: string
  /** quote from the de-identified answer the question builds on */
  grounding: string
  /** bank only: the question-bank item and its retrieval score */
  bank_item_id?: string
  score?: number
  /** AI only: shown before its duplicate check; `suggestion.checked` or `suggestion.discarded` follows */
  checking?: boolean
}

export type FollowUpEvent =
  | {
      event: 'batch.start'
      data: { batch_id: string; qa_item_id: string; model: string; prompt_version: string; retrieval_model: string | null }
    }
  | { event: 'suggestion.start'; data: SuggestionMeta }
  | { event: 'suggestion.delta'; data: { batch_id: string; suggestion_id: string; text: string } }
  | { event: 'suggestion.done'; data: SuggestionDone }
  /** the AI suggestion shown with `checking` is not a duplicate: it can be used */
  | { event: 'suggestion.checked'; data: { batch_id: string; suggestion_id: string } }
  /** an AI suggestion already shown turned out to mean the same as a question already asked: fold its card away */
  | {
      event: 'suggestion.discarded'
      data: { batch_id: string; suggestion_id: string; reason: 'duplicate'; duplicate_of: string; similarity: number }
    }
  | { event: 'batch.done'; data: { batch_id: string; discarded?: number } }
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

/** N차 결정 on the evaluation screen. A person decides; AI scores are reference only. */
export interface DecisionPanel {
  current: RoundDecision | null
  /** newest first */
  history: RoundDecision[]
  can_decide: boolean
  blocked_reason: string | null
  /** a pass makes a final candidate (recorded officially on the recruiting site) */
  is_last_round: boolean
  next_round: RoundRef | null
}

/** GET /api/sessions/{id}/evaluation */
export interface Evaluation {
  session: InterviewSession
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title'>
  round: RoundView
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
  decision: DecisionPanel
  /** for later rounds: interviewers' and AI's */
  check_points: CheckPoint[]
}

/** POST /api/sessions/{id}/decision */
export interface DecisionRequest {
  decision: DecisionStatus
  reason: string
}

/** POST /api/sessions/{id}/check-points */
export interface CreateCheckPointRequest {
  text: string
  competency?: string | null
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

/** An evaluated round waiting for a decision, or one decided 보류 (it stays on the list). */
export interface PendingDecision {
  session_id: string
  application_id: string
  candidate: Pick<Candidate, 'id' | 'pseudonym'>
  posting: Pick<JobPosting, 'id' | 'title'>
  round: RoundRef
  status: 'deciding' | 'hold'
  since: string | null
}

/** GET /api/dashboard */
export interface DashboardSummary {
  pipeline: PipelineRow[]
  today_sessions: SessionSummary[]
  /** completed sessions where the signed-in interviewer has not submitted scores */
  pending_my_scores: SessionSummary[]
  pending_decisions: PendingDecision[]
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
  /** left out: the round the application is waiting for */
  round_id?: string
  mode: SessionMode
  scheduled_at: string
  interviewers: { interviewer_id: string; role: InterviewerRole }[]
}

// --- 전형 (interview rounds) -------------------------------------------------------------------

export interface CreateRoundRequest {
  name: string
  default_mode?: SessionMode
  recommended_interviewers?: number
  show_previous_scores?: boolean
}

export type UpdateRoundRequest = Partial<CreateRoundRequest>

export interface PresetQuestionBody {
  competency: string
  question: string
  intent?: string
}

// --- 관리자 > 모델 설정 (admin only) ------------------------------------------------------------

/**
 * Where a provider sends data: this PC, the in-house server whose address the admin entered (open-weight
 * model server), Google Cloud (outside the company, not used), or another API outside the company.
 */
export const DATA_LOCATIONS = ['local', 'server', 'gcp', 'external'] as const
export type DataLocation = (typeof DATA_LOCATIONS)[number]

/** Sending data there needs the admin's confirmation (and a reason to apply or roll back). */
export const leavesCompany = (location: DataLocation | undefined) => location === 'gcp' || location === 'external'

/** The AI roles, then the 서류 읽기 roles, then the 음성 입력 roles, in display order. */
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
  'audio.vad',
  'audio.turn',
  'audio.denoise',
] as const
export type ModelRole = (typeof MODEL_ROLES)[number]
/** Heading the role is shown under: AI 모델, 서류 읽기 or 음성 입력. */
export type ModelGroup = 'ai' | 'documents' | 'audio'
export const isDocumentRole = (role: string) => role.startsWith('document.')

export type ModelKind =
  | 'llm'
  | 'stt'
  | 'embedding'
  | 'diarization'
  | 'reading'
  | 'ocr'
  | 'pdf_reader'
  | 'hwp_reader'
  | 'office_converter'
  | 'vad'
  | 'turn'
  | 'denoise'
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
  'audio.vad': 'vad',
  'audio.turn': 'turn',
  'audio.denoise': 'denoise',
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

// --- 질문 은행·평점 기준 예시 (retrieval) ------------------------------------------------------

export type BankStatus = 'draft' | 'approved' | 'retired'
export type BankSource = 'manual' | 'csv' | 'seed'

/** A prohibited-question warning (채용 면접 금지 질문): a rule match or the AI check. */
export interface BankFlag {
  category: string
  label: string
  basis: string
  matched: string
  source: 'rule' | 'ai'
  note: string
}

export interface BankPerson {
  id: string
  name: string
}

export interface QuestionBankItem {
  id: string
  job_family: string
  competency: string
  /** 1차, 2차 …; null = any round */
  round_position: number | null
  question: string
  intent: string
  follow_ups: string[]
  status: BankStatus
  flags: BankFlag[]
  source: BankSource
  created_by: BankPerson | null
  approved_by: BankPerson | null
  created_at: string
  updated_at: string
  approved_at: string | null
  retired_at: string | null
}

export interface BankFamily {
  job_family: string
  competencies: string[]
}

export interface QuestionBankList {
  items: QuestionBankItem[]
  families: BankFamily[]
  counts: Record<BankStatus, number>
  total: number
}

export interface QuestionBankFilter {
  job_family?: string
  competency?: string
  round?: number
  status?: BankStatus
  q?: string
}

export interface BankQuestionBody {
  job_family: string
  competency: string
  round_position: number | null
  question: string
  intent: string
  follow_ups: string[]
}

export interface ImportRowIssue {
  row: number
  message: string
}

export interface ImportResult {
  dry_run: boolean
  rows: number
  created: number
  skipped: number
  errors: ImportRowIssue[]
  warnings: ImportRowIssue[]
}

export interface RubricOverlap {
  id: string
  score: number
  similarity: number
}

/** 평점 기준 예시: a made-up answer at one score of one competency, shown to the scoring model as an anchor. */
export interface RubricExample {
  id: string
  job_family: string
  competency: string
  score: number
  question: string
  answer: string
  rationale: string
  status: BankStatus
  source: BankSource
  created_by: BankPerson | null
  approved_by: BankPerson | null
  created_at: string
  updated_at: string
  approved_at: string | null
  retired_at: string | null
  /** approved examples of the same competency at another score that read almost the same */
  overlaps: RubricOverlap[]
}

export interface RubricExampleBody {
  job_family: string
  competency: string
  score: number
  question: string
  answer: string
  rationale: string
}

export interface RubricList {
  items: RubricExample[]
  families: BankFamily[]
  counts: Record<BankStatus, number>
}

export interface EmbeddingIndexState {
  index_key: string
  model: string
  dimensions: number
  status: 'building' | 'ready' | 'failed'
  total: number
  done: number
  started_at: string
  finished_at: string | null
  error: string | null
  /** searches use this one now */
  serving: boolean
}

export interface EmbeddingIndexStatus {
  active_model: string | null
  active_index_key: string | null
  serving_index_key: string | null
  /** vectors searched now, by owner type (question / rubric / competency_set) */
  counts: Record<string, number>
  indexes: EmbeddingIndexState[]
}

export interface SourceMetrics {
  source: SuggestionSource
  shown: number
  used: number
  edited: number
  adoption_rate: number | null
  batches: number
  first_ms_median: number | null
  first_ms_p90: number | null
}

export interface FollowUpMetrics {
  since: string
  days: number
  batches: number
  sources: SourceMetrics[]
  duplicates: { bank: number; ai: number; total: number }
  retrieval_model: string | null
}
