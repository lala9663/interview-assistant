/**
 * In-memory mock database for MSW. Seeded relative to "now" so the dashboard always has a
 * live interview, today's schedule and recent results. All people are fictional.
 *
 * Interview rounds (전형 차수) follow the backend's `interviews.py`: 서류 → each round → 최종.
 * Round 1 takes applications that passed screening, round N+1 those a person passed in round N.
 * The seed lays out the same sessions, decisions and points to check as `demo/seed.py`.
 */
import type {
  ActivityItem,
  AiScoringStatus,
  Application,
  ApplicationChannel,
  ApplicationDetail,
  ApplicationRow,
  AuditLog,
  Availability,
  Candidate,
  CandidateIndexItem,
  CandidateNote,
  CheckPoint,
  CompetencySet,
  DecisionPanel,
  DecisionStatus,
  Evaluation,
  InterviewRound,
  InterviewSession,
  Interviewer,
  InterviewerRole,
  JobPosting,
  PendingDecision,
  PostingCounts,
  PostingSummary,
  PresetQuestion,
  PreviousRound,
  ProgressStep,
  QAItem,
  QuestionSource,
  RoundDecision,
  RoundRef,
  RoundSummary,
  RoundView,
  SchedulableApplication,
  Score,
  Screening,
  SessionBrief,
  SessionDetail,
  SessionInterviewer,
  SessionMode,
  SessionStatus,
  SessionSummary,
  StepStatus,
  TranscriptSegment,
  UploadResult,
} from '@/api/types'
import { STEP_STATUSES } from '@/api/types'
import { summarizeAiScores } from '@/lib/scoring'
import { addDays, addMinutes, kstDate, kstParts, MINUTE, startOfKstDay, startOfKstWeek } from '@/lib/time'

import { ANSWER_BANK, GENERIC_BANK, type SuggestionSeed } from './data/banks'
import { CANDIDATES, INTERVIEWERS, ME_KEY, pseudonymOf } from './data/people'
import { P1, P2, POSTING_SEEDS, type PresetSeed } from './data/postings'
import { createIntakeState, type IntakeState } from './intake-state'
import { createModelState, type ModelState } from './models'

export const AI_MODEL = 'claude-opus-5-5'
export const SCORING_PROMPT = 'score-v0.3'
export const FOLLOWUP_PROMPT = 'followup-v0.3'
export const CHECKPOINT_PROMPT = 'checkpoint-v0.1'
export const SCREENING_MODEL = 'claude-haiku-5-5'
export const SCORING_SAMPLES = 3
/** How long mock AI scoring "runs" after a session ends. */
export const AI_SCORING_MS = 7000

let idCounter = 0
export function newId(): string {
  idCounter += 1
  const rand = () => Math.floor(Math.random() * 0x10000).toString(16).padStart(4, '0')
  return `${rand()}${rand()}-${rand()}-4${rand().slice(1)}-a${rand().slice(1)}-${String(idCounter).padStart(4, '0')}${rand()}${rand()}`
}

const iso = (d: Date) => d.toISOString()
const byTime = (a: string | null, b: string | null) => (a ?? '').localeCompare(b ?? '')

/** Deterministic 0..1 from a string (for stable mock scores). */
function hash01(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 10000) / 10000
}

export function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.?!])\s+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

const SIGNALS = ['검증', '확인', '비교', '데이터', '원인', '합의', '개선']
/** Rough evidence weight of a text (numbers and signal words): the thinnest answers come first. */
export function weight(text: string): number {
  return (text.match(/\d/g)?.length ?? 0) + SIGNALS.filter((w) => text.includes(w)).length
}
const thinnest = (sentences: string[]) => sentences.reduce((best, s) => (weight(s) < weight(best) ? s : best), sentences[0] ?? '')
const round1 = (v: number) => Math.floor(v * 10 + 0.5) / 10
const mean = (values: number[]) => (values.length ? round1(values.reduce((a, b) => a + b, 0) / values.length) : null)

/** Extra mock-only info kept next to a QA item. */
export interface QAMeta {
  postingKey: 'P1' | 'P2'
  presetId: string | null
  competency: string | null
  answer: string
  suggestions: SuggestionSeed[] | null
}

export interface RegisteredSuggestion extends SuggestionSeed {
  batch_id: string
  suggestion_id: string
  qa_item_id: string
}

export class MockDb {
  readonly now: Date
  postings: JobPosting[] = []
  rounds: InterviewRound[] = []
  competencySets: CompetencySet[] = []
  /** round preset questions per competency set id */
  presets = new Map<string, PresetQuestion[]>()
  /** 이어 질문 per session id */
  carryover = new Map<string, PresetQuestion[]>()
  /** session id -> competency set id pinned when it started */
  pinned = new Map<string, string>()
  candidates: Candidate[] = []
  applications: Application[] = []
  screenings: Screening[] = []
  interviewers: Interviewer[] = []
  sessions: InterviewSession[] = []
  sessionInterviewers: SessionInterviewer[] = []
  qaItems: QAItem[] = []
  qaMeta = new Map<string, QAMeta>()
  scores: Score[] = []
  notes: CandidateNote[] = []
  decisions: RoundDecision[] = []
  checkPoints: CheckPoint[] = []
  availabilities: Availability[] = []
  audit: AuditLog[] = []
  aiScoring = new Map<string, { status: AiScoringStatus; startedAt: number }>()
  submittedAt = new Map<string, string>()
  /** interviewer scores are per session (qa_item_id null): score id -> session id */
  scoreSession = new Map<string, string>()
  documents = new Map<string, UploadResult['document']>()
  transcripts = new Map<string, TranscriptSegment[]>()
  suggestions = new Map<string, RegisteredSuggestion>()
  genericCursor = new Map<string, number>()
  /** 관리자 > 모델 설정 (mocks/models.ts) */
  models: ModelState
  /** 관리자 > 연동 현황 (mocks/intake-state.ts) */
  intake: IntakeState

  constructor(now = new Date()) {
    this.now = now
    seed(this)
    this.models = createModelState(now, newId)
    this.intake = createIntakeState(this, newId)
  }

  // ----- lookups ---------------------------------------------------------------------------------

  get me(): Interviewer {
    return this.interviewers.find((i) => i.id === interviewerId(ME_KEY))!
  }
  posting(id: string) {
    return this.postings.find((p) => p.id === id)
  }
  postingKey(postingId: string): 'P1' | 'P2' {
    return postingId === P2.id ? 'P2' : 'P1'
  }
  application(id: string) {
    return this.applications.find((a) => a.id === id)
  }
  candidate(id: string) {
    return this.candidates.find((c) => c.id === id)
  }
  screeningOf(applicationId: string) {
    return this.screenings.find((s) => s.application_id === applicationId) ?? null
  }
  session(id: string) {
    return this.sessions.find((s) => s.id === id)
  }
  interviewer(id: string) {
    return this.interviewers.find((i) => i.id === id)
  }
  sessionsOf(applicationId: string) {
    return this.sessions.filter((s) => s.application_id === applicationId)
  }
  qaOf(sessionId: string) {
    return this.qaItems.filter((q) => q.session_id === sessionId).sort((a, b) => a.seq - b.seq)
  }
  panelOf(sessionId: string) {
    return this.sessionInterviewers
      .filter((si) => si.session_id === sessionId)
      .sort((a, b) => (a.role === b.role ? 0 : a.role === 'lead' ? -1 : 1))
  }

  // ----- rounds and competency sets ---------------------------------------------------------------

  roundsOf(postingId: string): InterviewRound[] {
    return this.rounds.filter((r) => r.posting_id === postingId).sort((a, b) => a.position - b.position)
  }
  round(id: string) {
    return this.rounds.find((r) => r.id === id)
  }
  roundAt(postingId: string, position: number) {
    return this.roundsOf(postingId).find((r) => r.position === position)
  }
  isLast(r: InterviewRound) {
    return r.position === Math.max(...this.roundsOf(r.posting_id).map((x) => x.position))
  }
  roundRef(r: InterviewRound): RoundRef {
    return { id: r.id, position: r.position, label: r.label, name: r.name, is_last: this.isLast(r) }
  }
  roundView(r: InterviewRound): RoundView {
    return { ...this.roundRef(r), rounds: this.roundsOf(r.posting_id).length, show_previous_scores: r.show_previous_scores }
  }
  /** Positions changed: labels follow ("1차", "2차" ...). */
  relabel(postingId: string) {
    for (const r of this.roundsOf(postingId)) r.label = `${r.position}차`
  }
  setsOf(roundId: string): CompetencySet[] {
    return this.competencySets.filter((c) => c.round_id === roundId).sort((a, b) => a.version - b.version)
  }
  approvedSet(roundId: string): CompetencySet | null {
    return [...this.setsOf(roundId)].reverse().find((c) => c.approved_at) ?? null
  }
  latestSet(roundId: string): CompetencySet | null {
    return this.setsOf(roundId).at(-1) ?? null
  }
  /** Screening judges against round 1's approved dictionary; the posting list shows round 1's. */
  firstRound(postingId: string) {
    return this.roundsOf(postingId)[0]
  }
  setOfSession(sessionId: string): CompetencySet | null {
    const s = this.session(sessionId)!
    const pinned = this.pinned.get(sessionId)
    return (pinned && this.competencySets.find((c) => c.id === pinned)) || this.approvedSet(s.round_id)
  }
  presetsOf(setId: string) {
    return this.presets.get(setId) ?? []
  }
  presetById(id: string): PresetQuestion | undefined {
    for (const list of [...this.presets.values(), ...this.carryover.values()]) {
      const found = list.find((q) => q.id === id)
      if (found) return found
    }
    return undefined
  }

