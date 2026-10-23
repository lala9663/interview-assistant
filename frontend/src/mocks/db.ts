/**
 * In-memory mock database for MSW. Seeded relative to "now" so the dashboard always has a
 * live interview, today's schedule and recent results. All people are fictional.
 */
import type {
  ActivityItem,
  AiScoringStatus,
  Application,
  ApplicationDetail,
  ApplicationRow,
  ApplicationStage,
  AuditLog,
  Availability,
  Candidate,
  CandidateIndexItem,
  CandidateNote,
  CompetencySet,
  Evaluation,
  InterviewSession,
  Interviewer,
  InterviewerRole,
  JobPosting,
  PostingCounts,
  PostingSummary,
  PresetQuestion,
  QAItem,
  QuestionSource,
  SchedulableApplication,
  Score,
  Screening,
  SessionBrief,
  SessionDetail,
  SessionInterviewer,
  SessionMode,
  SessionStatus,
  SessionSummary,
  TranscriptSegment,
  UploadResult,
} from '@/api/types'
import { summarizeAiScores } from '@/lib/scoring'
import { addDays, addMinutes, kstDate, kstParts, MINUTE, startOfKstDay, startOfKstWeek } from '@/lib/time'

import { ANSWER_BANK, GENERIC_BANK, type SuggestionSeed } from './data/banks'
import { CANDIDATES, INTERVIEWERS, ME_KEY, pseudonymOf } from './data/people'
import { P1, P2, POSTING_SEEDS } from './data/postings'

