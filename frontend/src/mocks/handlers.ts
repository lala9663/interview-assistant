/**
 * MSW request handlers: the mock implementation of docs/api-contract.md.
 */
import { delay, http, HttpResponse } from 'msw'

import type {
  CheckPoint,
  Competency,
  CompetencySet,
  ConsentRequest,
  CreateAvailabilityRequest,
  CreateCheckPointRequest,
  CreateNoteRequest,
  CreateQARequest,
  CreateRoundRequest,
  CreateSessionRequest,
  DecisionRequest,
  FollowUpRequest,
  InterviewRound,
  PresetQuestion,
  PresetQuestionBody,
  QAItem,
  ScheduleSuggestionRequest,
  ScreeningStatus,
  SessionStatus,
  SubmitInterviewerScoresRequest,
  UpdateQARequest,
  UpdateRoundRequest,
} from '@/api/types'
import { BARS_LEVELS, DECISION_STATUSES, SCREENING_STATUSES, SESSION_MODES } from '@/api/types'
import { availabilityByInterviewer, subtractIntervals, suggestSlots } from '@/lib/schedule'
import { HOUR, isSameKstDay } from '@/lib/time'

import { adminHandlers } from './admin'
import { bankHandlers } from './bank'
import { intakeHandlers } from './intake'
import { ANSWER_BANK, GENERIC_BANK } from './data/banks'
import { AI_MODEL, getDb, newId, SCREENING_MODEL, splitSentences, weight, type MockDb, type QAMeta } from './db'
import { draftPresets, draftRoundCompetencies } from './rounds'
import { followUps, mockConfig, onQuestionAsked, stopStreaming, subscribe } from './live'

const API = '/api'

const latency = () => delay(Math.round((160 + Math.random() * 220) * mockConfig.speed))

const notFound = (what: string) => HttpResponse.json({ detail: `${what}을(를) 찾을 수 없습니다.` }, { status: 404 })
const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 })
const invalid = (field: string, msg: string) =>
  HttpResponse.json({ detail: [{ loc: ['body', field], msg, type: 'value_error' }] }, { status: 422 })