  roundSummary(r: InterviewRound): RoundSummary {
    const approved = this.approvedSet(r.id)
    const brief = (c: CompetencySet | null) => (c ? { id: c.id, version: c.version, approved_at: c.approved_at } : null)
    const held = this.sessions.filter((s) => s.round_id === r.id && s.status !== 'cancelled').length
    return {
      ...r,
      is_last: this.isLast(r),
      latest_competency_set: brief(this.latestSet(r.id)),
      approved_competency_set: brief(approved),
      preset_count: approved ? this.presetsOf(approved.id).length : 0,
      sessions: held,
      locked: held > 0 || this.decisions.some((d) => d.round_id === r.id),
    }
  }

  // ----- sessions, decisions, progress ------------------------------------------------------------

  aiStatus(sessionId: string): AiScoringStatus {
    const st = this.aiScoring.get(sessionId)
    if (!st) return 'not_started'
    if (st.status === 'running' && Date.now() - st.startedAt >= AI_SCORING_MS) {
      generateAiScores(this, sessionId)
      generateAiCheckPoints(this, sessionId)
      st.status = 'completed'
      const s = this.session(sessionId)
      this.log({ actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sessionId, model: AI_MODEL, prompt_version: SCORING_PROMPT, details: { application_id: s?.application_id } })
    }
    return st.status
  }
  submitted(sessionId: string): boolean {
    const panel = this.panelOf(sessionId)
    return panel.length > 0 && panel.every((p) => this.submittedAt.has(`${sessionId}:${p.interviewer_id}`))
  }
  isEvaluated(sessionId: string): boolean {
    if (this.aiStatus(sessionId) !== 'completed') return false
    return this.panelOf(sessionId).every((p) => this.submittedAt.has(`${sessionId}:${p.interviewer_id}`))
  }
  /** The application's newest session of the round that was not cancelled. */
  roundSession(applicationId: string, roundId: string): InterviewSession | null {
    const list = this.sessionsOf(applicationId).filter((s) => s.round_id === roundId && s.status !== 'cancelled')
    return list.sort((a, b) => byTime(a.created_at, b.created_at)).at(-1) ?? null
  }
  currentDecision(applicationId: string, roundId: string): RoundDecision | null {
    return this.decisionHistory(applicationId, roundId)[0] ?? null
  }
  decisionHistory(applicationId: string, roundId: string): RoundDecision[] {
    return this.decisions.filter((d) => d.application_id === applicationId && d.round_id === roundId).sort((a, b) => b.revision - a.revision)
  }

  private roundStatus(session: InterviewSession | null, decision: RoundDecision | null): [StepStatus, string | null] {
    if (decision) return [decision.decision, decision.created_at]
    if (!session) return ['waiting', null]
    if (session.status === 'scheduled') return ['scheduled', session.scheduled_at]
    if (session.status === 'in_progress') return ['in_progress', session.started_at]
    return [this.submitted(session.id) ? 'deciding' : 'evaluating', session.ended_at]
  }

  /** 서류 → each round → 최종 (interviews.progress). */
  progress(applicationId: string): ProgressStep[] {
    const a = this.application(applicationId)!
    const sc = this.screeningOf(applicationId)
    const steps: ProgressStep[] = [{ kind: 'screening', round: null, status: sc ? sc.status : 'waiting', at: sc?.created_at ?? null, session_id: null }]
    let reached = sc?.status === 'passed'
    for (const r of this.roundsOf(a.posting_id)) {
      const session = this.roundSession(a.id, r.id)
      const decision = this.currentDecision(a.id, r.id)
      let status: StepStatus | null = null
      let at: string | null = null
      if (reached || session || decision) [status, at] = this.roundStatus(session, decision)
      steps.push({ kind: 'round', round: this.roundRef(r), status, at, session_id: session?.id ?? null })
      reached = reached && status === 'passed'
    }
    steps.push({ kind: 'final', round: null, status: reached ? 'passed' : null, at: reached ? (steps.at(-1)?.at ?? null) : null, session_id: null })
    return steps
  }
  stage(applicationId: string): ProgressStep {
    const steps = this.progress(applicationId)
    return steps.find((s) => s.status !== 'passed') ?? steps.at(-1)!
  }
  nextRound(applicationId: string): InterviewRound | null {
    const now = this.stage(applicationId)
    return now.kind === 'round' && now.status === 'waiting' && now.round ? this.round(now.round.id)! : null
  }
  scheduleRefusal(applicationId: string, r: InterviewRound): string | null {
    const steps = this.progress(applicationId)
    const i = steps.findIndex((s) => s.round?.id === r.id)
    const session = this.roundSession(applicationId, r.id)
    if (session) return session.status === 'completed' ? `${r.label} 면접을 이미 마쳤습니다.` : `이미 예정된 ${r.label} 면접이 있습니다.`
    const before = steps[i - 1]!
    if (before.status !== 'passed') {
      return before.kind === 'screening' ? '서류 통과한 지원서만 1차 면접을 잡을 수 있습니다.' : `${before.round!.label} 합격자만 ${r.label} 면접을 잡을 수 있습니다.`
    }
    return null
  }
  roundStatusOf(s: InterviewSession): StepStatus {
    return this.progress(s.application_id).find((x) => x.round?.id === s.round_id)?.status ?? 'waiting'
  }

  decisionRefusal(sessionId: string): string | null {
    const s = this.session(sessionId)!
    const a = this.application(s.application_id)!
    const r = this.round(s.round_id)!
    if (a.withdrawn_at || a.deleted_at) return '지원자가 철회한 지원서라 결정할 수 없습니다.'
    if (s.status !== 'completed') return '면접이 끝난 뒤에 결정할 수 있습니다.'
    if (!this.submitted(s.id)) return '면접관 점수가 모두 제출된 뒤에 결정할 수 있습니다.'
    if (this.roundSession(a.id, r.id)?.id !== s.id) return '이 차수의 최근 면접에서 결정하세요.'
    const later = this.sessionsOf(a.id).find((x) => x.status !== 'cancelled' && this.round(x.round_id)!.position > r.position)
    if (later) return `${this.round(later.round_id)!.label} 면접이 이미 있어 ${r.label} 결정을 바꿀 수 없습니다.`
    return null
  }
  decisionPanel(sessionId: string): DecisionPanel {
    const s = this.session(sessionId)!
    const r = this.round(s.round_id)!
    const refusal = this.decisionRefusal(sessionId)
    const next = this.roundAt(r.posting_id, r.position + 1)
    return {
      current: this.currentDecision(s.application_id, r.id),
      history: this.decisionHistory(s.application_id, r.id),
      can_decide: refusal === null,
      blocked_reason: refusal,
      is_last_round: this.isLast(r),
      next_round: next ? this.roundRef(next) : null,
    }
  }
  pendingDecisions(): PendingDecision[] {
    const rows: PendingDecision[] = []
    for (const a of this.applications.filter((x) => !x.deleted_at && !x.withdrawn_at)) {
      for (const step of this.progress(a.id)) {
        if (step.kind !== 'round' || (step.status !== 'deciding' && step.status !== 'hold')) continue
        const decision = this.currentDecision(a.id, step.round!.id)
        const sessionId = step.session_id ?? decision?.session_id
        if (!sessionId) continue
        const c = this.candidate(a.candidate_id)!
        const p = this.posting(a.posting_id)!
        rows.push({ session_id: sessionId, application_id: a.id, candidate: { id: c.id, pseudonym: c.pseudonym }, posting: { id: p.id, title: p.title }, round: step.round!, status: step.status, since: step.at })
      }
    }
    return rows.sort((x, y) => byTime(x.since, y.since))
  }

