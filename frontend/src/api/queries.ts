/**
 * TanStack Query composables, one per endpoint. Each returns a `reactive()` result, so components read
 * `q.data` / `q.isPending` directly in script and template. Parameters may be refs or getters.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, toValue, type MaybeRefOrGetter } from 'vue'

import { endpoints } from './endpoints'
import type {
  ApplyModelRequest,
  Competency,
  IntakeEventFilter,
  CreateQARequest,
  CreateSessionRequest,
  RevertModelRequest,
  ScheduleSuggestionRequest,
  ScreeningStatus,
  SessionStatus,
  SubmitInterviewerScoresRequest,
  UploadApplicationRequest,
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
  modelSettings: ['admin', 'models'] as const,
  modelCatalog: ['admin', 'models', 'catalog'] as const,
  modelHistory: ['admin', 'models', 'history'] as const,
  modelDownloads: ['admin', 'models', 'downloads'] as const,
  intakeSummary: ['admin', 'intake', 'summary'] as const,
  intakeEvents: (filter: IntakeEventFilter) => ['admin', 'intake', 'events', filter] as const,
}

// ----- queries -------------------------------------------------------------------------------------

export const useMe = () =>
  reactive(useQuery({ queryKey: qk.me, queryFn: ({ signal }) => endpoints.me(signal), staleTime: Infinity }))

export const useDashboard = () =>
  reactive(useQuery({ queryKey: qk.dashboard, queryFn: ({ signal }) => endpoints.dashboard(signal), refetchInterval: 15_000 }))

export const useActivity = (limit = 12) =>
  reactive(
    useQuery({ queryKey: qk.activity(limit), queryFn: ({ signal }) => endpoints.activity(limit, signal), refetchInterval: 15_000 }),
  )

export const usePostings = () => reactive(useQuery({ queryKey: qk.postings, queryFn: ({ signal }) => endpoints.postings(signal) }))

export const usePosting = (id: MaybeRefOrGetter<string>) =>
  reactive(
    useQuery(() => {
      const v = toValue(id)
      return { queryKey: qk.posting(v), queryFn: ({ signal }) => endpoints.posting(v, signal), enabled: Boolean(v) }
    }),
  )

export const useCompetencySets = (postingId: MaybeRefOrGetter<string>) =>
  reactive(
    useQuery(() => {
      const v = toValue(postingId)
      return { queryKey: qk.competencySets(v), queryFn: ({ signal }) => endpoints.competencySets(v, signal), enabled: Boolean(v) }
    }),
  )

export const useApplications = (postingId: MaybeRefOrGetter<string | undefined>) =>
  reactive(
    useQuery(() => {
      const v = toValue(postingId) ?? ''
      return { queryKey: qk.applications(v), queryFn: ({ signal }) => endpoints.applications(v, signal), enabled: Boolean(v) }
    }),
  )

export const useApplication = (id: MaybeRefOrGetter<string | null>) =>
  reactive(
    useQuery(() => {
      const v = toValue(id) ?? ''
      return { queryKey: qk.application(v), queryFn: ({ signal }) => endpoints.application(v, signal), enabled: Boolean(v) }
    }),
  )

export const useSchedulable = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.schedulable,
      queryFn: ({ signal }) => endpoints.schedulableApplications(signal),
      enabled: toValue(enabled),
    })),
  )

export const useCandidateIndex = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.candidates,
      queryFn: ({ signal }) => endpoints.candidates(signal),
      enabled: toValue(enabled),
      staleTime: 60_000,
    })),
  )

export const useSessions = (status?: SessionStatus) =>
  reactive(useQuery({ queryKey: qk.sessions(status), queryFn: ({ signal }) => endpoints.sessions(status, signal) }))

export const useSession = (id: MaybeRefOrGetter<string>) =>
  reactive(
    useQuery(() => {
      const v = toValue(id)
      return { queryKey: qk.session(v), queryFn: ({ signal }) => endpoints.session(v, signal), enabled: Boolean(v) }
    }),
  )

export const useEvaluation = (id: MaybeRefOrGetter<string>) =>
  reactive(
    useQuery(() => {
      const v = toValue(id)
      return {
        queryKey: qk.evaluation(v),
        queryFn: ({ signal }) => endpoints.evaluation(v, signal),
        enabled: Boolean(v),
        // Poll while AI scoring runs (FR-07: 면접 종료 후 10분 이내).
        refetchInterval: (q) => (q.state.data?.ai.status === 'running' ? 2000 : false),
      }
    }),
  )

export const useInterviewers = () =>
  reactive(useQuery({ queryKey: qk.interviewers, queryFn: ({ signal }) => endpoints.interviewers(signal), staleTime: 5 * 60_000 }))

export const useAvailabilities = (from: MaybeRefOrGetter<string>, to: MaybeRefOrGetter<string>) =>
  reactive(
    useQuery(() => {
      const f = toValue(from)
      const t = toValue(to)
      return { queryKey: qk.availabilities(f, t), queryFn: ({ signal }) => endpoints.availabilities(f, t, signal) }
    }),
  )

export const useScheduleSuggestions = (body: MaybeRefOrGetter<ScheduleSuggestionRequest>) =>
  reactive(
    useQuery(() => {
      const b = toValue(body)
      return {
        queryKey: ['schedule-suggestions', b] as const,
        queryFn: () => endpoints.scheduleSuggestions(b),
        enabled: b.interviewer_ids.length > 0,
        placeholderData: keepPreviousData,
      }
    }),
  )

// ----- mutations -----------------------------------------------------------------------------------

export function useUpdateScreening(postingId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return reactive(
    useMutation({
      mutationFn: ({ screeningId, status }: { screeningId: string; status: ScreeningStatus }) =>
        endpoints.updateScreening(screeningId, status),
      onSuccess: () => {
        void qc.invalidateQueries({ queryKey: qk.applications(toValue(postingId)) })
        void qc.invalidateQueries({ queryKey: ['applications'] })
        void qc.invalidateQueries({ queryKey: qk.postings })
        void qc.invalidateQueries({ queryKey: qk.candidates })
        void qc.invalidateQueries({ queryKey: qk.dashboard })
        void qc.invalidateQueries({ queryKey: ['activity'] })
      },
    }),
  )
}

export function useUploadApplication(postingId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return reactive(
    useMutation({
      mutationFn: (body: UploadApplicationRequest) => endpoints.uploadApplication(toValue(postingId), body),
      onSuccess: () => {
        void qc.invalidateQueries({ queryKey: qk.applications(toValue(postingId)) })
        void qc.invalidateQueries({ queryKey: qk.postings })
        void qc.invalidateQueries({ queryKey: qk.candidates })
        void qc.invalidateQueries({ queryKey: qk.dashboard })
        void qc.invalidateQueries({ queryKey: ['activity'] })
      },
    }),
  )
}

function useInvalidateCompetency(postingId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: qk.competencySets(toValue(postingId)) })
    void qc.invalidateQueries({ queryKey: qk.postings })
    void qc.invalidateQueries({ queryKey: ['activity'] })
  }
}

export function useCreateCompetencySet(postingId: MaybeRefOrGetter<string>) {
  const invalidate = useInvalidateCompetency(postingId)
  return reactive(
    useMutation({ mutationFn: (c: Competency[]) => endpoints.createCompetencySet(toValue(postingId), c), onSuccess: invalidate }),
  )
}

export function useGenerateCompetencySet(postingId: MaybeRefOrGetter<string>) {
  const invalidate = useInvalidateCompetency(postingId)
  return reactive(useMutation({ mutationFn: () => endpoints.generateCompetencySet(toValue(postingId)), onSuccess: invalidate }))
}

export function useUpdateCompetencySet(postingId: MaybeRefOrGetter<string>) {
  const invalidate = useInvalidateCompetency(postingId)
  return reactive(
    useMutation({
      mutationFn: ({ id, competencies }: { id: string; competencies: Competency[] }) => endpoints.updateCompetencySet(id, competencies),
      onSuccess: invalidate,
    }),
  )
}

export function useApproveCompetencySet(postingId: MaybeRefOrGetter<string>) {
  const invalidate = useInvalidateCompetency(postingId)
  return reactive(useMutation({ mutationFn: (id: string) => endpoints.approveCompetencySet(id), onSuccess: invalidate }))
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
    consent: reactive(useMutation({ mutationFn: (consent: boolean) => endpoints.recordConsent(sessionId, consent), onSuccess: setDetail })),
    start: reactive(useMutation({ mutationFn: () => endpoints.startSession(sessionId), onSuccess: setDetail })),
    end: reactive(
      useMutation({
        mutationFn: () => endpoints.endSession(sessionId),
        onSuccess: (d) => {
          setDetail(d)
          void qc.invalidateQueries({ queryKey: qk.evaluation(sessionId) })
          void qc.invalidateQueries({ queryKey: ['postings'] })
        },
      }),
    ),
  }
}

export function useCreateQA(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return reactive(useMutation({ mutationFn: (body: CreateQARequest) => endpoints.createQA(sessionId, body), onSuccess: invalidate }))
}

export function useAnswerQA(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return reactive(
    useMutation({
      mutationFn: ({ qaId, answer }: { qaId: string; answer: string }) => endpoints.answerQA(qaId, answer),
      onSuccess: invalidate,
    }),
  )
}

export function useCreateNote(sessionId: string) {
  const invalidate = useInvalidateSession(sessionId)
  return reactive(useMutation({ mutationFn: (content: string) => endpoints.createNote(sessionId, content), onSuccess: invalidate }))
}

export function useSubmitScores(sessionId: string) {
  const qc = useQueryClient()
  return reactive(
    useMutation({
      mutationFn: ({ interviewerId, body }: { interviewerId: string; body: SubmitInterviewerScoresRequest }) =>
        endpoints.submitScores(sessionId, interviewerId, body),
      onSuccess: (ev) => {
        qc.setQueryData(qk.evaluation(sessionId), ev)
        void qc.invalidateQueries({ queryKey: ['sessions', 'list'] })
        void qc.invalidateQueries({ queryKey: qk.dashboard })
        void qc.invalidateQueries({ queryKey: ['postings'] })
        void qc.invalidateQueries({ queryKey: ['activity'] })
      },
    }),
  )
}

export function useCreateSession() {
  const qc = useQueryClient()
  return reactive(
    useMutation({
      mutationFn: (body: CreateSessionRequest) => endpoints.createSession(body),
      onSuccess: () => {
        // The server leaves booked interviews out of the slot suggestions.
        void qc.invalidateQueries({ queryKey: ['schedule-suggestions'] })
        void qc.invalidateQueries({ queryKey: ['sessions'] })
        void qc.invalidateQueries({ queryKey: ['applications'] })
        void qc.invalidateQueries({ queryKey: ['postings'] })
        void qc.invalidateQueries({ queryKey: qk.dashboard })
        void qc.invalidateQueries({ queryKey: ['activity'] })
      },
    }),
  )
}

export function useAvailabilityMutations() {
  const qc = useQueryClient()
  const invalidate = () => void qc.invalidateQueries({ queryKey: ['availabilities'] })
  return {
    create: reactive(useMutation({ mutationFn: endpoints.createAvailability, onSuccess: invalidate })),
    remove: reactive(useMutation({ mutationFn: endpoints.deleteAvailability, onSuccess: invalidate })),
  }
}

// ----- 관리자 > 모델 설정 ----------------------------------------------------------------------------

export const useModelSettings = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.modelSettings,
      queryFn: ({ signal }) => endpoints.modelSettings(signal),
      enabled: toValue(enabled),
      staleTime: 0,
    })),
  )

export const useModelCatalog = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.modelCatalog,
      queryFn: ({ signal }) => endpoints.modelCatalog(signal),
      enabled: toValue(enabled),
      staleTime: 0,
    })),
  )

export const useModelHistory = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.modelHistory,
      queryFn: ({ signal }) => endpoints.modelHistory(signal),
      enabled: toValue(enabled),
      staleTime: 0,
    })),
  )

/** Polls every second while a download runs; the catalog's "downloaded" flags refresh when one ends. */
export function useModelDownloads(enabled: MaybeRefOrGetter<boolean> = true) {
  const qc = useQueryClient()
  let running = false
  return reactive(
    useQuery(() => ({
      queryKey: qk.modelDownloads,
      queryFn: async ({ signal }) => {
        const list = await endpoints.modelDownloads(signal)
        const now = list.some((d) => d.status === 'downloading')
        if (running && !now) void qc.invalidateQueries({ queryKey: qk.modelCatalog })
        running = now
        return list
      },
      enabled: toValue(enabled),
      staleTime: 0,
      refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'downloading') ? 1000 : false),
    })),
  )
}