const SSE_HEADERS = { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' }
const encoder = new TextEncoder()
const sseChunk = (e: { event: string; data: unknown }) => encoder.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`)

/** Very small stand-in for the backend de-identifier (manual answers only). */
function mockDeidentify(text: string): string {
  return text
    .replace(/01[016789][-\s]?\d{3,4}[-\s]?\d{4}/g, '[전화-1]')
    .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, '[이메일-1]')
}

/** Close an unanswered question with what the transcript heard so far (new question or session end). */
function closeOpenAnswers(db: MockDb, sessionId: string) {
  for (const q of db.qaOf(sessionId)) {
    if (q.answered_at || !q.asked_at) continue
    const heard = (db.transcripts.get(sessionId) ?? [])
      .filter((seg) => seg.qa_item_id === q.id && seg.speaker === 'candidate')
      .map((seg) => seg.text)
      .join(' ')
    if (heard) {
      q.answer_deidentified = heard
      q.answered_at = new Date().toISOString()
    }
  }
}

function validCompetencies(list: unknown): list is Competency[] {
  return (
    Array.isArray(list) &&
    list.every(
      (c) =>
        c &&
        typeof c.name === 'string' &&
        c.name.trim() !== '' &&
        typeof c.description === 'string' &&
        c.bars &&
        BARS_LEVELS.every((l) => typeof c.bars[l] === 'string'),
    )
  )
}

function sessionOr404(db: MockDb, id: string) {
  return db.session(id) ?? null
}

const MAX_ROUNDS = 6

/** Number rounds 1..n in the given order (labels follow). */
function place(db: MockDb, postingId: string, ordered: InterviewRound[]) {
  ordered.forEach((r, i) => (r.position = i + 1))
  db.relabel(postingId)
}

function roundBody(body: CreateRoundRequest | UpdateRoundRequest, partial: boolean): string | null {
  if ((!partial || body.name !== undefined) && !body.name?.trim()) return '차수 이름을 입력하세요. 예: 직무 면접, 임원 면접'
  const n = body.recommended_interviewers
  if (n !== undefined && (!Number.isInteger(n) || n < 1 || n > 10)) return '권장 면접관 수는 1~10명입니다.'
  if (body.default_mode !== undefined && !SESSION_MODES.includes(body.default_mode)) return '허용되지 않는 값입니다.'
  return null
}

function draftOnly(set: CompetencySet) {
  return set.approved_at ? conflict('확정된 버전의 사전 질문은 바꿀 수 없습니다. 새 버전을 만드세요.') : null
}

function setOfQuestion(db: MockDb, questionId: string): CompetencySet | null {
  for (const [setId, list] of db.presets) if (list.some((q) => q.id === questionId)) return db.competencySets.find((c) => c.id === setId) ?? null
  return null
}

function presetBody(set: CompetencySet, body: PresetQuestionBody) {
  if (!set.competencies.some((c) => c.name === body.competency)) return invalid('competency', `'${body.competency}'은(는) 이 버전의 역량이 아닙니다.`)
  if (!body.question?.trim()) return invalid('question', '질문을 입력하세요.')
  return null
}

/** Text without spaces and punctuation, to spot a question asked again. */
const compact = (s: string) => s.replace(/[\s.,?!·…“”"']+/g, '')
const fragment = (sentence: string, words = 5) => {
  const parts = sentence.replace(/[.?! ]+$/, '').split(/\s+/)
  return parts.slice(0, words).join(' ') + (parts.length > words ? '…' : '')
}

export const handlers = [
  ...adminHandlers,
  ...intakeHandlers,
  ...bankHandlers,
  // ----- me / dashboard / activity ---------------------------------------------------------------
  http.get(`${API}/me`, async () => {
    await latency()
    return HttpResponse.json(getDb().me)
  }),

  http.get(`${API}/dashboard`, async () => {
    await latency()
    const db = getDb()
    const now = new Date()
    const meId = db.me.id
    const summaries = db.sessions.map((s) => db.sessionSummary(s))
    return HttpResponse.json({
      pipeline: db.postings
        .filter((p) => p.status !== 'closed')
        .map((p) => ({ posting: { id: p.id, title: p.title, job_family: p.job_family, status: p.status }, counts: db.counts(p.id) })),
      today_sessions: summaries
        .filter((s) => s.status !== 'cancelled' && s.scheduled_at && isSameKstDay(s.scheduled_at, now))
        .sort((a, b) => (a.scheduled_at ?? '').localeCompare(b.scheduled_at ?? '')),
      pending_my_scores: summaries.filter(
        (s) => s.status === 'completed' && s.interviewers.some((i) => i.interviewer_id === meId) && !s.submitted_interviewer_ids.includes(meId),
      ),
      pending_decisions: db.pendingDecisions(),
      hold_count: db.screenings.filter((s) => s.status === 'hold').length,
    })
  }),

  http.get(`${API}/activity`, async ({ request }) => {
    await latency()
    const limit = Number(new URL(request.url).searchParams.get('limit') ?? 20)
    return HttpResponse.json(getDb().activity(Math.min(Math.max(limit, 1), 100)))
  }),

  // ----- postings & competency dictionary --------------------------------------------------------
  http.get(`${API}/postings`, async () => {
    await latency()
    const db = getDb()
    return HttpResponse.json(db.postings.map((p) => db.postingSummary(p)))
  }),

  http.get(`${API}/postings/:id`, async ({ params }) => {
    await latency()
    const db = getDb()
    const p = db.posting(String(params.id))
    if (!p) return notFound('공고')
    return HttpResponse.json(db.postingDetail(p))
  }),

  http.patch(`${API}/postings/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const p = db.posting(String(params.id))
    if (!p) return notFound('공고')
    const body = (await request.json()) as { site_posting_no?: string | null }
    const next = (body.site_posting_no ?? '').trim() || null
    if (next !== null && !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(next)) return invalid('site_posting_no', '영문·숫자와 . _ : - 만 쓸 수 있습니다 (64자 이하).')
    const other = next ? db.postings.find((x) => x.site_posting_no === next && x.id !== p.id) : undefined
    if (other) return conflict(`공고 번호 ${next}는 이미 '${other.title}' 공고에 연결되어 있습니다.`)
    if (p.site_posting_no !== next) {
      db.log({ actor_type: 'user', action: 'posting.site_linked', target_type: 'job_posting', target_id: p.id, details: { from: p.site_posting_no, to: next } })
      p.site_posting_no = next
    }
    return HttpResponse.json(db.postingDetail(p))
  }),

  http.get(`${API}/postings/:id/competency-sets`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.posting(String(params.id))) return notFound('공고')
    return HttpResponse.json(db.roundsOf(String(params.id)).flatMap((r) => db.setsOf(r.id)))
  }),

  // ----- 전형 (차수) ---------------------------------------------------------------------------------
  http.get(`${API}/postings/:id/rounds`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.posting(String(params.id))) return notFound('공고')
    return HttpResponse.json(db.roundsOf(String(params.id)).map((r) => db.roundSummary(r)))
  }),

  http.post(`${API}/postings/:id/rounds`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const posting = db.posting(String(params.id))
    if (!posting) return notFound('공고')
    const body = (await request.json()) as CreateRoundRequest
    const problem = roundBody(body, false)
    if (problem) return invalid(problem.startsWith('차수') ? 'name' : 'recommended_interviewers', problem)
    const existing = db.roundsOf(posting.id)
    if (existing.length >= MAX_ROUNDS) return conflict(`차수는 ${MAX_ROUNDS}개까지 둘 수 있습니다.`)
    const position = existing.length + 1
    const round: InterviewRound = {
      id: newId(),
      posting_id: posting.id,
      position,
      label: `${position}차`,
      name: body.name.trim(),
      default_mode: body.default_mode ?? 'remote',
      recommended_interviewers: body.recommended_interviewers ?? 2,
      show_previous_scores: body.show_previous_scores ?? false,
      created_at: new Date().toISOString(),
    }
    db.rounds.push(round)
    db.log({ actor_type: 'user', action: 'round.created', target_type: 'interview_round', target_id: round.id, details: { position } })
    return HttpResponse.json(db.roundSummary(round), { status: 201 })
  }),

  http.patch(`${API}/rounds/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const round = db.round(String(params.id))
    if (!round) return notFound('차수')
    const body = (await request.json()) as UpdateRoundRequest
    const problem = roundBody(body, true)
    if (problem) return invalid(problem.startsWith('차수') ? 'name' : 'recommended_interviewers', problem)
    const changed: Record<string, { from: unknown; to: unknown }> = {}
    for (const key of ['name', 'default_mode', 'recommended_interviewers', 'show_previous_scores'] as const) {
      const value = key === 'name' ? body.name?.trim() : body[key]
      if (value !== undefined && value !== round[key]) {
        changed[key] = { from: round[key], to: value }
        ;(round as unknown as Record<string, unknown>)[key] = value
      }
    }
    if (Object.keys(changed).length > 0) db.log({ actor_type: 'user', action: 'round.updated', target_type: 'interview_round', target_id: round.id, details: changed })
    return HttpResponse.json(db.roundSummary(round))
  }),

  http.delete(`${API}/rounds/:id`, async ({ params }) => {
    await latency()
    const db = getDb()
    const round = db.round(String(params.id))
    if (!round) return notFound('차수')
    const all = db.roundsOf(round.posting_id)
    if (all.length === 1) return conflict('공고에는 차수가 하나 이상 있어야 합니다.')
    if (db.roundSummary(round).locked) return conflict(`${round.label}에 면접이나 결정이 있어 지울 수 없습니다.`)
    db.rounds = db.rounds.filter((r) => r.id !== round.id)
    db.competencySets = db.competencySets.filter((c) => c.round_id !== round.id)
    place(db, round.posting_id, all.filter((r) => r.id !== round.id))
    db.log({ actor_type: 'user', action: 'round.deleted', target_type: 'job_posting', target_id: round.posting_id, details: { round_id: round.id, name: round.name } })
    return new HttpResponse(null, { status: 204 })
  }),

  http.put(`${API}/postings/:id/rounds/order`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const posting = db.posting(String(params.id))
    if (!posting) return notFound('공고')
    const { round_ids: ids } = (await request.json()) as { round_ids: string[] }
    const all = db.roundsOf(posting.id)
    if (ids.length !== all.length || new Set(ids).size !== ids.length || !ids.every((id) => all.some((r) => r.id === id))) {
      return invalid('round_ids', '공고의 차수를 모두 한 번씩 보내야 합니다.')
    }
    const ordered = ids.map((id) => db.round(id)!)
    const stuck = ordered.find((r, i) => r.position !== i + 1 && db.roundSummary(r).locked)
    if (stuck) return conflict(`${stuck.label}에 면접이나 결정이 있어 순서를 바꿀 수 없습니다.`)
    if (ordered.some((r, i) => r.position !== i + 1)) {
      place(db, posting.id, ordered)
      db.log({ actor_type: 'user', action: 'round.reordered', target_type: 'job_posting', target_id: posting.id, details: { round_ids: ids } })
    }
    return HttpResponse.json(db.roundsOf(posting.id).map((r) => db.roundSummary(r)))
  }),

  http.get(`${API}/rounds/:id/competency-sets`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.round(String(params.id))) return notFound('차수')
    return HttpResponse.json(db.setsOf(String(params.id)))
  }),

  http.post(`${API}/rounds/:id/competency-sets`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const round = db.round(String(params.id))
    if (!round) return notFound('차수')
    const body = (await request.json()) as { competencies: unknown }
    if (!validCompetencies(body.competencies)) return invalid('competencies', '역량마다 이름, 설명, 1~5점 기준이 필요합니다.')
    const set: CompetencySet = { id: newId(), posting_id: round.posting_id, round_id: round.id, version: (db.latestSet(round.id)?.version ?? 0) + 1, competencies: body.competencies, approved_by: null, approved_at: null, created_at: new Date().toISOString() }
    db.competencySets.push(set)
    // A new draft starts with the approved version's questions for the competencies it keeps.
    const approved = db.approvedSet(round.id)
    const keep = new Set(body.competencies.map((c) => c.name))
    db.presets.set(set.id, approved ? db.presetsOf(approved.id).filter((q) => keep.has(q.competency)).map((q) => ({ ...q, id: newId() })) : [])
    db.log({ actor_type: 'user', action: 'competency_set.created', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(set, { status: 201 })
  }),

  http.post(`${API}/rounds/:id/competency-sets/generate`, async ({ params }) => {
    await delay(1800 * mockConfig.speed)
    const db = getDb()
    const round = db.round(String(params.id))
    if (!round) return notFound('차수')
    const base = db.latestSet(round.id)
    const earlier = db.roundsOf(round.posting_id).filter((r) => r.position < round.position).flatMap((r) => db.approvedSet(r.id)?.competencies.map((c) => c.name) ?? [])
    const competencies = draftRoundCompetencies(base?.competencies ?? [], earlier)
    const set: CompetencySet = { id: newId(), posting_id: round.posting_id, round_id: round.id, version: (base?.version ?? 0) + 1, competencies, approved_by: null, approved_at: null, created_at: new Date().toISOString() }
    db.competencySets.push(set)
    db.presets.set(set.id, [])
    db.log({ actor_type: 'ai', action: 'competency_set.generated', target_type: 'competency_set', target_id: set.id, model: AI_MODEL, prompt_version: 'competency-v0.3' })
    return HttpResponse.json(set, { status: 201 })
  }),

  http.get(`${API}/competency-sets/:id/preset-questions`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.competencySets.some((c) => c.id === params.id)) return notFound('역량 사전')
    return HttpResponse.json(db.presetsOf(String(params.id)))
  }),

  http.post(`${API}/competency-sets/:id/preset-questions`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const set = db.competencySets.find((c) => c.id === params.id)
    if (!set) return notFound('역량 사전')
    const refused = draftOnly(set)
    if (refused) return refused
    const body = (await request.json()) as PresetQuestionBody
    const problem = presetBody(set, body)
    if (problem) return problem
    const question: PresetQuestion = { id: newId(), competency: body.competency, question: body.question.trim(), intent: body.intent?.trim() ?? '', origin: null }
    db.presets.set(set.id, [...db.presetsOf(set.id), question])
    db.log({ actor_type: 'user', action: 'preset_question.created', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(question, { status: 201 })
  }),

  http.post(`${API}/competency-sets/:id/preset-questions/generate`, async ({ params }) => {
    await delay(1400 * mockConfig.speed)
    const db = getDb()
    const set = db.competencySets.find((c) => c.id === params.id)
    if (!set) return notFound('역량 사전')
    const refused = draftOnly(set)
    if (refused) return refused
    const round = db.round(set.round_id)!
    const earlier = db.roundsOf(round.posting_id)
      .filter((r) => r.position < round.position)
      .flatMap((r) => {
        const approved = db.approvedSet(r.id)
        return approved ? db.presetsOf(approved.id).map((q) => q.question) : []
      })
    const existing = db.presetsOf(set.id)
    const added = draftPresets(set.competencies.map((c) => c.name), [...earlier, ...existing.map((q) => q.question)], earlier.length > 0)
    if (added.length === 0) return HttpResponse.json({ detail: '새로 더할 사전 질문을 만들지 못했습니다.' }, { status: 502 })
    db.presets.set(set.id, [...existing, ...added.map((q) => ({ id: newId(), ...q, origin: null }))])
    db.log({ actor_type: 'ai', action: 'preset_question.generated', target_type: 'competency_set', target_id: set.id, model: AI_MODEL, prompt_version: 'preset-v0.1' })
    return HttpResponse.json(db.presetsOf(set.id))
  }),

  http.put(`${API}/preset-questions/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const set = setOfQuestion(db, String(params.id))
    if (!set) return notFound('사전 질문')
    const refused = draftOnly(set)
    if (refused) return refused
    const body = (await request.json()) as PresetQuestionBody
    const problem = presetBody(set, body)
    if (problem) return problem
    const q = db.presetsOf(set.id).find((x) => x.id === params.id)!
    Object.assign(q, { competency: body.competency, question: body.question.trim(), intent: body.intent?.trim() ?? '' })
    db.log({ actor_type: 'user', action: 'preset_question.updated', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(q)
  }),

  http.delete(`${API}/preset-questions/:id`, async ({ params }) => {
    await latency()
    const db = getDb()
    const set = setOfQuestion(db, String(params.id))
    if (!set) return notFound('사전 질문')
    const refused = draftOnly(set)
    if (refused) return refused
    db.presets.set(set.id, db.presetsOf(set.id).filter((q) => q.id !== params.id))
    db.log({ actor_type: 'user', action: 'preset_question.deleted', target_type: 'competency_set', target_id: set.id })
    return new HttpResponse(null, { status: 204 })
  }),

  http.put(`${API}/competency-sets/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const set = db.competencySets.find((c) => c.id === params.id)
    if (!set) return notFound('역량 사전')
    if (set.approved_at) return conflict('확정된 버전은 수정할 수 없습니다. 새 버전을 만드세요.')
    const body = (await request.json()) as { competencies: unknown }
    if (!validCompetencies(body.competencies)) return invalid('competencies', '역량마다 이름, 설명, 1~5점 기준이 필요합니다.')
    set.competencies = body.competencies
    db.log({ actor_type: 'user', action: 'competency_set.updated', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(set)
  }),

  http.post(`${API}/competency-sets/:id/approve`, async ({ params }) => {
    await latency()
    const db = getDb()
    const set = db.competencySets.find((c) => c.id === params.id)
    if (!set) return notFound('역량 사전')
    if (set.approved_at) return conflict('이미 확정된 버전입니다.')
    if (set.competencies.length === 0) return invalid('competencies', '역량이 하나 이상 있어야 확정할 수 있습니다.')
    const previous = db.approvedSet(set.round_id)
    set.approved_by = db.me.id
    set.approved_at = new Date().toISOString()
    // An AI draft has no questions yet: it takes the previous version's for the competencies it keeps.
    if (previous && db.presetsOf(set.id).length === 0) {
      const keep = new Set(set.competencies.map((c) => c.name))
      db.presets.set(set.id, db.presetsOf(previous.id).filter((q) => keep.has(q.competency)).map((q) => ({ ...q, id: newId() })))
    }
    db.log({ actor_type: 'user', action: 'competency_set.approved', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(set)
  }),

  // ----- screening -----------------------------------------------------------------------------------
  http.get(`${API}/postings/:id/applications`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.posting(String(params.id))) return notFound('공고')
    return HttpResponse.json(db.applicationRows(String(params.id)))
  }),

  http.post(`${API}/postings/:id/applications`, async ({ params, request }) => {
    await delay(1600 * mockConfig.speed)
    const db = getDb()
    const posting = db.posting(String(params.id))
    if (!posting) return notFound('공고')
    if (posting.status === 'closed') return conflict('마감된 공고에는 지원서를 올릴 수 없습니다.')
    const form = await request.formData()
    const file = form.get('file')
    if (!(file instanceof File) || file.size === 0) return invalid('file', '빈 파일입니다.')
    if (!String(form.get('name') ?? '').trim()) return invalid('name', '지원자 이름을 입력하세요. 비식별화에만 쓰입니다.')
    const result = db.addUpload(posting.id, file.name)
    db.log({ actor_type: 'ai', action: 'screening.batch_completed', target_type: 'job_posting', target_id: posting.id, model: SCREENING_MODEL, details: { count: 1 } })
    return HttpResponse.json(result, { status: 201 })
  }),

  http.get(`${API}/applications/schedulable`, async ({ request }) => {
    await latency()
    const round = new URL(request.url).searchParams.get('round')
    return HttpResponse.json(getDb().schedulable(round ? Number(round) : undefined))
  }),

  http.get(`${API}/applications/:id/decisions`, async ({ params }) => {
    await latency()
    const detail = getDb().applicationDetail(String(params.id))
    return detail ? HttpResponse.json(detail.decisions) : notFound('지원서')
  }),

  http.get(`${API}/applications/:id`, async ({ params }) => {
    await latency()
    const detail = getDb().applicationDetail(String(params.id))
    return detail ? HttpResponse.json(detail) : notFound('지원서')
  }),

  http.patch(`${API}/screenings/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = db.screenings.find((x) => x.id === params.id)
    if (!s) return notFound('선별 결과')
    const body = (await request.json()) as { status: ScreeningStatus }
    if (!SCREENING_STATUSES.includes(body.status)) return invalid('status', 'passed, hold, rejected 중 하나여야 합니다.')
    const from = s.status
    s.status = body.status
    if (from !== body.status) {
      db.log({ actor_type: 'user', action: 'screening.status_changed', target_type: 'screening', target_id: s.id, details: { from, to: body.status } })
    }
    return HttpResponse.json(s)
  }),

  http.get(`${API}/candidates`, async () => {
    await latency()
    return HttpResponse.json(getDb().candidateIndex())
  }),

  // ----- sessions --------------------------------------------------------------------------------------
  http.get(`${API}/sessions`, async ({ request }) => {
    await latency()
    const db = getDb()
    const status = new URL(request.url).searchParams.get('status') as SessionStatus | null
    const list = db.sessions.filter((s) => !status || s.status === status).map((s) => db.sessionSummary(s))
    list.sort((a, b) => (b.scheduled_at ?? '').localeCompare(a.scheduled_at ?? ''))
    return HttpResponse.json(list)
  }),

  http.post(`${API}/sessions`, async ({ request }) => {
    await latency()
    const db = getDb()
    const body = (await request.json()) as CreateSessionRequest
    const app = db.application(body.application_id)
    if (!app) return notFound('지원서')
    if (!body.interviewers?.length) return invalid('interviewers', '면접관을 한 명 이상 지정하세요.')
    if (body.interviewers.filter((i) => i.role === 'lead').length !== 1) return invalid('interviewers', '주관 면접관은 한 명이어야 합니다.')
    if (app.withdrawn_at) return conflict('지원자가 철회한 지원서라 면접을 잡을 수 없습니다.')
    let round = body.round_id ? db.round(body.round_id) : db.nextRound(app.id)
    if (body.round_id && (!round || round.posting_id !== app.posting_id)) return invalid('round_id', '이 공고의 차수가 아닙니다.')
    if (!round) {
      if (db.sessionsOf(app.id).some((s) => s.status === 'scheduled' || s.status === 'in_progress')) return conflict('이미 예정된 면접이 있습니다.')
      return conflict('면접을 잡을 차수가 없습니다. 서류 통과나 이전 차수 합격이 먼저입니다.')
    }
    round = round!
    const refusal = db.scheduleRefusal(app.id, round)
    if (refusal) return conflict(refusal)
    const session = {
      id: newId(),
      application_id: app.id,
      round_id: round.id,
      mode: body.mode,
      status: 'scheduled' as const,
      scheduled_at: body.scheduled_at,
      started_at: null,
      ended_at: null,
      has_recording: false,
      created_at: new Date().toISOString(),
    }
    db.sessions.push(session)
    for (const i of body.interviewers) db.sessionInterviewers.push({ session_id: session.id, interviewer_id: i.interviewer_id, role: i.role })
    db.log({ actor_type: 'user', action: 'session.scheduled', target_type: 'interview_session', target_id: session.id, details: { scheduled_at: body.scheduled_at, round: round.position } })
    return HttpResponse.json(db.sessionSummary(session), { status: 201 })
  }),

  http.get(`${API}/sessions/:id`, async ({ params }) => {
    await latency()
    const detail = getDb().sessionDetail(String(params.id))
    return detail ? HttpResponse.json(detail) : notFound('면접')
  }),

  http.post(`${API}/sessions/:id/consent`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'scheduled') return conflict('면접 시작 전에만 동의를 기록할 수 있습니다.')
    const body = (await request.json()) as ConsentRequest
    const cand = db.candidate(db.application(s.application_id)!.candidate_id)!
    cand.consent_recording = Boolean(body.consent_recording)
    cand.consent_at = body.consent_recording ? new Date().toISOString() : null
    db.log({ actor_type: 'user', action: 'consent.recorded', target_type: 'interview_session', target_id: s.id, details: { consent_recording: cand.consent_recording } })
    return HttpResponse.json(db.sessionDetail(s.id))
  }),

  http.post(`${API}/sessions/:id/start`, async ({ params }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'scheduled') return conflict('예정된 면접만 시작할 수 있습니다.')
    const cand = db.candidate(db.application(s.application_id)!.candidate_id)!
    s.status = 'in_progress'
    s.started_at = new Date().toISOString()
    s.has_recording = cand.consent_recording
    const approved = db.approvedSet(s.round_id)
    if (approved) db.pinned.set(s.id, approved.id)
    db.log({ actor_type: 'user', action: 'session.started', target_type: 'interview_session', target_id: s.id, details: { recording: s.has_recording } })
    return HttpResponse.json(db.sessionDetail(s.id))
  }),

  http.post(`${API}/sessions/:id/end`, async ({ params }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'in_progress') return conflict('진행 중인 면접만 종료할 수 있습니다.')
    stopStreaming(s.id)
    closeOpenAnswers(db, s.id)
    s.status = 'completed'
    s.ended_at = new Date().toISOString()
    db.aiScoring.set(s.id, { status: 'running', startedAt: Date.now() })
    db.log({ actor_type: 'user', action: 'session.completed', target_type: 'interview_session', target_id: s.id })
    db.log({ actor_type: 'ai', action: 'score.ai_started', target_type: 'interview_session', target_id: s.id, model: AI_MODEL })
    return HttpResponse.json(db.sessionDetail(s.id))
  }),

  http.post(`${API}/sessions/:id/qa-items`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'in_progress') return conflict('진행 중인 면접에서만 질문을 기록할 수 있습니다.')
    const body = (await request.json()) as CreateQARequest
    const question = body.question?.trim()
    if (!question) return invalid('question', '질문을 입력하세요.')
    const postingKey = db.postingKey(db.application(s.application_id)!.posting_id)
    let meta: QAMeta
    const preset = body.question_source === 'preset' && body.preset_question_id ? db.presetById(body.preset_question_id) : undefined
    if (body.question_source === 'preset' && body.preset_question_id) {
      const ours = (db.carryover.get(s.id) ?? []).some((q) => q.id === preset?.id) || db.presetsOf(db.setOfSession(s.id)?.id ?? '').some((q) => q.id === preset?.id)
      if (!preset || !ours) return invalid('preset_question_id', '이 면접의 사전 질문이 아닙니다.')
    }
    const bank = preset ? ANSWER_BANK[preset.id] : undefined
    if (preset && bank) {
      meta = { postingKey, presetId: preset.id, competency: preset.competency, answer: bank.answer, suggestions: bank.suggestions }
    } else if (preset) {
      meta = { postingKey, presetId: preset.id, competency: preset.competency, answer: db.nextGenericAnswer(postingKey), suggestions: null }
    } else if (body.question_source === 'ai_suggested' && body.suggestion) {
      const sug = db.suggestions.get(body.suggestion.suggestion_id)
      if (!sug) return invalid('suggestion', '알 수 없는 제안입니다.')
      const shown = db.bank.shown.find((x) => x.suggestion_id === sug.suggestion_id)
      if (shown) Object.assign(shown, { used: true, edited: body.suggestion.edited })
      meta = { postingKey, presetId: null, competency: sug.competency, answer: sug.answer, suggestions: GENERIC_BANK[postingKey]!.suggestions }
    } else {
      meta = { postingKey, presetId: null, competency: null, answer: db.nextGenericAnswer(postingKey), suggestions: null }
    }
    // A new question closes any answer still streaming.
    stopStreaming(s.id)
    closeOpenAnswers(db, s.id)
    const qa = db.addQA(s.id, question, body.question_source, meta, new Date(), null)
    db.log({
      actor_type: 'user',
      action: 'qa.created',
      target_type: 'interview_session',
      target_id: s.id,
      details: { question_source: body.question_source, ...(body.suggestion ? { suggestion_id: body.suggestion.suggestion_id, edited: body.suggestion.edited } : {}) },
    })
    onQuestionAsked(s.id, qa)
    return HttpResponse.json(qa, { status: 201 })
  }),

  http.patch(`${API}/qa-items/:id`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const qa = db.qaItems.find((q) => q.id === params.id)
    if (!qa) return notFound('질문')
    const body = (await request.json()) as UpdateQARequest
    if (!body.answer_text?.trim()) return invalid('answer_text', '답변을 입력하세요.')
    qa.answer_deidentified = mockDeidentify(body.answer_text.trim())
    qa.answered_at = new Date().toISOString()
    const meta = db.qaMeta.get(qa.id)
    if (meta) meta.answer = qa.answer_deidentified
    return HttpResponse.json(qa satisfies QAItem)
  }),

  http.post(`${API}/sessions/:id/carryover-questions`, async ({ params }) => {
    await delay(1400 * mockConfig.speed)
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    const round = db.round(s.round_id)!
    if (round.position === 1) return conflict('1차 면접에는 이어 볼 이전 차수가 없습니다.')
    if (s.status !== 'scheduled' && s.status !== 'in_progress') return conflict('예정되었거나 진행 중인 면접에서만 이어 질문을 만들 수 있습니다.')
    const earlier = db.earlierSessions(s.id).flatMap((e) => db.qaOf(e.id).filter((q) => q.answer_deidentified).map((q) => ({ q, label: db.round(e.round_id)!.label })))
    if (earlier.length === 0) return conflict('마친 이전 차수 면접이 없습니다.')
    const asked = new Set(db.qaOf(s.id).map((q) => q.question))
    const kept = (db.carryover.get(s.id) ?? []).filter((q) => asked.has(q.question))
    const names = db.setOfSession(s.id)?.competencies.map((c) => c.name) ?? ['역량']
    const seen = new Set([...earlier.map((e) => compact(e.q.question)), ...kept.map((q) => compact(q.question))])
    const fresh: PresetQuestion[] = []
    // The thinnest earlier answers first, like the fake model: that is where the round left most to check.
    for (const [i, { q, label }] of [...earlier].sort((a, b) => weight(a.q.answer_deidentified!) - weight(b.q.answer_deidentified!)).slice(0, 3).entries()) {
      const sentences = splitSentences(q.answer_deidentified!)
      const grounding = sentences.reduce((best, x) => (weight(x) < weight(best) ? x : best), sentences[0] ?? '').replace(/\.$/, '')
      const competency = names[i % names.length]!
      const question = `${label}에서 “${fragment(grounding)}”라고 하셨습니다. 그 일에서 본인이 내린 가장 어려운 판단은 무엇이었고, 결과에 대해 어떤 책임을 지셨나요?`
      if (seen.has(compact(question))) continue
      seen.add(compact(question))
      fresh.push({
        id: newId(),
        competency,
        question,
        intent: `${label} 답변 심화`,
        origin: {
          round: db.roundRef(db.round(db.session(q.session_id)!.round_id)!),
          question: q.question,
          grounding,
          rationale: `${label}에서 '${fragment(q.question, 4)}'은(는) 이미 물었고 답변이 결과 위주였습니다. 같은 질문을 반복하지 않고 ${competency} 관점에서 판단과 책임을 더 깊이 확인합니다.`,
          model: AI_MODEL,
        },
      })
    }
    db.carryover.set(s.id, [...kept, ...fresh])
    db.log({ actor_type: 'ai', action: 'carryover.generated', target_type: 'interview_session', target_id: s.id, model: AI_MODEL, prompt_version: 'carryover-v0.1', details: { earlier_round_answers: earlier.length } })
    return HttpResponse.json(db.sessionDetail(s.id))
  }),

  http.post(`${API}/sessions/:id/notes`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    const body = (await request.json()) as CreateNoteRequest
    if (!body.content?.trim()) return invalid('content', '메모를 입력하세요.')
    const note = { id: newId(), session_id: s.id, author_id: db.me.id, content: body.content.trim(), created_at: new Date().toISOString() }
    db.notes.push(note)
    return HttpResponse.json(note, { status: 201 })
  }),

  // The microphone needs the real backend (VAD, STT, the WebSocket): the mock API says so with a code.
  http.post(`${API}/sessions/:id/audio/chunks`, () =>
    HttpResponse.json({ detail: { code: 'MOCK-API', message: '모의 API 모드에서는 마이크를 쓸 수 없습니다. 백엔드 연결 모드(npm run dev:api)에서 쓰세요.' } }, { status: 409 }),
  ),
  http.delete(`${API}/sessions/:id/audio/chunks`, () => new HttpResponse(null, { status: 204 })),
  http.post(`${API}/sessions/:id/live/role`, () => conflict('마이크가 연결되어 있지 않습니다.')),
  http.get(`${API}/live/audio-samples`, () => HttpResponse.json([])),

  http.get(`${API}/sessions/:id/transcript`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.session(String(params.id))) return notFound('면접')
    return HttpResponse.json({ segments: db.transcripts.get(String(params.id)) ?? [] })
  }),

  http.get(`${API}/sessions/:id/transcript/stream`, ({ params, request }) => {
    const db = getDb()
    const id = String(params.id)
    if (!db.session(id)) return notFound('면접')
    let unsubscribe = () => {}
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        let closed = false
        const close = () => {
          if (closed) return
          closed = true
          unsubscribe()
          try {
            controller.close()
          } catch {
            // already closed
          }
        }
        unsubscribe = subscribe(id, (e) => {
          if (closed) return
          try {
            controller.enqueue(sseChunk(e))
          } catch {
            close()
          }
        })
        request.signal.addEventListener('abort', close, { once: true })
      },
      cancel() {
        unsubscribe()
      },
    })
    return new HttpResponse(stream, { headers: SSE_HEADERS })
  }),

  http.post(`${API}/sessions/:id/follow-ups`, async ({ params, request }) => {
    const db = getDb()
    const id = String(params.id)
    if (!db.session(id)) return notFound('면접')
    const body = (await request.json()) as FollowUpRequest
    const gen = followUps(id, body.qa_item_id)
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const { value, done } = await gen.next()
          if (done) controller.close()
          else controller.enqueue(sseChunk(value))
        } catch {
          controller.close()
        }
      },
      cancel() {
        void gen.return(undefined)
      },
    })
    request.signal.addEventListener('abort', () => void gen.return(undefined), { once: true })
    return new HttpResponse(stream, { headers: SSE_HEADERS })
  }),

  // ----- evaluation --------------------------------------------------------------------------------
  http.get(`${API}/sessions/:id/evaluation`, async ({ params }) => {
    await latency()
    const ev = getDb().evaluation(String(params.id))
    return ev ? HttpResponse.json(ev) : notFound('면접')
  }),

  http.put(`${API}/sessions/:id/scores/:interviewerId`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'completed') return conflict('종료된 면접만 평가할 수 있습니다.')
    const interviewerId = String(params.interviewerId)
    if (!db.panelOf(s.id).some((p) => p.interviewer_id === interviewerId)) return conflict('이 면접의 면접관이 아닙니다.')
    const body = (await request.json()) as SubmitInterviewerScoresRequest
    const set = db.setOfSession(s.id)
    const names = set?.competencies.map((c) => c.name) ?? []
    for (const name of names) {
      const row = body.scores.find((x) => x.competency === name)
      if (!row) return invalid('scores', `'${name}' 점수가 없습니다.`)
      if (!Number.isInteger(row.score) || row.score < 1 || row.score > 5) return invalid('scores', '점수는 1~5 정수여야 합니다.')
    }
    // Interviewer scores are per session and competency (qa_item_id null); a resubmission replaces them.
    db.scores = db.scores.filter((x) => !(x.evaluator_type === 'interviewer' && x.evaluator_id === interviewerId && db.scoreSession.get(x.id) === s.id))
    const now = new Date().toISOString()
    for (const row of body.scores) {
      const id = newId()
      db.scoreSession.set(id, s.id)
      db.scores.push({
        id,
        qa_item_id: null,
        competency: row.competency,
        score: row.score,
        evidence: row.comment.trim() || null,
        confidence: null,
        evaluator_type: 'interviewer',
        evaluator_id: interviewerId,
        model: null,
        prompt_version: null,
        created_at: now,
      })
    }
    db.submittedAt.set(`${s.id}:${interviewerId}`, now)
    db.log({ actor_type: 'user', actor_id: interviewerId, action: 'score.interviewer_submitted', target_type: 'interview_session', target_id: s.id })
    return HttpResponse.json(db.evaluation(s.id))
  }),

  http.post(`${API}/sessions/:id/decision`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (!db.me.is_admin && !db.panelOf(s.id).some((p) => p.interviewer_id === db.me.id)) {
      return HttpResponse.json({ detail: '이 면접의 면접관이나 관리자만 결정할 수 있습니다.' }, { status: 403 })
    }
    const refusal = db.decisionRefusal(s.id)
    if (refusal) return conflict(refusal)
    const body = (await request.json()) as DecisionRequest
    if (!DECISION_STATUSES.includes(body.decision)) return invalid('decision', '허용되지 않는 값입니다.')
    const reason = body.reason?.trim()
    if (!reason) return invalid('reason', '결정 사유를 입력하세요.')
    if (reason.length > 1000) return invalid('reason', '결정 사유는 1000자까지 쓸 수 있습니다.')
    const current = db.currentDecision(s.application_id, s.round_id)
    const row = db.decide(s.id, body.decision, mockDeidentify(reason), db.me.id)
    const round = db.round(s.round_id)!
    const details = { round: round.position, revision: row.revision, final: body.decision === 'passed' && db.isLast(round) }
    db.log(
      current
        ? { actor_type: 'user', action: 'round.decision_changed', target_type: 'application', target_id: s.application_id, details: { from: current.decision, to: body.decision, ...details } }
        : { actor_type: 'user', action: 'round.decided', target_type: 'application', target_id: s.application_id, details: { decision: body.decision, ...details } },
    )
    return HttpResponse.json(db.evaluation(s.id))
  }),

  http.post(`${API}/sessions/:id/check-points`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const s = sessionOr404(db, String(params.id))
    if (!s) return notFound('면접')
    if (s.status !== 'completed') return conflict('종료된 면접에만 확인할 점을 남길 수 있습니다.')
    const body = (await request.json()) as CreateCheckPointRequest
    if (!body.text?.trim()) return invalid('text', '확인할 점을 입력하세요.')
    if (body.competency && !db.setOfSession(s.id)?.competencies.some((c) => c.name === body.competency)) {
      return invalid('competency', `'${body.competency}'은(는) 이 면접의 역량이 아닙니다.`)
    }
    const point: CheckPoint = {
      id: newId(),
      session_id: s.id,
      source: 'interviewer',
      competency: body.competency ?? null,
      text: mockDeidentify(body.text.trim()),
      evidence: null,
      qa_item_id: null,
      author_id: db.me.id,
      author_name: db.me.name,
      model: null,
      created_at: new Date().toISOString(),
    }
    db.checkPoints.push(point)
    db.log({ actor_type: 'user', action: 'check_point.created', target_type: 'interview_session', target_id: s.id })
    return HttpResponse.json(point, { status: 201 })
  }),

  http.delete(`${API}/check-points/:id`, async ({ params }) => {
    await latency()
    const db = getDb()
    const point = db.checkPoints.find((p) => p.id === params.id)
    if (!point) return notFound('확인할 점')
    if (point.source !== 'interviewer' || point.author_id !== db.me.id) {
      return HttpResponse.json({ detail: '직접 남긴 확인할 점만 지울 수 있습니다.' }, { status: 403 })
    }
    db.checkPoints = db.checkPoints.filter((p) => p.id !== point.id)
    return new HttpResponse(null, { status: 204 })
  }),

  // ----- schedule ------------------------------------------------------------------------------------
  http.get(`${API}/interviewers`, async () => {
    await latency()
    return HttpResponse.json(getDb().interviewers)
  }),

  http.get(`${API}/availabilities`, async ({ request }) => {
    await latency()
    const url = new URL(request.url)
    const from = url.searchParams.get('from')
    const to = url.searchParams.get('to')
    const list = getDb().availabilities.filter((a) => (!from || a.end_at > from) && (!to || a.start_at < to))
    return HttpResponse.json(list)
  }),

  http.post(`${API}/availabilities`, async ({ request }) => {
    await latency()
    const db = getDb()
    const body = (await request.json()) as CreateAvailabilityRequest
    if (!db.interviewer(body.interviewer_id)) return notFound('면접관')
    if (!(new Date(body.end_at) > new Date(body.start_at))) return invalid('end_at', '종료 시각은 시작 시각보다 늦어야 합니다.')
    const a = { id: newId(), interviewer_id: body.interviewer_id, start_at: body.start_at, end_at: body.end_at, source: 'manual' as const, created_at: new Date().toISOString() }
    db.availabilities.push(a)
    return HttpResponse.json(a, { status: 201 })
  }),

  http.delete(`${API}/availabilities/:id`, async ({ params }) => {
    await latency()
    const db = getDb()
    const before = db.availabilities.length
    db.availabilities = db.availabilities.filter((a) => a.id !== params.id)
    if (db.availabilities.length === before) return notFound('가용 시간')
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API}/schedule/suggestions`, async ({ request }) => {
    await latency()
    const db = getDb()
    const body = (await request.json()) as ScheduleSuggestionRequest
    if (!body.interviewer_ids?.length) return invalid('interviewer_ids', '면접관을 한 명 이상 선택하세요.')
    const by = availabilityByInterviewer(db.availabilities)
    // Like the server, a booked interview takes an hour (BOOKED_MINUTES) of its panel's free time.
    for (const s of db.sessions) {
      if ((s.status !== 'scheduled' && s.status !== 'in_progress') || !s.scheduled_at) continue
      const start = new Date(s.scheduled_at).getTime()
      for (const p of db.panelOf(s.id)) by.set(p.interviewer_id, subtractIntervals(by.get(p.interviewer_id) ?? [], [{ start, end: start + HOUR }]))
    }
    const from = Math.max(new Date(body.from).getTime(), Date.now())
    return HttpResponse.json(
      suggestSlots(by, body.interviewer_ids, body.duration_minutes, {
        minCount: body.min_interviewers ?? body.interviewer_ids.length,
        from,
        to: new Date(body.to).getTime(),
        limit: 8,
      }),
    )
  }),
]