  /** The application's completed sessions of earlier rounds, oldest round first. */
  earlierSessions(sessionId: string): InterviewSession[] {
    const s = this.session(sessionId)!
    const position = this.round(s.round_id)!.position
    return this.roundsOf(this.application(s.application_id)!.posting_id)
      .filter((r) => r.position < position)
      .map((r) => this.roundSession(s.application_id, r.id))
      .filter((x): x is InterviewSession => x?.status === 'completed')
  }
  previousRound(current: InterviewSession, earlier: InterviewSession): PreviousRound {
    const visible = this.round(current.round_id)!.show_previous_scores
    const decision = this.currentDecision(earlier.application_id, earlier.round_id)
    const qaIds = new Set(this.qaOf(earlier.id).map((q) => q.id))
    const all = this.scores.filter((x) => (x.qa_item_id ? qaIds.has(x.qa_item_id) : this.scoreSession.get(x.id) === earlier.id))
    const names = [...new Set(all.map((x) => x.competency))]
    return {
      round: this.roundRef(this.round(earlier.round_id)!),
      session: this.brief(earlier),
      decision: decision?.decision ?? null,
      qa_count: qaIds.size,
      check_points: this.checkPoints.filter((p) => p.session_id === earlier.id),
      notes: this.notes
        .filter((n) => n.session_id === earlier.id)
        .sort((x, y) => x.created_at.localeCompare(y.created_at))
        .map((n) => ({ id: n.id, content: n.content, author_name: this.interviewer(n.author_id)?.name ?? '', created_at: n.created_at })),
      scores_visible: visible,
      scores: visible
        ? names.map((name) => ({
            competency: name,
            interviewer_mean: mean(all.filter((x) => x.competency === name && x.evaluator_type === 'interviewer').map((x) => x.score)),
            ai_mean: mean(all.filter((x) => x.competency === name && x.evaluator_type === 'ai').map((x) => x.score)),
          }))
        : null,
      decision_reason: visible ? (decision?.reason ?? null) : null,
    }
  }

  // ----- writes ----------------------------------------------------------------------------------

  log(entry: Omit<AuditLog, 'id' | 'occurred_at' | 'actor_id' | 'model' | 'prompt_version' | 'details'> & Partial<AuditLog>) {
    this.audit.unshift({
      id: newId(),
      occurred_at: entry.occurred_at ?? iso(new Date()),
      actor_type: entry.actor_type,
      actor_id: entry.actor_id ?? (entry.actor_type === 'user' ? this.me.id : null),
      action: entry.action,
      target_type: entry.target_type,
      target_id: entry.target_id,
      model: entry.model ?? null,
      prompt_version: entry.prompt_version ?? null,
      details: entry.details ?? null,
    })
  }

  addQA(sessionId: string, question: string, source: QuestionSource, meta: QAMeta, askedAt: Date, answeredAt: Date | null): QAItem {
    const seq = this.qaOf(sessionId).length + 1
    const qa: QAItem = {
      id: newId(),
      session_id: sessionId,
      seq,
      question,
      question_source: source,
      answer_deidentified: answeredAt ? meta.answer : null,
      asked_at: iso(askedAt),
      answered_at: answeredAt ? iso(answeredAt) : null,
      created_at: iso(askedAt),
    }
    this.qaItems.push(qa)
    this.qaMeta.set(qa.id, meta)
    return qa
  }

  decide(sessionId: string, decision: DecisionStatus, reason: string, deciderId: string, at = new Date()): RoundDecision {
    const s = this.session(sessionId)!
    const row: RoundDecision = {
      id: newId(),
      application_id: s.application_id,
      round_id: s.round_id,
      session_id: s.id,
      revision: this.decisionHistory(s.application_id, s.round_id).length + 1,
      decision,
      reason,
      decided_by: deciderId,
      decided_by_name: this.interviewer(deciderId)?.name ?? '',
      created_at: iso(at),
    }
    this.decisions.push(row)
    return row
  }

  /** Next answer from the generic pool for a posting (direct input, follow-ups of follow-ups). */
  nextGenericAnswer(postingKey: 'P1' | 'P2'): string {
    const n = this.genericCursor.get(`a:${postingKey}`) ?? 0
    this.genericCursor.set(`a:${postingKey}`, n + 1)
    const pool = GENERIC_BANK[postingKey]!.answers
    return pool[n % pool.length]!
  }

  // ----- views -----------------------------------------------------------------------------------

  counts(postingId: string): PostingCounts {
    const apps = this.applications.filter((a) => a.posting_id === postingId && !a.deleted_at && !a.withdrawn_at)
    const rounds = this.roundsOf(postingId).map((r) => ({
      round: this.roundRef(r),
      reached: 0,
      ...(Object.fromEntries(STEP_STATUSES.map((st) => [st, 0])) as Record<StepStatus, number>),
    }))
    const c: PostingCounts = { applications: apps.length, passed: 0, hold: 0, rejected: 0, interviewing: 0, interviewed: 0, evaluated: 0, rounds, final: 0 }
    for (const a of apps) {
      const s = this.screeningOf(a.id)
      if (s) c[s.status] += 1
      const steps = this.progress(a.id)
      for (const step of steps) {
        if (step.kind !== 'round' || step.status === null) continue
        const row = rounds.find((r) => r.round.id === step.round!.id)!
        row.reached += 1
        row[step.status] += 1
      }
      if (steps.at(-1)!.status === 'passed') c.final += 1
      const now = steps.find((x) => x.status !== 'passed') ?? steps.at(-1)!
      if (now.status === 'scheduled' || now.status === 'in_progress') c.interviewing += 1
      const done = this.sessionsOf(a.id).filter((x) => x.status === 'completed')
      if (done.length > 0) {
        c.interviewed += 1
        if (done.every((x) => this.isEvaluated(x.id))) c.evaluated += 1
      }
    }
    return c
  }

  postingSummary(p: JobPosting): PostingSummary {
    const { jd_text: _jd, ...rest } = p
    const brief = (c: CompetencySet | null) => (c ? { id: c.id, version: c.version, approved_at: c.approved_at } : null)
    const first = this.firstRound(p.id)
    return {
      ...rest,
      counts: this.counts(p.id),
      rounds: this.roundsOf(p.id).map((r) => this.roundRef(r)),
      latest_competency_set: first ? brief(this.latestSet(first.id)) : null,
      approved_competency_set: first ? brief(this.approvedSet(first.id)) : null,
    }
  }

  postingDetail(p: JobPosting) {
    return { ...p, counts: this.counts(p.id), rounds: this.roundsOf(p.id).map((r) => this.roundRef(r)) }
  }

  applicationRows(postingId: string): ApplicationRow[] {
    return this.applications
      .filter((a) => a.posting_id === postingId && !a.deleted_at && !a.withdrawn_at)
      .map((a) => {
        const cand = this.candidate(a.candidate_id)!
        return {
          application_id: a.id,
          candidate: { id: cand.id, pseudonym: cand.pseudonym },
          screening: this.screeningOf(a.id),
          years_experience: a.profile?.years_experience ?? null,
          top_skills: a.profile?.skills.slice(0, 3) ?? [],
          stage: this.stage(a.id),
          progress: this.progress(a.id),
          channel: a.channel,
          created_at: a.created_at,
        }
      })
  }

  brief(s: InterviewSession): SessionBrief {
    return { id: s.id, round: this.roundRef(this.round(s.round_id)!), status: s.status, mode: s.mode, scheduled_at: s.scheduled_at, ended_at: s.ended_at }
  }

  applicationDetail(id: string): ApplicationDetail | null {
    const a = this.application(id)
    if (!a) return null
    const p = this.posting(a.posting_id)!
    return {
      application: a,
      candidate: this.candidate(a.candidate_id)!,
      posting: { id: p.id, title: p.title, job_family: p.job_family },
      screening: this.screeningOf(a.id),
      sessions: this.sessionsOf(a.id)
        .sort((x, y) => byTime(x.scheduled_at, y.scheduled_at))
        .map((s) => this.brief(s)),
      document: this.documents.get(a.id) ?? null,
      stage: this.stage(a.id),
      progress: this.progress(a.id),
      decisions: this.decisions
        .filter((d) => d.application_id === a.id)
        .sort((x, y) => this.round(y.round_id)!.position - this.round(x.round_id)!.position || y.revision - x.revision),
    }
  }

  /** Mock upload: a new candidate with a generic profile, screened as hold (people decide). */
  addUpload(postingId: string, filename: string): UploadResult {
    return this.addApplication(postingId, filename, 'upload')
  }

