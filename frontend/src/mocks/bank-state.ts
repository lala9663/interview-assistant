/**
 * Mock 질문 은행 and 평점 기준 예시 (api/routes/bank.py), the embedding index status and the follow-up metrics
 * (api/routes/retrieval_admin.py). The seed is frontend/src/mocks/data/question-bank.ts, the same as the
 * backend's. Search here shares two-character pieces between answer and question: no model, just enough to
 * show the flow (the backend searches with the embedding role's model).
 */
import type {
  BankFamily,
  EmbeddingIndexStatus,
  FollowUpMetrics,
  Interviewer,
  QuestionBankItem,
  RubricExample,
  SourceMetrics,
  SuggestionSource,
} from '@/api/types'

import { INTERVIEWERS, ME_KEY } from './data/people'
import { QUESTION_BANK, RUBRIC_EXAMPLES } from './data/question-bank'
import { checkQuestion } from './question-rules'

export const RETRIEVAL_MODEL = 'BAAI/bge-m3'
export const INDEX_KEY = 'BAAI/bge-m3@5617a9f/1024'
const REBUILD_MS = 4000

export const bankId = (key: string) => `9b0c1d2e-0000-4000-9000-${key.replace(/-/g, '').padEnd(12, '0').slice(0, 12)}`

export interface ShownSuggestion {
  batch_id: string
  suggestion_id: string
  source: SuggestionSource
  latency_ms: number
  discarded: boolean
  used: boolean
  edited: boolean
  at: number
}

export interface BankState {
  questions: QuestionBankItem[]
  rubric: RubricExample[]
  /** a rebuild started from 관리자 > 모델 설정 (ms since epoch), null when none runs */
  rebuildStartedAt: number | null
  builtAt: string
  shown: ShownSuggestion[]
}

const person = (key: string) => {
  const p = INTERVIEWERS.find((i) => i.key === key)!
  return { id: p.id, name: p.name }
}

export function createBankState(now: Date): BankState {
  const day = 24 * 3600 * 1000
  const me = person(ME_KEY)
  const questions: QuestionBankItem[] = QUESTION_BANK.map((s) => {
    const created = new Date(now.getTime() - s.daysAgo * day).toISOString()
    const approved = s.status !== 'draft' ? new Date(now.getTime() - s.daysAgo * day + 2 * 3600 * 1000).toISOString() : null
    return {
      id: bankId(s.key),
      job_family: s.job_family,
      competency: s.competency,
      round_position: s.round_position,
      question: s.question,
      intent: s.intent,
      follow_ups: [...s.follow_ups],
      status: s.status,
      flags: checkQuestion(s.question, ...s.follow_ups),
      source: 'seed',
      created_by: person(s.author),
      approved_by: s.status !== 'draft' ? me : null,
      created_at: created,
      updated_at: created,
      approved_at: approved,
      retired_at: s.status === 'retired' ? new Date(now.getTime() - (s.daysAgo - 5) * day).toISOString() : null,
    }
  })
  const rubric: RubricExample[] = RUBRIC_EXAMPLES.map((s) => {
    const created = new Date(now.getTime() - s.daysAgo * day).toISOString()
    return {
      id: bankId(s.key),
      job_family: s.job_family,
      competency: s.competency,
      score: s.score,
      question: s.question,
      answer: s.answer,
      rationale: s.rationale,
      status: s.status,
      source: 'seed',
      created_by: person(s.author),
      approved_by: s.status === 'approved' ? me : null,
      created_at: created,
      updated_at: created,
      approved_at: s.status === 'approved' ? new Date(now.getTime() - s.daysAgo * day + 3600 * 1000).toISOString() : null,
      retired_at: null,
      overlaps: [],
    }
  })
  return { questions, rubric, rebuildStartedAt: null, builtAt: new Date(now.getTime() - 3 * day).toISOString(), shown: [] }
}

export const personOf = (me: Interviewer) => ({ id: me.id, name: me.name })

/** Job families and competencies: those in the bank or rubric, plus the postings' dictionaries. */
export function families(pairs: [string, string][], dictionaries: [string, string[]][]): BankFamily[] {
  const found = new Map<string, Set<string>>()
  for (const [family, competency] of pairs) (found.get(family) ?? found.set(family, new Set()).get(family)!).add(competency)
  for (const [family, names] of dictionaries) {
    const set = found.get(family) ?? found.set(family, new Set()).get(family)!
    for (const n of names) set.add(n)
  }
  return [...found.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([job_family, set]) => ({ job_family, competencies: [...set].sort((a, b) => a.localeCompare(b)) }))
}