export const AI_MODEL = 'claude-opus-5-5'
export const SCORING_PROMPT = 'score-v0.3'
export const FOLLOWUP_PROMPT = 'followup-v0.2'
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
  competencySets: CompetencySet[] = []
  presets = new Map<string, PresetQuestion[]>()
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

  constructor(now = new Date()) {
    this.now = now
    seed(this)
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
  approvedSet(postingId: string): CompetencySet | null {
    const sets = this.competencySets.filter((c) => c.posting_id === postingId && c.approved_at)
    return sets.sort((a, b) => b.version - a.version)[0] ?? null
  }
  latestSet(postingId: string): CompetencySet | null {
    const sets = this.competencySets.filter((c) => c.posting_id === postingId)
    return sets.sort((a, b) => b.version - a.version)[0] ?? null
  }
  aiStatus(sessionId: string): AiScoringStatus {
    const st = this.aiScoring.get(sessionId)
    if (!st) return 'not_started'
    if (st.status === 'running' && Date.now() - st.startedAt >= AI_SCORING_MS) {
      generateAiScores(this, sessionId)
      st.status = 'completed'
      const s = this.session(sessionId)
      this.log({ actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sessionId, model: AI_MODEL, prompt_version: SCORING_PROMPT, details: { application_id: s?.application_id } })
    }
    return st.status
  }
  isEvaluated(sessionId: string): boolean {
    if (this.aiStatus(sessionId) !== 'completed') return false
    return this.panelOf(sessionId).every((p) => this.submittedAt.has(`${sessionId}:${p.interviewer_id}`))
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

  /** Next answer from the generic pool for a posting (direct input, follow-ups of follow-ups). */
  nextGenericAnswer(postingKey: 'P1' | 'P2'): string {
    const n = this.genericCursor.get(`a:${postingKey}`) ?? 0
    this.genericCursor.set(`a:${postingKey}`, n + 1)
    const pool = GENERIC_BANK[postingKey]!.answers
    return pool[n % pool.length]!
  }

  // ----- views -----------------------------------------------------------------------------------

  counts(postingId: string): PostingCounts {
    const apps = this.applications.filter((a) => a.posting_id === postingId && !a.deleted_at)
    const c: PostingCounts = { applications: apps.length, passed: 0, hold: 0, rejected: 0, interviewing: 0, interviewed: 0, evaluated: 0 }
    for (const a of apps) {
      const s = this.screeningOf(a.id)
      if (s) c[s.status] += 1
      const stage = this.stage(a.id)
      if (stage === 'interview_scheduled' || stage === 'interviewing') c.interviewing += 1
      if (stage === 'interviewed' || stage === 'evaluated') c.interviewed += 1
      if (stage === 'evaluated') c.evaluated += 1
    }
    return c
  }

  stage(applicationId: string): ApplicationStage {
    const sessions = this.sessionsOf(applicationId).filter((s) => s.status !== 'cancelled')
    if (sessions.some((s) => s.status === 'in_progress')) return 'interviewing'
    if (sessions.some((s) => s.status === 'scheduled')) return 'interview_scheduled'
    const done = sessions.filter((s) => s.status === 'completed')
    if (done.length === 0) return 'screening'
    return done.every((s) => this.isEvaluated(s.id)) ? 'evaluated' : 'interviewed'
  }

  postingSummary(p: JobPosting): PostingSummary {
    const { jd_text: _jd, ...rest } = p
    const brief = (c: CompetencySet | null) => (c ? { id: c.id, version: c.version, approved_at: c.approved_at } : null)
    return { ...rest, counts: this.counts(p.id), latest_competency_set: brief(this.latestSet(p.id)), approved_competency_set: brief(this.approvedSet(p.id)) }
  }

  applicationRows(postingId: string): ApplicationRow[] {
    return this.applications
      .filter((a) => a.posting_id === postingId && !a.deleted_at)
      .map((a) => {
        const cand = this.candidate(a.candidate_id)!
        return {
          application_id: a.id,
          candidate: { id: cand.id, pseudonym: cand.pseudonym },
          screening: this.screeningOf(a.id),
          years_experience: a.profile?.years_experience ?? null,
          top_skills: a.profile?.skills.slice(0, 3) ?? [],
          stage: this.stage(a.id),
          created_at: a.created_at,
        }
      })
  }

  brief(s: InterviewSession): SessionBrief {
    return { id: s.id, status: s.status, mode: s.mode, scheduled_at: s.scheduled_at, ended_at: s.ended_at }
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
      sessions: this.sessionsOf(a.id).map((s) => this.brief(s)),
      document: this.documents.get(a.id) ?? null,
    }
  }

  /** Mock upload: a new candidate with a generic profile, screened as hold (people decide). */
  addUpload(postingId: string, filename: string): UploadResult {
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
    const document = { format: ext === 'htm' ? 'html' : ext, blocks: 6, hidden_blocks: 0, images_dropped: 0, replacements: 4 }
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

  schedulable(): SchedulableApplication[] {
    return this.applications
      .filter((a) => this.screeningOf(a.id)?.status === 'passed')
      .filter((a) => !this.sessionsOf(a.id).some((s) => s.status === 'scheduled' || s.status === 'in_progress' || s.status === 'completed'))
      .map((a) => {
        const c = this.candidate(a.candidate_id)!
        const p = this.posting(a.posting_id)!
        return {
          application_id: a.id,
          candidate: { id: c.id, pseudonym: c.pseudonym },
          posting: { id: p.id, title: p.title, job_family: p.job_family },
          fit_score: this.screeningOf(a.id)!.fit_score,
        }
      })
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
    return {
      session: s,
      posting: { id: p.id, title: p.title, job_family: p.job_family },
      card: {
        candidate: { id: c.id, pseudonym: c.pseudonym, consent_recording: c.consent_recording, consent_at: c.consent_at },
        profile: a.profile,
        screening: sc ? { fit_score: sc.fit_score, status: sc.status, rationale: sc.rationale } : null,
        previous_sessions: this.sessionsOf(a.id)
          .filter((x) => x.id !== s.id && x.status === 'completed')
          .map((x) => this.brief(x)),
      },
      interviewers: this.panelView(s.id),
      competency_set: this.approvedSet(p.id),
      preset_questions: this.presets.get(p.id) ?? [],
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
      competency_set: this.approvedSet(p.id),
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
      case 'competency_set': {
        const cs = this.competencySets.find((x) => x.id === e.target_id)
        const p = cs && this.posting(cs.posting_id)
        return p && cs ? `${p.title} v${cs.version}` : null
      }
      case 'job_posting':
        return this.posting(e.target_id)?.title ?? null
      default:
        return null
    }
  }
}

// ---------------------------------------------------------------------------------------------
// AI scoring (mock): one score per answered QA item, evidence quoted from the answer.
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

function seed(db: MockDb) {
  const now = db.now
  const daysAgo = (d: number, h = 10, m = 0) => {
    const p = kstParts(addDays(now, -d))
    return kstDate(p.year, p.month, p.day, h, m)
  }

  for (const i of INTERVIEWERS) {
    db.interviewers.push({ id: i.id, employee_no: i.employee_no, name: i.name, job_family: i.job_family, department: i.department, created_at: iso(daysAgo(120)) })
  }

  for (const p of POSTING_SEEDS) {
    db.postings.push({ id: p.id, title: p.title, job_family: p.job_family, jd_text: p.jd_text, status: p.status, created_at: iso(daysAgo(p.createdDaysAgo, 9)) })
    for (const s of p.sets) {
      const created = daysAgo(s.daysAgo, 11)
      db.competencySets.push({
        id: `e5f6a7b8-0000-4000-9000-${p.id.slice(-4)}0000000${s.version}`,
        posting_id: p.id,
        version: s.version,
        competencies: structuredClone(s.competencies),
        approved_by: s.approvedBy ? interviewerId(s.approvedBy) : null,
        approved_at: s.approvedBy ? iso(addMinutes(created, 180)) : null,
        created_at: iso(created),
      })
    }
    db.presets.set(p.id, p.presets)
  }

  for (const c of CANDIDATES) {
    const posting = c.posting === 'P1' ? P1 : P2
    const applied = daysAgo(c.appliedDaysAgo, 9 + (c.n % 8), (c.n * 7) % 60)
    db.candidates.push({ id: candidateIdOf(c.n), pseudonym: pseudonymOf(c.n), consent_recording: false, consent_at: null, deleted_at: null, created_at: iso(applied) })
    db.applications.push({ id: applicationIdOf(c.n), candidate_id: candidateIdOf(c.n), posting_id: posting.id, profile: c.profile, deleted_at: null, created_at: iso(applied) })
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
}

function seedSessions(db: MockDb, now: Date, daysAgo: (d: number, h?: number, m?: number) => Date) {
  const sessionIds: Record<string, string> = {}
  const make = (key: string, s: SessionSeed) => {
    const id = `0a1b2c3d-0000-4000-9000-${key.padEnd(12, '0')}`
    sessionIds[key] = id
    db.sessions.push({
      id,
      application_id: applicationIdOf(s.n),
      mode: s.mode,
      status: s.status,
      scheduled_at: iso(s.scheduled),
      started_at: s.started ? iso(s.started) : null,
      ended_at: s.ended ? iso(s.ended) : null,
      has_recording: s.status === 'completed' || s.status === 'in_progress',
      created_at: iso(addDays(s.scheduled, -4)),
    })
    for (const [k, role] of s.panel) db.sessionInterviewers.push({ session_id: id, interviewer_id: interviewerId(k), role })
    if (s.status === 'completed' || s.status === 'in_progress') {
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

  // In progress: CAND-0007
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
  make('s3', { n: 9, mode: 'remote', status: 'scheduled', scheduled: tomorrow10, panel: [['park', 'lead'], ['kim', 'panel']] })
  const c1 = make('c1', { n: 3, mode: 'remote', status: 'completed', scheduled: daysAgo(1, 14), started: daysAgo(1, 14, 2), ended: daysAgo(1, 14, 48), panel: [['kim', 'lead'], ['park', 'panel']] })
  const c2 = make('c2', { n: 5, mode: 'onsite', status: 'completed', scheduled: daysAgo(2, 10), started: daysAgo(2, 10, 1), ended: daysAgo(2, 10, 52), panel: [['park', 'lead'], ['kim', 'panel']] })
  const c3 = make('c3', { n: 14, mode: 'remote', status: 'completed', scheduled: daysAgo(1, 15, 30), started: daysAgo(1, 15, 31), ended: daysAgo(1, 16, 20), panel: [['lee', 'lead'], ['jung', 'panel']] })
  const c4 = make('c4', { n: 16, mode: 'remote', status: 'completed', scheduled: addMinutes(now, -125), started: addMinutes(now, -124), ended: addMinutes(now, -75), panel: [['jung', 'lead'], ['lee', 'panel']] })

  const preset = (postingKey: 'P1' | 'P2', pid: string) => {
    const posting = postingKey === 'P1' ? P1 : P2
    return posting.presets.find((q) => q.id === pid)!
  }

  /** Ask a preset and (optionally) one of its suggestions, with answers. */
  const askPreset = (sessionId: string, postingKey: 'P1' | 'P2', pid: string, at: Date, answered: boolean) => {
    const q = preset(postingKey, pid)
    const bank = ANSWER_BANK[pid]!
    return db.addQA(sessionId, q.question, 'preset', { postingKey, presetId: pid, competency: q.competency, answer: bank.answer, suggestions: bank.suggestions }, at, answered ? addMinutes(at, 2) : null)
  }
  const askSuggestion = (sessionId: string, postingKey: 'P1' | 'P2', pid: string, idx: number, at: Date) => {
    const sug = ANSWER_BANK[pid]!.suggestions[idx]!
    const generic = GENERIC_BANK[postingKey]!.suggestions
    return db.addQA(sessionId, sug.question, 'ai_suggested', { postingKey, presetId: null, competency: sug.competency, answer: sug.answer, suggestions: generic }, at, addMinutes(at, 2))
  }

  // Live session history: Q1 (answered), follow-up (answered), Q3 asked a moment ago (answer streams on connect).
  const l1 = askPreset(live, 'P1', 'p1-q1', addMinutes(now, -12), true)
  const l2 = askSuggestion(live, 'P1', 'p1-q1', 0, addMinutes(now, -8))
  const l3 = askPreset(live, 'P1', 'p1-q3', addMinutes(now, -1), false)
  const segs: TranscriptSegment[] = []
  let t = 60_000
  const push = (qa: QAItem, speaker: 'interviewer' | 'candidate', text: string) => {
    const dur = Math.max(1500, text.length * 110)
    segs.push({ segment_id: newId(), qa_item_id: qa.id, speaker, text, is_final: true, start_ms: t, end_ms: t + dur })
    t += dur + 600
  }
  for (const qa of [l1, l2]) {
    push(qa, 'interviewer', qa.question)
    for (const s of splitSentences(qa.answer_deidentified ?? '')) push(qa, 'candidate', s)
  }
  t = 12 * 60_000
  push(l3, 'interviewer', l3.question)
  db.transcripts.set(live, segs)
  db.notes.push({ id: newId(), session_id: live, author_id: interviewerId('kim'), content: '엣지 링 사례 설명이 구체적. 비용 판단 근거까지 스스로 설명함.', created_at: iso(addMinutes(now, -6)) })

  // Completed sessions
  const c1qa = [
    askPreset(c1, 'P1', 'p1-q2', daysAgo(1, 14, 4), true),
    askPreset(c1, 'P1', 'p1-q5', daysAgo(1, 14, 12), true),
    askSuggestion(c1, 'P1', 'p1-q5', 0, daysAgo(1, 14, 18)),
    askPreset(c1, 'P1', 'p1-q7', daysAgo(1, 14, 25), true),
    askPreset(c1, 'P1', 'p1-q4', daysAgo(1, 14, 34), true),
  ]
  const c2qa = [
    askPreset(c2, 'P1', 'p1-q1', daysAgo(2, 10, 3), true),
    askPreset(c2, 'P1', 'p1-q3', daysAgo(2, 10, 14), true),
    askSuggestion(c2, 'P1', 'p1-q3', 1, daysAgo(2, 10, 22)),
    askPreset(c2, 'P1', 'p1-q8', daysAgo(2, 10, 30), true),
    askPreset(c2, 'P1', 'p1-q6', daysAgo(2, 10, 40), true),
  ]
  const c3qa = [
    askPreset(c3, 'P2', 'p2-q3', daysAgo(1, 15, 33), true),
    askSuggestion(c3, 'P2', 'p2-q3', 0, daysAgo(1, 15, 41)),
    askPreset(c3, 'P2', 'p2-q4', daysAgo(1, 15, 48), true),
    askPreset(c3, 'P2', 'p2-q6', daysAgo(1, 15, 58), true),
    askPreset(c3, 'P2', 'p2-q1', daysAgo(1, 16, 8), true),
  ]
  askPreset(c4, 'P2', 'p2-q1', addMinutes(now, -120), true)
  askPreset(c4, 'P2', 'p2-q2', addMinutes(now, -108), true)
  askPreset(c4, 'P2', 'p2-q5', addMinutes(now, -95), true)

  for (const id of [c1, c2, c3]) {
    db.aiScoring.set(id, { status: 'completed', startedAt: 0 })
    generateAiScores(db, id)
  }
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
  void [c1qa, c2qa, c3qa]
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
  const p1v2 = db.competencySets.find((c) => c.posting_id === P1.id && c.version === 2)!
  const p2v1 = db.competencySets.find((c) => c.posting_id === P2.id && c.version === 1)!
  const entries: Parameters<MockDb['log']>[0][] = [
    { occurred_at: iso(addDays(now, -3)), actor_type: 'ai', action: 'screening.batch_completed', target_type: 'job_posting', target_id: P2.id, model: SCREENING_MODEL, details: { count: 9 } },
    { occurred_at: iso(addDays(now, -2)), actor_type: 'ai', action: 'competency_set.generated', target_type: 'competency_set', target_id: p1v2.id, model: AI_MODEL },
    { occurred_at: iso(addMinutes(addDays(now, -2), 50)), actor_type: 'user', actor_id: interviewerId('park'), action: 'score.interviewer_submitted', target_type: 'interview_session', target_id: sid('c2') },
    { occurred_at: iso(addDays(now, -1)), actor_type: 'user', actor_id: interviewerId('lee'), action: 'competency_set.approved', target_type: 'competency_set', target_id: p2v1.id },
    { occurred_at: iso(addMinutes(addDays(now, -1), 30)), actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sid('c1'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(addDays(now, -1), 70)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'score.interviewer_submitted', target_type: 'interview_session', target_id: sid('c1') },
    { occurred_at: iso(addMinutes(addDays(now, -1), 95)), actor_type: 'ai', action: 'score.ai_completed', target_type: 'interview_session', target_id: sid('c3'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(now, -180)), actor_type: 'user', actor_id: interviewerId('park'), action: 'screening.status_changed', target_type: 'screening', target_id: scr(13), details: { from: 'rejected', to: 'hold' } },
    { occurred_at: iso(addMinutes(now, -75)), actor_type: 'user', actor_id: interviewerId('jung'), action: 'session.completed', target_type: 'interview_session', target_id: sid('c4') },
    { occurred_at: iso(addMinutes(now, -75)), actor_type: 'ai', action: 'score.ai_started', target_type: 'interview_session', target_id: sid('c4'), model: AI_MODEL },
    { occurred_at: iso(addMinutes(now, -14)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'consent.recorded', target_type: 'interview_session', target_id: sid('live'), details: { consent_recording: true } },
    { occurred_at: iso(addMinutes(now, -13)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'session.started', target_type: 'interview_session', target_id: sid('live') },
    { occurred_at: iso(addMinutes(now, -8)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'qa.created', target_type: 'interview_session', target_id: sid('live'), details: { question_source: 'ai_suggested' } },
    { occurred_at: iso(addMinutes(now, -1)), actor_type: 'user', actor_id: interviewerId('kim'), action: 'qa.created', target_type: 'interview_session', target_id: sid('live'), details: { question_source: 'preset' } },
  ]
  for (const e of entries) db.log(e)
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