  /** A new candidate and application from an upload or the recruiting site (a retried 연동 event). */
  addApplication(postingId: string, filename: string, channel: ApplicationChannel): UploadResult {
    const n = this.candidates.length + 1
    const now = new Date()
    const candidate = { id: newId(), pseudonym: pseudonymOf(n), consent_recording: false, consent_at: null, deleted_at: null, created_at: iso(now) }
    const application = {
      id: newId(),
      candidate_id: candidate.id,
      posting_id: postingId,
      profile: {
        summary: '업로드한 서류에서 구조화한 프로필 (모의).',
        years_experience: 3 + Math.floor(hash01(filename) * 6),
        skills: ['Python', 'SQL', '데이터 분석'],
        experience: [{ company: '[회사-1]', role: '엔지니어', period: '2021.03 – 현재', highlights: [] }],
        education: [{ school: '[학교-1]', degree: '학사', major: '공학' }],
        projects: [],
        certifications: [],
      },
      channel,
      withdrawn_at: null,
      deleted_at: null,
      created_at: iso(now),
    }
    const fit = 50 + Math.round(hash01(`${filename}:fit`) * 40)
    const screening = {
      id: newId(),
      application_id: application.id,
      fit_score: fit,
      rationale: `서류를 JD와 대조했습니다 (AI 권고: ${fit >= 75 ? '통과' : '보류'})
+ 필수 요건 일부 충족
- 경력 근거 확인 필요`,
      status: 'hold' as const,
      model: SCREENING_MODEL,
      prompt_version: 'screening-v0.4',
      created_at: iso(now),
    }
    const ext = filename.split('.').pop()?.toLowerCase() ?? ''
    const format = channel === 'site' ? 'site' : ext === 'htm' ? 'html' : ext
    const document = { format, blocks: 6, hidden_blocks: 0, images_dropped: 0, replacements: 4 }
    this.candidates.push(candidate)
    this.applications.push(application)
    this.screenings.push(screening)
    this.documents.set(application.id, document)
    return { application_id: application.id, candidate: { id: candidate.id, pseudonym: candidate.pseudonym }, screening, document }
  }

  candidateIndex(): CandidateIndexItem[] {
    return this.applications.map((a) => {
      const c = this.candidate(a.candidate_id)!
      const p = this.posting(a.posting_id)!
      const s = this.screeningOf(a.id)
      return {
        candidate_id: c.id,
        pseudonym: c.pseudonym,
        application_id: a.id,
        posting_id: p.id,
        posting_title: p.title,
        screening_status: s?.status ?? null,
        fit_score: s?.fit_score ?? null,
      }
    })
  }

  /** Applications waiting for their next round, optionally only those for the round at `position`. */
  schedulable(position?: number): SchedulableApplication[] {
    const rows: SchedulableApplication[] = []
    for (const a of this.applications.filter((x) => !x.deleted_at && !x.withdrawn_at)) {
      const r = this.nextRound(a.id)
      const sc = this.screeningOf(a.id)
      if (!r || !sc || (position !== undefined && r.position !== position)) continue
      const steps = this.progress(a.id)
      const before = steps[steps.findIndex((x) => x.round?.id === r.id) - 1]!
      const c = this.candidate(a.candidate_id)!
      const p = this.posting(a.posting_id)!
      rows.push({
        application_id: a.id,
        candidate: { id: c.id, pseudonym: c.pseudonym },
        posting: { id: p.id, title: p.title, job_family: p.job_family },
        fit_score: sc.fit_score,
        round: this.roundRef(r),
        mode: r.default_mode,
        recommended_interviewers: r.recommended_interviewers,
        since: before.at,
      })
    }
    return rows
  }

  panelView(sessionId: string) {
    return this.panelOf(sessionId).map((si) => ({ ...si, interviewer: this.interviewer(si.interviewer_id)! }))
  }

  sessionSummary(s: InterviewSession): SessionSummary {
    const a = this.application(s.application_id)!
    const c = this.candidate(a.candidate_id)!
    const p = this.posting(a.posting_id)!
    return {
      ...s,
      candidate: { id: c.id, pseudonym: c.pseudonym },
      posting: { id: p.id, title: p.title },
      round: this.roundRef(this.round(s.round_id)!),
      round_status: this.roundStatusOf(s),
      interviewers: this.panelView(s.id),
      qa_count: this.qaOf(s.id).length,
      ai_scoring: this.aiStatus(s.id),
      submitted_interviewer_ids: this.panelOf(s.id)
        .filter((pi) => this.submittedAt.has(`${s.id}:${pi.interviewer_id}`))
        .map((pi) => pi.interviewer_id),
    }
  }

  sessionDetail(id: string): SessionDetail | null {
    const s = this.session(id)
    if (!s) return null
    const a = this.application(s.application_id)!
    const c = this.candidate(a.candidate_id)!
    const p = this.posting(a.posting_id)!
    const sc = this.screeningOf(a.id)
    const set = this.setOfSession(s.id)
    return {
      session: s,
      posting: { id: p.id, title: p.title, job_family: p.job_family },
      round: this.roundView(this.round(s.round_id)!),
      card: {
        candidate: { id: c.id, pseudonym: c.pseudonym, consent_recording: c.consent_recording, consent_at: c.consent_at },
        profile: a.profile,
        screening: sc ? { fit_score: sc.fit_score, status: sc.status, rationale: sc.rationale } : null,
        previous_sessions: this.sessionsOf(a.id)
          .filter((x) => x.id !== s.id && x.status === 'completed')
          .map((x) => this.brief(x)),
        previous_rounds: this.earlierSessions(s.id).map((x) => this.previousRound(s, x)),
      },
      interviewers: this.panelView(s.id),
      competency_set: set,
      preset_questions: set ? this.presetsOf(set.id) : [],
      carryover_questions: this.carryover.get(s.id) ?? [],
      qa_items: this.qaOf(s.id),
      notes: this.notes.filter((n) => n.session_id === s.id).sort((x, y) => x.created_at.localeCompare(y.created_at)),
    }
  }

  evaluation(id: string): Evaluation | null {
    const s = this.session(id)
    if (!s) return null
    const a = this.application(s.application_id)!
    const c = this.candidate(a.candidate_id)!
    const p = this.posting(a.posting_id)!
    const status = this.aiStatus(id)
    const qa = this.qaOf(id)
    const qaIds = new Set(qa.map((q) => q.id))
    const all = this.scores.filter((x) => (x.qa_item_id ? qaIds.has(x.qa_item_id) : this.scoreSession.get(x.id) === id))
    const ai = status === 'completed' ? all.filter((x) => x.evaluator_type === 'ai') : []
    return {
      session: s,
      candidate: { id: c.id, pseudonym: c.pseudonym },
      posting: { id: p.id, title: p.title },
      round: this.roundView(this.round(s.round_id)!),
      competency_set: this.setOfSession(s.id),
      qa_items: qa,
      ai: {
        status,
        model: status === 'not_started' ? null : AI_MODEL,
        prompt_version: status === 'not_started' ? null : SCORING_PROMPT,
        samples: SCORING_SAMPLES,
        scores: ai,
        summary: summarizeAiScores(ai),
      },
      interviewers: this.panelOf(id).map((pi) => ({
        interviewer: this.interviewer(pi.interviewer_id)!,
        role: pi.role,
        submitted_at: this.submittedAt.get(`${id}:${pi.interviewer_id}`) ?? null,
        scores: all.filter((x) => x.evaluator_type === 'interviewer' && x.evaluator_id === pi.interviewer_id),
      })),
      decision: this.decisionPanel(id),
      check_points: this.checkPoints.filter((x) => x.session_id === id),
    }
  }

  activity(limit: number): ActivityItem[] {
    return this.audit.slice(0, limit).map((e) => ({ ...e, actor_label: this.actorLabel(e), target_label: this.targetLabel(e) }))
  }

  private actorLabel(e: AuditLog): string {
    if (e.actor_type === 'ai') return 'AI'
    if (e.actor_type === 'system') return '시스템'
    return this.interviewer(e.actor_id ?? '')?.name ?? '사용자'
  }

