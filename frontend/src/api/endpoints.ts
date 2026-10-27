/** One function per REST endpoint (docs/api-contract.md). */
import { api } from './client'
import type {
  ActivityItem,
  ApplicationDetail,
  ApplyModelRequest,
  ApplicationRow,
  BankFlag,
  BankQuestionBody,
  EmbeddingIndexStatus,
  FollowUpMetrics,
  ImportResult,
  IntakeEvent,
  IntakeEventFilter,
  IntakeSummary,
  Availability,
  CandidateIndexItem,
  CandidateNote,
  CheckPoint,
  Competency,
  CompetencySet,
  CreateAvailabilityRequest,
  CreateCheckPointRequest,
  CreateQARequest,
  CreateRoundRequest,
  CreateSessionRequest,
  DashboardSummary,
  DecisionRequest,
  Evaluation,
  Interviewer,
  Me,
  ModelChange,
  ModelCheck,
  ModelDownload,
  ModelImpl,
  ModelRoleState,
  ModelSettings,
  ModelSpec,
  ModelTestResult,
  PostingDetail,
  PostingSummary,
  PresetQuestion,
  PresetQuestionBody,
  QAItem,
  QuestionBankFilter,
  QuestionBankItem,
  QuestionBankList,
  RevertModelRequest,
  RubricExample,
  RubricExampleBody,
  RubricList,
  RoundDecision,
  RoundSummary,
  SchedulableApplication,
  ScheduleSuggestion,
  ScheduleSuggestionRequest,
  Screening,
  ScreeningStatus,
  SessionDetail,
  SessionStatus,
  SessionSummary,
  SubmitInterviewerScoresRequest,
  TranscriptHistory,
  UpdatePostingRequest,
  UpdateRoundRequest,
  UploadApplicationRequest,
  UploadResult,
} from './types'

