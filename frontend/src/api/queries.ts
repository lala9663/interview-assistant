import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { endpoints } from './endpoints'
import type {
  Competency,
  CreateQARequest,
  CreateSessionRequest,
  ScheduleSuggestionRequest,
  ScreeningStatus,
  SessionStatus,
  SubmitInterviewerScoresRequest,
} from './types'

export const qk = {
  me: ['me'] as const,
  dashboard: ['dashboard'] as const,
  activity: (limit: number) => ['activity', limit] as const,
  postings: ['postings'] as const,
  posting: (id: string) => ['postings', id] as const,
  competencySets: (postingId: string) => ['postings', postingId, 'competency-sets'] as const,
  applications: (postingId: string) => ['postings', postingId, 'applications'] as const,
  application: (id: string) => ['applications', id] as const,
  schedulable: ['applications', 'schedulable'] as const,
  candidates: ['candidates'] as const,
  sessions: (status?: SessionStatus) => ['sessions', 'list', status ?? 'all'] as const,
  session: (id: string) => ['sessions', id] as const,
  transcript: (id: string) => ['sessions', id, 'transcript'] as const,
  evaluation: (id: string) => ['sessions', id, 'evaluation'] as const,
  interviewers: ['interviewers'] as const,
  availabilities: (from: string, to: string) => ['availabilities', from, to] as const,
}

// ----- queries -------------------------------------------------------------------------------------

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: ({ signal }) => endpoints.me(signal), staleTime: Infinity })

export const useDashboard = () =>
  useQuery({ queryKey: qk.dashboard, queryFn: ({ signal }) => endpoints.dashboard(signal), refetchInterval: 15_000 })

export const useActivity = (limit = 12) =>
  useQuery({ queryKey: qk.activity(limit), queryFn: ({ signal }) => endpoints.activity(limit, signal), refetchInterval: 15_000 })

export const usePostings = () => useQuery({ queryKey: qk.postings, queryFn: ({ signal }) => endpoints.postings(signal) })

export const usePosting = (id: string) =>
  useQuery({ queryKey: qk.posting(id), queryFn: ({ signal }) => endpoints.posting(id, signal), enabled: Boolean(id) })

export const useCompetencySets = (postingId: string) =>
  useQuery({
    queryKey: qk.competencySets(postingId),
    queryFn: ({ signal }) => endpoints.competencySets(postingId, signal),
    enabled: Boolean(postingId),
  })

export const useApplications = (postingId: string | undefined) =>
  useQuery({
    queryKey: qk.applications(postingId ?? ''),
    queryFn: ({ signal }) => endpoints.applications(postingId!, signal),
    enabled: Boolean(postingId),
  })

export const useApplication = (id: string | null) =>
  useQuery({ queryKey: qk.application(id ?? ''), queryFn: ({ signal }) => endpoints.application(id!, signal), enabled: Boolean(id) })

export const useSchedulable = (enabled = true) =>
  useQuery({ queryKey: qk.schedulable, queryFn: ({ signal }) => endpoints.schedulableApplications(signal), enabled })

export const useCandidateIndex = (enabled = true) =>
  useQuery({ queryKey: qk.candidates, queryFn: ({ signal }) => endpoints.candidates(signal), enabled, staleTime: 60_000 })

export const useSessions = (status?: SessionStatus) =>
  useQuery({ queryKey: qk.sessions(status), queryFn: ({ signal }) => endpoints.sessions(status, signal) })

export const useSession = (id: string) =>
  useQuery({ queryKey: qk.session(id), queryFn: ({ signal }) => endpoints.session(id, signal), enabled: Boolean(id) })

export const useEvaluation = (id: string) =>
  useQuery({
    queryKey: qk.evaluation(id),
    queryFn: ({ signal }) => endpoints.evaluation(id, signal),
    enabled: Boolean(id),
    // Poll while AI scoring runs (FR-07: 면접 종료 후 10분 이내).
    refetchInterval: (q) => (q.state.data?.ai.status === 'running' ? 2000 : false),
  })

export const useInterviewers = () =>
  useQuery({ queryKey: qk.interviewers, queryFn: ({ signal }) => endpoints.interviewers(signal), staleTime: 5 * 60_000 })

export const useAvailabilities = (from: string, to: string) =>
  useQuery({ queryKey: qk.availabilities(from, to), queryFn: ({ signal }) => endpoints.availabilities(from, to, signal) })

// ----- mutations -----------------------------------------------------------------------------------