function useInvalidateModels() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['admin', 'models'] })
  }
}

export function useApplyModel() {
  const invalidate = useInvalidateModels()
  return reactive(
    useMutation({
      mutationFn: ({ role, body }: { role: string; body: ApplyModelRequest }) => endpoints.applyModel(role, body),
      onSuccess: invalidate,
    }),
  )
}

export function useRevertModel() {
  const invalidate = useInvalidateModels()
  return reactive(
    useMutation({
      mutationFn: ({ changeId, body }: { changeId: string; body: RevertModelRequest }) => endpoints.revertModel(changeId, body),
      onSuccess: invalidate,
    }),
  )
}

// ----- 관리자 > 연동 현황 ----------------------------------------------------------------------------

/** Polls every 2 s while events wait or are being applied, every 15 s otherwise. */
export const useIntakeSummary = (enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => ({
      queryKey: qk.intakeSummary,
      queryFn: ({ signal }) => endpoints.intakeSummary(signal),
      enabled: toValue(enabled),
      staleTime: 0,
      refetchInterval: (q) => (q.state.data && q.state.data.totals.queued + q.state.data.totals.processing > 0 ? 2000 : 15_000),
    })),
  )

export const useIntakeEvents = (filter: MaybeRefOrGetter<IntakeEventFilter>, enabled: MaybeRefOrGetter<boolean> = true) =>
  reactive(
    useQuery(() => {
      const f = toValue(filter)
      return {
        queryKey: qk.intakeEvents(f),
        queryFn: ({ signal }) => endpoints.intakeEvents(f, signal),
        enabled: toValue(enabled),
        staleTime: 0,
        placeholderData: keepPreviousData,
        refetchInterval: (q) => (q.state.data?.some((e) => e.status === 'queued' || e.status === 'processing') ? 2000 : 15_000),
      }
    }),
  )