export const endpoints = {
  me: (signal?: AbortSignal) => api.get<Me>('/me', signal),
  dashboard: (signal?: AbortSignal) => api.get<DashboardSummary>('/dashboard', signal),
  activity: (limit: number, signal?: AbortSignal) => api.get<ActivityItem[]>(`/activity?limit=${limit}`, signal),

  postings: (signal?: AbortSignal) => api.get<PostingSummary[]>('/postings', signal),
  posting: (id: string, signal?: AbortSignal) => api.get<PostingDetail>(`/postings/${id}`, signal),
  updatePosting: (id: string, body: UpdatePostingRequest) => api.patch<PostingDetail>(`/postings/${id}`, body),
  competencySets: (postingId: string, signal?: AbortSignal) =>
    api.get<CompetencySet[]>(`/postings/${postingId}/competency-sets`, signal),
  updateCompetencySet: (id: string, competencies: Competency[]) =>
    api.put<CompetencySet>(`/competency-sets/${id}`, { competencies }),
  approveCompetencySet: (id: string) => api.post<CompetencySet>(`/competency-sets/${id}/approve`),

  // 전형 (차수)
  rounds: (postingId: string, signal?: AbortSignal) => api.get<RoundSummary[]>(`/postings/${postingId}/rounds`, signal),
  createRound: (postingId: string, body: CreateRoundRequest) => api.post<RoundSummary>(`/postings/${postingId}/rounds`, body),
  updateRound: (roundId: string, body: UpdateRoundRequest) => api.patch<RoundSummary>(`/rounds/${roundId}`, body),
  deleteRound: (roundId: string) => api.delete<void>(`/rounds/${roundId}`),
  reorderRounds: (postingId: string, roundIds: string[]) =>
    api.put<RoundSummary[]>(`/postings/${postingId}/rounds/order`, { round_ids: roundIds }),
  roundSets: (roundId: string, signal?: AbortSignal) => api.get<CompetencySet[]>(`/rounds/${roundId}/competency-sets`, signal),
  createRoundSet: (roundId: string, competencies: Competency[]) =>
    api.post<CompetencySet>(`/rounds/${roundId}/competency-sets`, { competencies }),
  generateRoundSet: (roundId: string) => api.post<CompetencySet>(`/rounds/${roundId}/competency-sets/generate`),
  presetQuestions: (setId: string, signal?: AbortSignal) =>
    api.get<PresetQuestion[]>(`/competency-sets/${setId}/preset-questions`, signal),
  createPresetQuestion: (setId: string, body: PresetQuestionBody) =>
    api.post<PresetQuestion>(`/competency-sets/${setId}/preset-questions`, body),
  generatePresetQuestions: (setId: string) => api.post<PresetQuestion[]>(`/competency-sets/${setId}/preset-questions/generate`),
  updatePresetQuestion: (id: string, body: PresetQuestionBody) => api.put<PresetQuestion>(`/preset-questions/${id}`, body),
  deletePresetQuestion: (id: string) => api.delete<void>(`/preset-questions/${id}`),

  applications: (postingId: string, signal?: AbortSignal) =>
    api.get<ApplicationRow[]>(`/postings/${postingId}/applications`, signal),
  uploadApplication: (postingId: string, body: UploadApplicationRequest) => {
    const form = new FormData()
    form.append('file', body.file)
    form.append('name', body.name)
    if (body.aliases) form.append('aliases', body.aliases)
    if (body.phone) form.append('phone', body.phone)
    if (body.email) form.append('email', body.email)
    return api.postForm<UploadResult>(`/postings/${postingId}/applications`, form)
  },
  application: (id: string, signal?: AbortSignal) => api.get<ApplicationDetail>(`/applications/${id}`, signal),
  schedulableApplications: (signal?: AbortSignal) => api.get<SchedulableApplication[]>('/applications/schedulable', signal),
  decisions: (applicationId: string, signal?: AbortSignal) => api.get<RoundDecision[]>(`/applications/${applicationId}/decisions`, signal),
  updateScreening: (id: string, status: ScreeningStatus) => api.patch<Screening>(`/screenings/${id}`, { status }),
  candidates: (signal?: AbortSignal) => api.get<CandidateIndexItem[]>('/candidates', signal),

  sessions: (status?: SessionStatus, signal?: AbortSignal) =>
    api.get<SessionSummary[]>(`/sessions${status ? `?status=${status}` : ''}`, signal),
  session: (id: string, signal?: AbortSignal) => api.get<SessionDetail>(`/sessions/${id}`, signal),
  createSession: (body: CreateSessionRequest) => api.post<SessionSummary>('/sessions', body),
  recordConsent: (id: string, consent: boolean) => api.post<SessionDetail>(`/sessions/${id}/consent`, { consent_recording: consent }),
  startSession: (id: string) => api.post<SessionDetail>(`/sessions/${id}/start`),
  endSession: (id: string) => api.post<SessionDetail>(`/sessions/${id}/end`),
  createQA: (sessionId: string, body: CreateQARequest) => api.post<QAItem>(`/sessions/${sessionId}/qa-items`, body),
  answerQA: (qaId: string, answerText: string) => api.patch<QAItem>(`/qa-items/${qaId}`, { answer_text: answerText }),
  createNote: (sessionId: string, content: string) => api.post<CandidateNote>(`/sessions/${sessionId}/notes`, { content }),
  transcript: (sessionId: string, signal?: AbortSignal) => api.get<TranscriptHistory>(`/sessions/${sessionId}/transcript`, signal),
  carryoverQuestions: (sessionId: string) => api.post<SessionDetail>(`/sessions/${sessionId}/carryover-questions`),

  evaluation: (sessionId: string, signal?: AbortSignal) => api.get<Evaluation>(`/sessions/${sessionId}/evaluation`, signal),
  submitScores: (sessionId: string, interviewerId: string, body: SubmitInterviewerScoresRequest) =>
    api.put<Evaluation>(`/sessions/${sessionId}/scores/${interviewerId}`, body),
  decide: (sessionId: string, body: DecisionRequest) => api.post<Evaluation>(`/sessions/${sessionId}/decision`, body),
  createCheckPoint: (sessionId: string, body: CreateCheckPointRequest) =>
    api.post<CheckPoint>(`/sessions/${sessionId}/check-points`, body),
  deleteCheckPoint: (id: string) => api.delete<void>(`/check-points/${id}`),

  interviewers: (signal?: AbortSignal) => api.get<Interviewer[]>('/interviewers', signal),
  availabilities: (from: string, to: string, signal?: AbortSignal) =>
    api.get<Availability[]>(`/availabilities?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, signal),
  createAvailability: (body: CreateAvailabilityRequest) => api.post<Availability>('/availabilities', body),
  deleteAvailability: (id: string) => api.delete<void>(`/availabilities/${id}`),
  scheduleSuggestions: (body: ScheduleSuggestionRequest) => api.post<ScheduleSuggestion[]>('/schedule/suggestions', body),

  // 관리자 > 모델 설정 (admins only, 403 otherwise)
  modelSettings: (signal?: AbortSignal) => api.get<ModelSettings>('/admin/models', signal),
  modelCatalog: (signal?: AbortSignal) => api.get<ModelImpl[]>('/admin/models/catalog', signal),
  checkModel: (role: string, spec: ModelSpec) => api.post<ModelCheck>(`/admin/models/${role}/check`, spec),
  /** STT and diarization take `audio` (a recording or file); without it the server's Korean sample.
   *  서류 읽기 roles take `document` (and the applicant's `name` for the preview's de-identification);
   *  without it the server's built-in fictional resume. */
  testModel: (
    role: string,
    spec: ModelSpec,
    opts: { confirmExternal?: boolean; audio?: Blob | null; document?: File | null; name?: string } = {},
  ) => {
    const form = new FormData()
    form.append('spec', JSON.stringify(spec))
    form.append('confirm_external', String(Boolean(opts.confirmExternal)))
    if (opts.audio) form.append('audio', opts.audio, opts.audio instanceof File ? opts.audio.name : 'recording.webm')
    if (opts.document) form.append('document', opts.document, opts.document.name)
    if (opts.name) form.append('name', opts.name)
    return api.postForm<ModelTestResult>(`/admin/models/${role}/test`, form)
  },
  applyModel: (role: string, body: ApplyModelRequest) => api.post<ModelRoleState>(`/admin/models/${role}/apply`, body),
  modelHistory: (signal?: AbortSignal) => api.get<ModelChange[]>('/admin/models/history?limit=50', signal),
  revertModel: (changeId: string, body: RevertModelRequest) => api.post<ModelRoleState>(`/admin/models/history/${changeId}/revert`, body),
  modelDownloads: (signal?: AbortSignal) => api.get<ModelDownload[]>('/admin/models/downloads', signal),
  startDownload: (impl: string, model: string) => api.post<ModelDownload>('/admin/models/downloads', { impl, model }),
  cancelDownload: (impl: string, model: string) => api.delete<ModelDownload>(`/admin/models/downloads/${impl}/${model}`),

  // 관리자 > 연동 현황 (admins only)
  intakeSummary: (signal?: AbortSignal) => api.get<IntakeSummary>('/admin/intake/summary', signal),
  intakeEvents: (filter: IntakeEventFilter, signal?: AbortSignal) => {
    const q = new URLSearchParams({ limit: '500' })
    if (filter.status) q.set('status', filter.status)
    if (filter.posting_no) q.set('posting_no', filter.posting_no)
    return api.get<IntakeEvent[]>(`/admin/intake/events?${q.toString()}`, signal)
  },
  retryIntakeEvent: (id: string) => api.post<IntakeEvent>(`/admin/intake/events/${id}/retry`),
  retryIntake: (body: { failure_code?: string; posting_no?: string }) => api.post<{ requeued: number }>('/admin/intake/retry', body),

  // 질문 은행 (writing drafts: everyone; approve, retire, restore, import, AI check: admins)
  questionBank: (filter: QuestionBankFilter, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== '') q.set(k, String(v))
    return api.get<QuestionBankList>(`/question-bank?${q.toString()}`, signal)
  },
  checkQuestion: (body: { question: string; follow_ups: string[] }) => api.post<{ flags: BankFlag[] }>('/question-bank/check', body),
  createQuestion: (body: BankQuestionBody) => api.post<QuestionBankItem>('/question-bank', body),
  updateQuestion: (id: string, body: BankQuestionBody) => api.put<QuestionBankItem>(`/question-bank/${id}`, body),
  approveQuestion: (id: string, confirmWarnings: boolean) =>
    api.post<QuestionBankItem>(`/question-bank/${id}/approve`, { confirm_warnings: confirmWarnings }),
  retireQuestion: (id: string) => api.post<QuestionBankItem>(`/question-bank/${id}/retire`),
  restoreQuestion: (id: string) => api.post<QuestionBankItem>(`/question-bank/${id}/restore`),
  aiCheckQuestion: (id: string) => api.post<QuestionBankItem>(`/question-bank/${id}/ai-check`),
  importQuestions: (file: File, dryRun: boolean) => {
    const form = new FormData()
    form.set('file', file)
    form.set('dry_run', String(dryRun))
    return api.postForm<ImportResult>('/question-bank/import', form)
  },

  // 평점 기준 예시
  rubricExamples: (filter: { job_family?: string; competency?: string }, signal?: AbortSignal) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(filter)) if (v) q.set(k, v)
    return api.get<RubricList>(`/rubric-examples?${q.toString()}`, signal)
  },
  createRubric: (body: RubricExampleBody) => api.post<RubricExample>('/rubric-examples', body),
  updateRubric: (id: string, body: RubricExampleBody) => api.put<RubricExample>(`/rubric-examples/${id}`, body),
  approveRubric: (id: string) => api.post<RubricExample>(`/rubric-examples/${id}/approve`),
  retireRubric: (id: string) => api.post<RubricExample>(`/rubric-examples/${id}/retire`),
  restoreRubric: (id: string) => api.post<RubricExample>(`/rubric-examples/${id}/restore`),

  // 관리자: 임베딩 색인, 꼬리질문 지표
  embeddingIndex: (signal?: AbortSignal) => api.get<EmbeddingIndexStatus>('/admin/embedding-index', signal),
  rebuildIndex: () => api.post<EmbeddingIndexStatus>('/admin/embedding-index/rebuild'),
  followUpMetrics: (days: number, signal?: AbortSignal) => api.get<FollowUpMetrics>(`/admin/follow-up-metrics?days=${days}`, signal),
}