export function useUpdateScreening(postingId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ screeningId, status }: { screeningId: string; status: ScreeningStatus }) =>
      endpoints.updateScreening(screeningId, status),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.applications(postingId) })
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: qk.postings })
      void qc.invalidateQueries({ queryKey: qk.candidates })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

function useInvalidateCompetency(postingId: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: qk.competencySets(postingId) })
    void qc.invalidateQueries({ queryKey: qk.postings })
    void qc.invalidateQueries({ queryKey: ['activity'] })
  }
}

export function useCreateCompetencySet(postingId: string) {
  const invalidate = useInvalidateCompetency(postingId)
  return useMutation({ mutationFn: (c: Competency[]) => endpoints.createCompetencySet(postingId, c), onSuccess: invalidate })
}

export function useGenerateCompetencySet(postingId: string) {
  const invalidate = useInvalidateCompetency(postingId)
  return useMutation({ mutationFn: () => endpoints.generateCompetencySet(postingId), onSuccess: invalidate })
}

export function useUpdateCompetencySet(postingId: string) {
  const invalidate = useInvalidateCompetency(postingId)
  return useMutation({
    mutationFn: ({ id, competencies }: { id: string; competencies: Competency[] }) => endpoints.updateCompetencySet(id, competencies),
    onSuccess: invalidate,
  })
}

export function useApproveCompetencySet(postingId: string) {
  const invalidate = useInvalidateCompetency(postingId)
  return useMutation({ mutationFn: (id: string) => endpoints.approveCompetencySet(id), onSuccess: invalidate })
}

function useInvalidateSession(sessionId: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: qk.session(sessionId) })
    void qc.invalidateQueries({ queryKey: ['sessions', 'list'] })
    void qc.invalidateQueries({ queryKey: qk.dashboard })
    void qc.invalidateQueries({ queryKey: ['activity'] })
  }
}

export function useSessionLifecycle(sessionId: string) {
  const qc = useQueryClient()
  const invalidate = useInvalidateSession(sessionId)
  const setDetail = (d: Awaited<ReturnType<typeof endpoints.session>>) => {
    qc.setQueryData(qk.session(sessionId), d)
    invalidate()
  }
  return {
    consent: useMutation({ mutationFn: (consent: boolean) => endpoints.recordConsent(sessionId, consent), onSuccess: setDetail }),
    start: useMutation({ mutationFn: () => endpoints.startSession(sessionId), onSuccess: setDetail }),
    end: useMutation({
      mutationFn: () => endpoints.endSession(sessionId),
      onSuccess: (d) => {
        setDetail(d)
        void qc.invalidateQueries({ queryKey: qk.evaluation(sessionId) })
        void qc.invalidateQueries({ queryKey: ['postings'] })
      },
    }),
  }
}

export function useCreateQA(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return useMutation({ mutationFn: (body: CreateQARequest) => endpoints.createQA(sessionId, body), onSuccess: invalidate })
}

export function useAnswerQA(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return useMutation({
    mutationFn: ({ qaId, answer }: { qaId: string; answer: string }) => endpoints.answerQA(qaId, answer),
    onSuccess: invalidate,
  })
}

export function useCreateNote(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return useMutation({ mutationFn: (content: string) => endpoints.createNote(sessionId, content), onSuccess: invalidate })
}

export function useSubmitScores(sessionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ interviewerId, body }: { interviewerId: string; body: SubmitInterviewerScoresRequest }) =>
      endpoints.submitScores(sessionId, interviewerId, body),
    onSuccess: (ev) => {
      qc.setQueryData(qk.evaluation(sessionId), ev)
      void qc.invalidateQueries({ queryKey: ['sessions', 'list'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: ['postings'] })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSessionRequest) => endpoints.createSession(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['sessions'] })
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: ['postings'] })
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      void qc.invalidateQueries({ queryKey: ['activity'] })
    },
  })
}

export function useAvailabilityMutations() {
  const qc = useQueryClient()
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['availabilities'] })
  return {
    create: useMutation({ mutationFn: endpoints.createAvailability, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: endpoints.deleteAvailability, onSuccess: invalidate }),
  }
}

export function useScheduleSuggestions(body: ScheduleSuggestionRequest) {
  return useQuery({
    queryKey: ['schedule-suggestions', body],
    queryFn: () => endpoints.scheduleSuggestions(body),
    enabled: body.interviewer_ids.length > 0,
    placeholderData: (prev) => prev,
  })
}