export function useIntakeRetry() {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['admin', 'intake'] })
    void qc.invalidateQueries({ queryKey: ['postings'] })
  }
  return {
    one: reactive(useMutation({ mutationFn: (id: string) => endpoints.retryIntakeEvent(id), onSuccess: refresh })),
    all: reactive(
      useMutation({ mutationFn: (body: { failure_code?: string; posting_no?: string }) => endpoints.retryIntake(body), onSuccess: refresh }),
    ),
  }
}

export function useUpdatePosting(postingId: MaybeRefOrGetter<string>) {
  const qc = useQueryClient()
  return reactive(
    useMutation({
      mutationFn: (siteNo: string | null) => endpoints.updatePosting(toValue(postingId), { site_posting_no: siteNo }),
      onSuccess: (d) => {
        qc.setQueryData(qk.posting(d.id), d)
        void qc.invalidateQueries({ queryKey: qk.postings })
        void qc.invalidateQueries({ queryKey: ['admin', 'intake'] })
      },
    }),
  )
}

export function useModelDownloadMutations() {
  const qc = useQueryClient()
  const refresh = () => void qc.invalidateQueries({ queryKey: qk.modelDownloads })
  return {
    start: reactive(useMutation({ mutationFn: (m: { impl: string; model: string }) => endpoints.startDownload(m.impl, m.model), onSuccess: refresh })),
    cancel: reactive(useMutation({ mutationFn: (m: { impl: string; model: string }) => endpoints.cancelDownload(m.impl, m.model), onSuccess: refresh })),
  }
}