  private targetLabel(e: AuditLog): string | null {
    if (!e.target_id) return null
    switch (e.target_type) {
      case 'interview_session': {
        const s = this.session(e.target_id)
        const a = s && this.application(s.application_id)
        return a ? (this.candidate(a.candidate_id)?.pseudonym ?? null) : null
      }
      case 'screening': {
        const sc = this.screenings.find((x) => x.id === e.target_id)
        const a = sc && this.application(sc.application_id)
        return a ? (this.candidate(a.candidate_id)?.pseudonym ?? null) : null
      }
      case 'application': {
        const a = this.application(e.target_id)
        return a ? (this.candidate(a.candidate_id)?.pseudonym ?? null) : null
      }
      case 'competency_set': {
        const cs = this.competencySets.find((x) => x.id === e.target_id)
        const p = cs && this.posting(cs.posting_id)
        const r = cs && this.round(cs.round_id)
        return p && cs && r ? `${p.title} ${r.label} v${cs.version}` : null
      }
      case 'interview_round': {
        const r = this.round(e.target_id)
        const p = r && this.posting(r.posting_id)
        return p && r ? `${p.title} ${r.label}` : null
      }
      case 'job_posting':
        return this.posting(e.target_id)?.title ?? null
      default:
        return null
    }
  }
}

// ---------------------------------------------------------------------------------------------
// AI (mock): scores per answered QA item and points to check, evidence quoted from the answer.
// ---------------------------------------------------------------------------------------------

function pickEvidence(answer: string, salt: string): string {
  const sentences = splitSentences(answer)
  if (sentences.length === 0) return answer
  const withNumbers = sentences.filter((s) => /\d/.test(s))
  const pool = withNumbers.length > 0 ? withNumbers : sentences
  return pool[Math.floor(hash01(salt) * pool.length)]!
}

export function generateAiScores(db: MockDb, sessionId: string) {
  const session = db.session(sessionId)!
  const app = db.application(session.application_id)!
  const fit = db.screeningOf(app.id)?.fit_score ?? 70
  const created = session.ended_at ?? iso(new Date())
  db.scores = db.scores.filter((s) => !(s.evaluator_type === 'ai' && db.qaOf(sessionId).some((q) => q.id === s.qa_item_id)))
  for (const qa of db.qaOf(sessionId)) {
    const meta = db.qaMeta.get(qa.id)
    if (!qa.answer_deidentified || !meta?.competency) continue
    const h = hash01(`${qa.id}:${meta.competency}`)
    const base = fit / 20 // 0..5
    const score = Math.max(1, Math.min(5, Math.round(base - 1.3 + h * 2.4)))
    const confidence = Math.round((0.52 + hash01(`${qa.id}:conf`) * 0.42) * 100) / 100
    db.scores.push({
      id: newId(),
      qa_item_id: qa.id,
      competency: meta.competency,
      score,
      evidence: pickEvidence(qa.answer_deidentified, qa.id),
      confidence,
      evaluator_type: 'ai',
      evaluator_id: null,
      model: AI_MODEL,
      prompt_version: SCORING_PROMPT,
      created_at: created,
    })
  }
}

/** Like the fake model (and the seed): the two thinnest answers, quoted verbatim. */
export function generateAiCheckPoints(db: MockDb, sessionId: string) {
  const session = db.session(sessionId)!
  db.checkPoints = db.checkPoints.filter((p) => !(p.session_id === sessionId && p.source === 'ai'))
  const answered = db.qaOf(sessionId).filter((q) => q.answer_deidentified)
  const at = iso(addMinutes(new Date(session.ended_at ?? new Date()), 3))
  for (const qa of [...answered].sort((a, b) => weight(a.answer_deidentified!) - weight(b.answer_deidentified!)).slice(0, 2)) {
    const competency = db.qaMeta.get(qa.id)?.competency ?? ''
    db.checkPoints.push({
      id: newId(),
      session_id: sessionId,
      source: 'ai',
      competency: competency || null,
      text: `${competency}: 이 답변은 근거가 적어 본인이 직접 한 판단과 결과를 다음 차수에서 구체적으로 확인할 필요가 있습니다.`,
      evidence: thinnest(splitSentences(qa.answer_deidentified!)),
      qa_item_id: qa.id,
      author_id: null,
      author_name: null,
      model: AI_MODEL,
      created_at: at,
    })
  }
}

// ---------------------------------------------------------------------------------------------
// Seed
// ---------------------------------------------------------------------------------------------

function interviewerId(key: string) {
  return INTERVIEWERS.find((i) => i.key === key)!.id
}

function candidateIdOf(n: number) {
  return `c0a1b2c3-0000-4000-9000-${String(n).padStart(12, '0')}`
}

function applicationIdOf(n: number) {
  return `d1e2f3a4-0000-4000-9000-${String(n).padStart(12, '0')}`
}

export function roundIdOf(postingId: string, position: number) {
  return `b2c3d4e5-0000-4000-9000-${postingId.slice(-4)}0000000${position}`
}

function setIdOf(postingId: string, position: number, version: number) {
  const middle = position === 1 ? '0000000' : `00000${position}0`
  return `e5f6a7b8-0000-4000-9000-${postingId.slice(-4)}${middle}${version}`
}

function seed(db: MockDb) {
  const now = db.now
  const daysAgo = (d: number, h = 10, m = 0) => {
    const p = kstParts(addDays(now, -d))
    return kstDate(p.year, p.month, p.day, h, m)
  }

  for (const i of INTERVIEWERS) {
    db.interviewers.push({ id: i.id, employee_no: i.employee_no, name: i.name, job_family: i.job_family, department: i.department, is_admin: i.key === ME_KEY, created_at: iso(daysAgo(120)) })
  }

  for (const p of POSTING_SEEDS) {
    const created = iso(daysAgo(p.createdDaysAgo, 9))
    db.postings.push({ id: p.id, title: p.title, job_family: p.job_family, jd_text: p.jd_text, status: p.status, site_posting_no: p.site_posting_no, created_at: created })
    p.rounds.forEach((r, i) => {
      const position = i + 1
      const roundId = roundIdOf(p.id, position)
      db.rounds.push({
        id: roundId,
        posting_id: p.id,
        position,
        label: `${position}차`,
        name: r.name,
        default_mode: r.default_mode,
        recommended_interviewers: r.recommended_interviewers,
        show_previous_scores: r.show_previous_scores,
        created_at: created,
      })
      let approved: CompetencySet | null = null
      for (const s of r.sets) {
        const at = daysAgo(s.daysAgo, 11)
        const set: CompetencySet = {
          id: setIdOf(p.id, position, s.version),
          posting_id: p.id,
          round_id: roundId,
          version: s.version,
          competencies: structuredClone(s.competencies),
          approved_by: s.approvedBy ? interviewerId(s.approvedBy) : null,
          approved_at: s.approvedBy ? iso(addMinutes(at, 180)) : null,
          created_at: iso(at),
        }
        db.competencySets.push(set)
        if (set.approved_at) approved = set
      }
      if (approved) db.presets.set(approved.id, r.presets.map((q: PresetSeed) => ({ ...q, origin: null })))
    })
  }

  for (const c of CANDIDATES) {
    const posting = c.posting === 'P1' ? P1 : P2
    const applied = daysAgo(c.appliedDaysAgo, 9 + (c.n % 8), (c.n * 7) % 60)
    db.candidates.push({ id: candidateIdOf(c.n), pseudonym: pseudonymOf(c.n), consent_recording: false, consent_at: null, deleted_at: null, created_at: iso(applied) })
    db.applications.push({
      id: applicationIdOf(c.n),
      candidate_id: candidateIdOf(c.n),
      posting_id: posting.id,
      profile: c.profile,
      channel: 'upload',
      withdrawn_at: null,
      deleted_at: null,
      created_at: iso(applied),
    })
    const rationale = [c.summaryLine, ...c.strengths.map((s) => `+ ${s}`), ...c.concerns.map((s) => `- ${s}`)].join('\n')
    db.screenings.push({
      id: `f7a8b9c0-0000-4000-9000-${String(c.n).padStart(12, '0')}`,
      application_id: applicationIdOf(c.n),
      fit_score: c.fit,
      rationale,
      status: c.status,
      model: SCREENING_MODEL,
      prompt_version: 'screening-v0.4',
      created_at: iso(addMinutes(applied, 90)),
    })
  }

  seedSessions(db, now, daysAgo)
  seedAvailability(db, now)
  seedAudit(db, now)
}

interface SessionSeed {
  n: number
  mode: SessionMode
  status: SessionStatus
  scheduled: Date
  started?: Date
  ended?: Date
  panel: [string, InterviewerRole][]
  /** 1 = 1차 */
  round?: number
}

