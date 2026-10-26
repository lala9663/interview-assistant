/** One function per REST endpoint (docs/api-contract.md). */
import { api } from './client'
import type {
  ActivityItem,
  ApplicationDetail,
  ApplyModelRequest,
  ApplicationRow,
  IntakeEvent,
  IntakeEventFilter,
  IntakeSummary,
  Availability,
  CandidateIndexItem,
  CandidateNote,
  Competency,
  CompetencySet,
  CreateAvailabilityRequest,
  CreateQARequest,
  CreateSessionRequest,
  DashboardSummary,
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
  QAItem,
  RevertModelRequest,
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
  createCompetencySet: (postingId: string, competencies: Competency[]) =>
    api.post<CompetencySet>(`/postings/${postingId}/competency-sets`, { competencies }),
  generateCompetencySet: (postingId: string) => api.post<CompetencySet>(`/postings/${postingId}/competency-sets/generate`),
  updateCompetencySet: (id: string, competencies: Competency[]) =>
    api.put<CompetencySet>(`/competency-sets/${id}`, { competencies }),
  approveCompetencySet: (id: string) => api.post<CompetencySet>(`/competency-sets/${id}/approve`),

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

  evaluation: (sessionId: string, signal?: AbortSignal) => api.get<Evaluation>(`/sessions/${sessionId}/evaluation`, signal),
  submitScores: (sessionId: string, interviewerId: string, body: SubmitInterviewerScoresRequest) =>
    api.put<Evaluation>(`/sessions/${sessionId}/scores/${interviewerId}`, body),

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
  /** STT and diarization take `audio` (a recording or file); without it the server's Korean sample. */
  testModel: (role: string, spec: ModelSpec, opts: { confirmExternal?: boolean; audio?: Blob | null } = {}) => {
    const form = new FormData()
    form.append('spec', JSON.stringify(spec))
    form.append('confirm_external', String(Boolean(opts.confirmExternal)))
    if (opts.audio) form.append('audio', opts.audio, opts.audio instanceof File ? opts.audio.name : 'recording.webm')
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
}
