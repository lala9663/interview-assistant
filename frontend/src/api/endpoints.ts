/** One function per REST endpoint (docs/api-contract.md). */
import { api } from './client'
import type {
  ActivityItem,
  ApplicationDetail,
  ApplicationRow,
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
  PostingDetail,
  PostingSummary,
  QAItem,
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
} from './types'

export const endpoints = {
  me: (signal?: AbortSignal) => api.get<Me>('/me', signal),
  dashboard: (signal?: AbortSignal) => api.get<DashboardSummary>('/dashboard', signal),
  activity: (limit: number, signal?: AbortSignal) => api.get<ActivityItem[]>(`/activity?limit=${limit}`, signal),

  postings: (signal?: AbortSignal) => api.get<PostingSummary[]>('/postings', signal),
  posting: (id: string, signal?: AbortSignal) => api.get<PostingDetail>(`/postings/${id}`, signal),
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
}