function seedSessions(db: MockDb, now: Date, daysAgo: (d: number, h?: number, m?: number) => Date) {
  const make = (key: string, s: SessionSeed) => {
    const id = `0a1b2c3d-0000-4000-9000-${key.padEnd(12, '0')}`
    const posting = db.application(applicationIdOf(s.n))!.posting_id
    const roundId = roundIdOf(posting, s.round ?? 1)
    const ran = s.status === 'completed' || s.status === 'in_progress'
    db.sessions.push({
      id,
      application_id: applicationIdOf(s.n),
      round_id: roundId,
      mode: s.mode,
      status: s.status,
      scheduled_at: iso(s.scheduled),
      started_at: s.started ? iso(s.started) : null,
      ended_at: s.ended ? iso(s.ended) : null,
      has_recording: ran,
      created_at: iso(addDays(s.scheduled, -4)),
    })
    for (const [k, role] of s.panel) db.sessionInterviewers.push({ session_id: id, interviewer_id: interviewerId(k), role })
    if (ran) {
      const approved = db.approvedSet(roundId)
      if (approved) db.pinned.set(id, approved.id)
      const cand = db.candidate(candidateIdOf(s.n))!
      cand.consent_recording = true
      cand.consent_at = iso(addMinutes(s.started ?? s.scheduled, -1))
    }
    return id
  }

  // Today: later sessions at 16:00 / 17:30 KST, or 1h / 2.5h from now if that has passed.
  const today16 = (() => {
    const p = kstParts(now)
    return kstDate(p.year, p.month, p.day, 16, 0)
  })()
  const soon = new Date(Math.ceil(addMinutes(now, 60).getTime() / (30 * MINUTE)) * 30 * MINUTE)
  const s1At = today16.getTime() > soon.getTime() ? today16 : soon
  const tomorrow10 = (() => {
    const p = kstParts(addDays(now, 1))
    return kstDate(p.year, p.month, p.day, 10, 0)
  })()

  // In progress: CAND-0007 (1차)
  const live = make('live', {
    n: 7,
    mode: 'remote',
    status: 'in_progress',
    scheduled: addMinutes(now, -15),
    started: addMinutes(now, -13),
    panel: [['kim', 'lead'], ['park', 'panel']],
  })
  make('s1', { n: 11, mode: 'remote', status: 'scheduled', scheduled: s1At, panel: [['kim', 'lead'], ['park', 'panel']] })
  make('s2', { n: 18, mode: 'onsite', status: 'scheduled', scheduled: addMinutes(s1At, 90), panel: [['lee', 'lead'], ['jung', 'panel']] })
  // CAND-0003 passed 1차 (c1): 2차 tomorrow.
  make('s3', { n: 3, mode: 'onsite', status: 'scheduled', scheduled: tomorrow10, panel: [['park', 'lead'], ['kim', 'panel']], round: 2 })
  const c1 = make('c1', { n: 3, mode: 'remote', status: 'completed', scheduled: daysAgo(1, 14), started: daysAgo(1, 14, 2), ended: daysAgo(1, 14, 48), panel: [['kim', 'lead'], ['park', 'panel']] })
  const c2 = make('c2', { n: 5, mode: 'onsite', status: 'completed', scheduled: daysAgo(2, 10), started: daysAgo(2, 10, 1), ended: daysAgo(2, 10, 52), panel: [['park', 'lead'], ['kim', 'panel']] })
  const c3 = make('c3', { n: 14, mode: 'remote', status: 'completed', scheduled: daysAgo(1, 15, 30), started: daysAgo(1, 15, 31), ended: daysAgo(1, 16, 20), panel: [['lee', 'lead'], ['jung', 'panel']] })
  const c4 = make('c4', { n: 16, mode: 'remote', status: 'completed', scheduled: addMinutes(now, -125), started: addMinutes(now, -124), ended: addMinutes(now, -75), panel: [['jung', 'lead'], ['lee', 'panel']] })
  // Earlier days and 2차 (demo/seed.py rounds_history_)
  const r1n1 = make('r1n1', { n: 1, mode: 'remote', status: 'completed', scheduled: daysAgo(9, 14), started: daysAgo(9, 14, 2), ended: daysAgo(9, 14, 50), panel: [['kim', 'lead'], ['park', 'panel']] })
  const r2n1 = make('r2n1', { n: 1, mode: 'onsite', status: 'completed', scheduled: daysAgo(2, 15), started: daysAgo(2, 15, 1), ended: daysAgo(2, 15, 45), panel: [['park', 'lead'], ['kim', 'panel']], round: 2 })
  const r1n9 = make('r1n9', { n: 9, mode: 'remote', status: 'completed', scheduled: daysAgo(6, 10), started: daysAgo(6, 10, 1), ended: daysAgo(6, 10, 50), panel: [['kim', 'lead'], ['park', 'panel']] })
  const live2 = make('live2', { n: 9, mode: 'onsite', status: 'in_progress', scheduled: addMinutes(now, -20), started: addMinutes(now, -19), panel: [['lee', 'lead'], ['choi', 'panel']], round: 2 })
  const r1n12 = make('r1n12', { n: 12, mode: 'remote', status: 'completed', scheduled: daysAgo(5, 14), started: daysAgo(5, 14, 1), ended: daysAgo(5, 14, 46), panel: [['lee', 'lead'], ['jung', 'panel']] })
  const r1n20 = make('r1n20', { n: 20, mode: 'remote', status: 'completed', scheduled: daysAgo(3, 10), started: daysAgo(3, 10, 1), ended: daysAgo(3, 10, 44), panel: [['jung', 'lead'], ['lee', 'panel']] })

  const presetSeed = (pid: string) => {
    for (const p of [P1, P2]) for (const r of p.rounds) for (const q of r.presets) if (q.id === pid) return { postingKey: (p === P1 ? 'P1' : 'P2') as 'P1' | 'P2', q }
    throw new Error(pid)
  }

  /** Ask a preset and (optionally) one of its suggestions, with answers. */
  const askPreset = (sessionId: string, pid: string, at: Date, answered: boolean) => {
    const { postingKey, q } = presetSeed(pid)
    const bank = ANSWER_BANK[pid]!
    return db.addQA(sessionId, q.question, 'preset', { postingKey, presetId: pid, competency: q.competency, answer: bank.answer, suggestions: bank.suggestions }, at, answered ? addMinutes(at, 2) : null)
  }
  const askSuggestion = (sessionId: string, pid: string, idx: number, at: Date) => {
    const { postingKey } = presetSeed(pid)
    const sug = ANSWER_BANK[pid]!.suggestions[idx]!
    const generic = GENERIC_BANK[postingKey]!.suggestions
    return db.addQA(sessionId, sug.question, 'ai_suggested', { postingKey, presetId: null, competency: sug.competency, answer: sug.answer, suggestions: generic }, at, addMinutes(at, 2))
  }
  const transcript = (sessionId: string, answered: QAItem[], pending: QAItem) => {
    const segs: TranscriptSegment[] = []
    let t = 60_000
    const push = (qa: QAItem, speaker: 'interviewer' | 'candidate', text: string) => {
      const dur = Math.max(1500, text.length * 110)
      segs.push({ segment_id: newId(), qa_item_id: qa.id, speaker, text, is_final: true, start_ms: t, end_ms: t + dur })
      t += dur + 600
    }
    for (const qa of answered) {
      push(qa, 'interviewer', qa.question)
      for (const s of splitSentences(qa.answer_deidentified ?? '')) push(qa, 'candidate', s)
    }
    t = 12 * 60_000
    push(pending, 'interviewer', pending.question)
    db.transcripts.set(sessionId, segs)
  }
  const note = (sessionId: string, key: string, at: Date, content: string) =>
    db.notes.push({ id: newId(), session_id: sessionId, author_id: interviewerId(key), content, created_at: iso(at) })
  const checkPoint = (sessionId: string, key: string, at: Date, competency: string, text: string) =>
    db.checkPoints.push({ id: newId(), session_id: sessionId, source: 'interviewer', competency, text, evidence: null, qa_item_id: null, author_id: interviewerId(key), author_name: db.interviewer(interviewerId(key))!.name, model: null, created_at: iso(at) })

  // Live session history: Q1 (answered), follow-up (answered), Q3 asked a moment ago (answer streams on connect).
  const l1 = askPreset(live, 'p1-q1', addMinutes(now, -12), true)
  const l2 = askSuggestion(live, 'p1-q1', 0, addMinutes(now, -8))
  const l3 = askPreset(live, 'p1-q3', addMinutes(now, -1), false)
  transcript(live, [l1, l2], l3)
  note(live, 'kim', addMinutes(now, -6), '엣지 링 사례 설명이 구체적. 비용 판단 근거까지 스스로 설명함.')

  // Completed sessions
  askPreset(c1, 'p1-q2', daysAgo(1, 14, 4), true)
  askPreset(c1, 'p1-q5', daysAgo(1, 14, 12), true)
  askSuggestion(c1, 'p1-q5', 0, daysAgo(1, 14, 18))
  askPreset(c1, 'p1-q7', daysAgo(1, 14, 25), true)
  askPreset(c1, 'p1-q4', daysAgo(1, 14, 34), true)

  askPreset(c2, 'p1-q1', daysAgo(2, 10, 3), true)
  askPreset(c2, 'p1-q3', daysAgo(2, 10, 14), true)
  askSuggestion(c2, 'p1-q3', 1, daysAgo(2, 10, 22))
  askPreset(c2, 'p1-q8', daysAgo(2, 10, 30), true)
  askPreset(c2, 'p1-q6', daysAgo(2, 10, 40), true)

  askPreset(c3, 'p2-q3', daysAgo(1, 15, 33), true)
  askSuggestion(c3, 'p2-q3', 0, daysAgo(1, 15, 41))
  askPreset(c3, 'p2-q4', daysAgo(1, 15, 48), true)
  askPreset(c3, 'p2-q6', daysAgo(1, 15, 58), true)
  askPreset(c3, 'p2-q1', daysAgo(1, 16, 8), true)

  askPreset(c4, 'p2-q1', addMinutes(now, -120), true)
  askPreset(c4, 'p2-q2', addMinutes(now, -108), true)
  askPreset(c4, 'p2-q5', addMinutes(now, -95), true)

  askPreset(r1n1, 'p1-q1', daysAgo(9, 14, 4), true)
  askSuggestion(r1n1, 'p1-q1', 2, daysAgo(9, 14, 12))
  askPreset(r1n1, 'p1-q5', daysAgo(9, 14, 20), true)
  askPreset(r1n1, 'p1-q7', daysAgo(9, 14, 30), true)
  note(r1n1, 'kim', daysAgo(9, 14, 40), '엣지 링 사례를 메커니즘 수준까지 설명. 협업 질문에서는 답이 짧아짐.')

  askPreset(r2n1, 'p1r2-q1', daysAgo(2, 15, 3), true)
  askSuggestion(r2n1, 'p1r2-q1', 0, daysAgo(2, 15, 10))
  askPreset(r2n1, 'p1r2-q3', daysAgo(2, 15, 18), true)
  askPreset(r2n1, 'p1r2-q5', daysAgo(2, 15, 28), true)

  askPreset(r1n9, 'p1-q2', daysAgo(6, 10, 3), true)
  askPreset(r1n9, 'p1-q4', daysAgo(6, 10, 14), true)
  askPreset(r1n9, 'p1-q6', daysAgo(6, 10, 25), true)
  askPreset(r1n9, 'p1-q8', daysAgo(6, 10, 36), true)
  note(r1n9, 'kim', daysAgo(6, 10, 30), '설명이 차분하고 수치 근거를 스스로 제시함.')

  const m1 = askPreset(live2, 'p1r2-q1', addMinutes(now, -17), true)
  const m2 = askSuggestion(live2, 'p1r2-q1', 1, addMinutes(now, -12))
  const m3 = askPreset(live2, 'p1r2-q3', addMinutes(now, -2), false)
  transcript(live2, [m1, m2], m3)

  ;['p2-q1', 'p2-q2', 'p2-q4', 'p2-q6'].forEach((pid, i) => askPreset(r1n12, pid, daysAgo(5, 14, 3 + i * 10), true))
  ;['p2-q3', 'p2-q5', 'p2-q2'].forEach((pid, i) => askPreset(r1n20, pid, daysAgo(3, 10, 3 + i * 12), true))

  for (const id of [c1, c2, c3, r1n1, r2n1, r1n9, r1n12, r1n20]) {
    db.aiScoring.set(id, { status: 'completed', startedAt: 0 })
    generateAiScores(db, id)
  }
  for (const id of [c1, c2, c3, r1n1, r1n9, r1n12, r1n20]) generateAiCheckPoints(db, id)
  db.aiScoring.set(c4, { status: 'running', startedAt: Date.now() })

  const interviewerScores = (sessionId: string, key: string, at: Date, rows: [string, number, string][]) => {
    for (const [competency, score, comment] of rows) {
      const id = newId()
      db.scoreSession.set(id, sessionId)
      db.scores.push({
        id,
        qa_item_id: null,
        competency,
        score,
        evidence: comment,
        confidence: null,
        evaluator_type: 'interviewer',
        evaluator_id: interviewerId(key),
        model: null,
        prompt_version: null,
        created_at: iso(at),
      })
    }
    db.submittedAt.set(`${sessionId}:${interviewerId(key)}`, iso(at))
  }
  interviewerScores(c1, 'kim', daysAgo(1, 15, 10), [
    ['공정 문제 해결', 4, '실패 원인을 스스로 찾아 검증 절차 개선까지 연결함.'],
    ['데이터 기반 분석', 3, '분석 근거는 있으나 표본 크기에 대한 설명이 부족.'],
    ['공정·장비 이해', 4, '온도와 폴리머 증착의 관계를 정확히 설명.'],
    ['협업과 커뮤니케이션', 4, '생산팀과 합의 후 재조정까지 이어간 과정이 구체적.'],
  ])
  interviewerScores(c1, 'park', daysAgo(1, 15, 40), [
    ['공정 문제 해결', 4, '재발 방지 조치까지 확인함.'],
    ['데이터 기반 분석', 4, '이벤트 겹쳐 보기로 원인을 찾은 접근이 좋음.'],
    ['공정·장비 이해', 3, '식각 메커니즘 설명은 좋으나 증착 쪽 깊이는 보통.'],
    ['협업과 커뮤니케이션', 5, '데이터로 이견을 조율하고 결과를 수용하는 태도.'],
  ])
  interviewerScores(c2, 'park', daysAgo(2, 11, 30), [
    ['공정 문제 해결', 4, '가설 설정과 DOE 검증이 체계적.'],
    ['데이터 기반 분석', 4, '다변량 분석 이후 판단 기준이 명확.'],
    ['공정·장비 이해', 3, '전후 공정 영향은 설명했으나 근거가 다소 약함.'],
    ['협업과 커뮤니케이션', 3, '장비사 협업 양식 개선은 좋으나 내부 협업 사례 부족.'],
  ])
  interviewerScores(c3, 'lee', daysAgo(1, 17), [
    ['시스템 설계', 4, '대안 비교와 선택 근거가 분명함.'],
    ['운영·장애 대응', 3, '장애 대응 절차는 좋으나 운영 규모가 작음.'],
    ['코드 품질', 4, '테스트 전략 설명이 구체적.'],
    ['협업과 커뮤니케이션', 3, '타 팀 설득 사례가 적음.'],
  ])
  interviewerScores(c3, 'jung', daysAgo(1, 17, 20), [
    ['시스템 설계', 3, '트래픽 규모 대비 설계 근거가 약함.'],
    ['운영·장애 대응', 4, '회고 문화 도입은 인상적.'],
    ['코드 품질', 3, '리뷰 기준은 보통.'],
    ['협업과 커뮤니케이션', 4, '갈등 상황 설명이 솔직함.'],
  ])
  const p1Round1: [string, string][] = [
    ['공정 문제 해결', '재발 방지까지 연결한 과정이 구체적.'],
    ['데이터 기반 분석', '변수 배제 과정이 체계적.'],
    ['공정·장비 이해', '메커니즘 설명이 정확함.'],
    ['협업과 커뮤니케이션', '유관 부서 설득 경험은 짧게만 언급.'],
  ]
  const ended = (id: string) => new Date(db.session(id)!.ended_at!)
  for (const [id, scores] of [
    [r1n1, [[4, 4, 5, 3], [5, 4, 4, 3]]],
    [r1n9, [[4, 4, 3, 4], [4, 5, 3, 4]]],
  ] as const) {
    ;(['kim', 'park'] as const).forEach((key, i) =>
      interviewerScores(id, key, addMinutes(ended(id), 70 + i * 30), p1Round1.map(([c, t], j) => [c, scores[i]![j]!, t])),
    )
  }
  const p1Round2: [string, string][] = [
    ['주도성과 책임감', '범위 밖 문제를 스스로 맡고 실수도 먼저 공유함.'],
    ['조직 적합과 성장 의지', '지원 동기와 부족한 점을 솔직하게 설명.'],
    ['협업과 영향력', '권한 없이 숫자로 다른 조직을 설득한 사례가 좋음.'],
  ]
  interviewerScores(r2n1, 'park', daysAgo(2, 16, 30), p1Round2.map(([c, t], j) => [c, [5, 4, 4][j]!, t]))
  interviewerScores(r2n1, 'kim', daysAgo(2, 17), p1Round2.map(([c, t], j) => [c, [4, 4, 5][j]!, t]))
  const p2: [string, string][] = [
    ['시스템 설계', '대안 비교와 선택 근거가 분명함.'],
    ['운영·장애 대응', '관측성 구축 경험이 구체적.'],
    ['코드 품질', '테스트 전략 설명이 구체적.'],
    ['협업과 커뮤니케이션', '타 팀과의 합의 과정이 명확.'],
  ]
  for (const [id, keys, values] of [
    [r1n12, ['lee', 'jung'], [[5, 4, 4, 4], [4, 5, 4, 4]]],
    [r1n20, ['jung', 'lee'], [[3, 4, 3, 3], [3, 3, 3, 4]]],
  ] as const) {
    keys.forEach((key, i) => interviewerScores(id, key, addMinutes(ended(id), 60 + i * 30), p2.map(([c, t], j) => [c, values[i]![j]!, t])))
  }

  // Decisions and points to check (demo/seed.py)
  const decide = (id: string, decision: DecisionStatus, key: string, at: Date, reason: string) => db.decide(id, decision, reason, interviewerId(key), at)
  decide(r1n1, 'passed', 'kim', daysAgo(8, 10), '공정 문제 해결과 데이터 근거가 구체적이고 재발 방지까지 연결함. 2차에서 리더십과 조직 간 영향력 확인 필요.')
  checkPoint(r1n1, 'kim', daysAgo(9, 16), '협업과 커뮤니케이션', '양산 이관 때 다른 부서를 설득한 경험은 짧게만 언급됨. 2차에서 영향력 사례로 확인.')
  decide(r1n9, 'passed', 'park', daysAgo(5, 11), '데이터로 현장 직감과 다른 결론을 설득한 과정이 좋음. 증착 쪽 깊이는 2차에서 확인.')
  checkPoint(r1n9, 'park', daysAgo(6, 12, 30), '공정·장비 이해', '증착 공정 경험은 서류 대비 설명이 얕음. 2차에서 책임 범위와 함께 확인.')
  decide(r1n12, 'passed', 'lee', daysAgo(4, 10), '추론 서빙 설계와 운영 근거가 구체적. 마지막 차수 합격으로 최종 합격 후보.')
  decide(r1n20, 'hold', 'jung', daysAgo(3, 15), '장애 회고 경험은 좋으나 설계 리딩 근거가 부족. 다른 지원자와 비교한 뒤 결정.')
  decide(r1n20, 'rejected', 'lee', daysAgo(2, 11), '같은 차수 지원자 대비 설계와 추론 서빙 근거가 부족해 불합격.')
  decide(c1, 'passed', 'kim', addMinutes(now, -200), '실패 원인을 스스로 찾아 검증 절차 개선까지 연결함. 2차에서 책임감과 조직 적합 확인.')
  checkPoint(c1, 'kim', daysAgo(1, 15, 12), '데이터 기반 분석', '분석 근거는 있으나 표본 크기 설명이 부족했음. 2차에서 판단 근거를 다시 확인.')
  decide(c3, 'hold', 'lee', addMinutes(now, -150), '설계 근거는 충분하나 운영 경험의 규모가 작음. 같은 차수 다른 지원자 결과를 보고 다시 결정.')
}