// ----- search (mock: shared two-character pieces) -------------------------------------------------

const grams = (text: string) => {
  const squashed = text.replace(/[\s.,?!“”"'()·]/g, '')
  const out = new Set<string>()
  for (let i = 0; i < squashed.length - 1; i++) out.add(squashed.slice(i, i + 2))
  return out
}

export function overlap(a: string, b: string): number {
  const x = grams(a)
  const y = grams(b)
  if (x.size === 0 || y.size === 0) return 0
  let shared = 0
  for (const g of x) if (y.has(g)) shared++
  return shared / Math.sqrt(x.size * y.size)
}

export interface BankMatch {
  item: QuestionBankItem
  text: string
  score: number
}

/** Approved questions (or their follow-up examples) of the job family and competencies closest to the answer. */
export function bankMatches(state: BankState, answer: string, jobFamily: string, competencies: string[], round: number): BankMatch[] {
  const found: BankMatch[] = []
  for (const item of state.questions) {
    if (item.status !== 'approved' || item.job_family !== jobFamily) continue
    if (competencies.length > 0 && !competencies.includes(item.competency)) continue
    if (item.round_position !== null && item.round_position !== round) continue
    const best = [item.question, ...item.follow_ups]
      .map((text) => ({ item, text, score: overlap(answer, text) }))
      .sort((a, b) => b.score - a.score)[0]!
    found.push(best)
  }
  return found.sort((a, b) => b.score - a.score)
}

// ----- embedding index and metrics -------------------------------------------------------------

export function indexStatus(state: BankState, now = Date.now()): EmbeddingIndexStatus {
  const approved = state.questions.filter((q) => q.status === 'approved')
  const counts = {
    question: approved.reduce((n, q) => n + 1 + q.follow_ups.length, 0),
    rubric: state.rubric.filter((r) => r.status === 'approved').length,
    competency_set: 3,
  }
  const total = counts.question + counts.rubric + counts.competency_set
  const building = state.rebuildStartedAt !== null && now - state.rebuildStartedAt < REBUILD_MS
  if (state.rebuildStartedAt !== null && !building) {
    state.builtAt = new Date(state.rebuildStartedAt + REBUILD_MS).toISOString()
    state.rebuildStartedAt = null
  }
  const ready = {
    index_key: INDEX_KEY,
    model: RETRIEVAL_MODEL,
    dimensions: 1024,
    status: (building ? 'building' : 'ready') as 'building' | 'ready',
    total,
    done: building ? Math.min(total, Math.round(((now - state.rebuildStartedAt!) / REBUILD_MS) * total)) : total,
    started_at: building ? new Date(state.rebuildStartedAt!).toISOString() : state.builtAt,
    finished_at: building ? null : state.builtAt,
    error: null,
    serving: true,
  }
  return {
    active_model: RETRIEVAL_MODEL,
    active_index_key: INDEX_KEY,
    serving_index_key: INDEX_KEY,
    counts,
    indexes: [ready],
  }
}

export function metrics(state: BankState, days: number, now = Date.now()): FollowUpMetrics {
  const since = now - days * 24 * 3600 * 1000
  const rows = state.shown.filter((r) => r.at >= since)
  const sources: SourceMetrics[] = (['bank', 'ai'] as const).map((source) => {
    const shown = rows.filter((r) => r.source === source && !r.discarded)
    const used = shown.filter((r) => r.used)
    const first = new Map<string, number>()
    for (const r of shown) first.set(r.batch_id, Math.min(first.get(r.batch_id) ?? r.latency_ms, r.latency_ms))
    const timings = [...first.values()].sort((a, b) => a - b)
    const pick = (q: number) => (timings.length ? timings[Math.min(timings.length - 1, Math.round(q * (timings.length - 1)))]! : null)
    return {
      source,
      shown: shown.length,
      used: used.length,
      edited: used.filter((r) => r.edited).length,
      adoption_rate: shown.length ? Math.round((used.length / shown.length) * 1000) / 1000 : null,
      batches: new Set(shown.map((r) => r.batch_id)).size,
      first_ms_median: pick(0.5),
      first_ms_p90: pick(0.9),
    }
  })
  const dropped = (source: SuggestionSource) => rows.filter((r) => r.source === source && r.discarded).length
  return {
    since: new Date(since).toISOString(),
    days,
    batches: new Set(rows.map((r) => r.batch_id)).size,
    sources,
    duplicates: { bank: dropped('bank'), ai: dropped('ai'), total: dropped('bank') + dropped('ai') },
    retrieval_model: RETRIEVAL_MODEL,
  }
}