/** Weekly availability templates (KST hours), Mon..Fri. */
const AVAILABILITY_TEMPLATES: Record<string, [number, number][][]> = {
  kim: [[[10, 12], [14, 17]], [[9, 11.5]], [[13, 18]], [[10, 12], [15, 17]], [[9, 12]]],
  park: [[[9, 11], [15, 18]], [[10, 12], [14, 16]], [[14, 17]], [[9, 11.5], [15.5, 18]], [[10, 11]]],
  lee: [[[13, 16]], [[9, 12]], [[10, 12], [14, 15]], [[13, 18]], [[9, 11]]],
  jung: [[[10, 12], [13.5, 15]], [[9.5, 11]], [[15, 18]], [[10, 12], [14, 16]], [[13, 17]]],
  choi: [[[9, 12]], [[13, 17]], [[9, 10.5]], [[9, 11]], [[14, 18]]],
}

function seedAvailability(db: MockDb, now: Date) {
  const week0 = startOfKstWeek(now)
  for (const [key, days] of Object.entries(AVAILABILITY_TEMPLATES)) {
    for (let w = 0; w < 2; w++) {
      for (let d = 0; d < 5; d++) {
        // Next week rotates the template by one day so the two weeks differ.
        const blocks = days[(d + w) % 5]!
        const day = startOfKstDay(addDays(week0, w * 7 + d))
        for (const [from, to] of blocks) {
          db.availabilities.push({
            id: newId(),
            interviewer_id: interviewerId(key),
            start_at: iso(addMinutes(day, from * 60)),
            end_at: iso(addMinutes(day, to * 60)),
            source: 'manual',
            created_at: iso(addDays(week0, -3)),
          })
        }
      }
    }
  }
}

function seedAudit(db: MockDb, now: Date) {
  const sid = (key: string) => `0a1b2c3d-0000-4000-9000-${key.padEnd(12, '0')}`
  const scr = (n: number) => `f7a8b9c0-0000-4000-9000-${String(n).padStart(12, '0')}`
  const p1v2 = db.competencySets.find((c) => c.posting_id === P1.id && c.round_id === roundIdOf(P1.id, 1) && c.version === 2)!
  const p2v1 = db.competencySets.find((c) => c.posting_id === P2.id && c.version === 1)!
  const entries: Parameters<MockDb['log']>[0][] = [
    { occurred_at: iso(addDays(now, -3)), actor_type: 'ai', action: 'screening.batch_completed', target_type: 'job_posting', target_id: P2.id, model: SCREENING_MODEL, details: { count: 9 } },
    { occurred_at: iso(addDays(now, -2)), actor_type: 'ai', action: 'competency_set.generated', target_type: 'competency_set', target_id: p1v2.id, model: AI_MODEL },
    { occurred_at: iso(addMinutes(addDays(now, -2), 50)), actor_type: 'user', actor_id: interviewerId('park'), action: 'score.interviewer_submitted', target_type: 'interview_session', target_id: sid('c2') },
    { occurred_at: iso(addDays(now, -1)), actor_type: 'user', actor_id: interviewerId('lee'), action: 'competency_set.approved', target_type: 'competency_set', target_id: p2v1.id },
    { occurred_at: iso(addMinutes(addDays(now, -1), 30)), actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sid('c1'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(addDays(now, -1), 70)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'score.interviewer_submitted', target_type: 'interview_session', target_id: sid('c1') },
    { occurred_at: iso(addMinutes(addDays(now, -1), 95)), actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sid('c3'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(now, -200)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'round.decided', target_type: 'application', target_id: applicationIdOf(3), details: { decision: 'passed', round: 1 } },
    { occurred_at: iso(addMinutes(now, -190)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'session.scheduled', target_type: 'interview_session', target_id: sid('s3'), details: { round: 2 } },
    { occurred_at: iso(addMinutes(now, -180)), actor_type: 'user', actor_id: interviewerId('park'), action: 'screening.status_changed', target_type: 'screening', target_id: scr(13), details: { from: 'rejected', to: 'hold' } },
    { occurred_at: iso(addMinutes(now, -150)), actor_type: 'user', actor_id: interviewerId('lee'), action: 'round.decided', target_type: 'application', target_id: applicationIdOf(14), details: { decision: 'hold', round: 1 } },
    { occurred_at: iso(addMinutes(now, -75)), actor_type: 'user', actor_id: interviewerId('jung'), action: 'session.completed', target_type: 'interview_session', target_id: sid('c4') },
    { occurred_at: iso(addMinutes(now, -75)), actor_type: 'ai', action: 'score.ai_started', target_type: 'interview_session', target_id: sid('c4'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(now, -14)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'consent.recorded', target_type: 'interview_session', target_id: sid('live'), details: { consent_recording: true } },
    { occurred_at: iso(addMinutes(now, -13)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'session.started', target_type: 'interview_session', target_id: sid('live') },
    { occurred_at: iso(addMinutes(now, -8)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'qa.created', target_type: 'interview_session', target_id: sid('live'), details: { question_source: 'ai_suggested' } },
    { occurred_at: iso(addMinutes(now, -1)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'qa.created', target_type: 'interview_session', target_id: sid('live'), details: { question_source: 'preset' } },
  ]
  for (const e of entries.sort((a, b) => byTime(a.occurred_at ?? null, b.occurred_at ?? null))) db.log(e)
}

// ---------------------------------------------------------------------------------------------

let current: MockDb | null = null

export function getDb(): MockDb {
  current ??= new MockDb()
  return current
}

export function resetDb(now?: Date): MockDb {
  current = new MockDb(now)
  return current
}
