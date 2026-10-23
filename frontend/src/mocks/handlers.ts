/**
 * MSW request handlers: the mock implementation of docs/api-contract.md.
 */
import { delay, http, HttpResponse } from 'msw'

import type {
  Competency,
  ConsentRequest,
  CreateAvailabilityRequest,
  CreateNoteRequest,
  CreateQARequest,
  CreateSessionRequest,
  FollowUpRequest,
  QAItem,
  ScheduleSuggestionRequest,
  ScreeningStatus,
  SessionStatus,
  SubmitInterviewerScoresRequest,
  UpdateQARequest,
} from '@/api/types'
import { BARS_LEVELS, SCREENING_STATUSES } from '@/api/types'
import { availabilityByInterviewer, suggestSlots } from '@/lib/schedule'
import { isSameKstDay } from '@/lib/time'

import { ANSWER_BANK, GENERIC_BANK } from './data/banks'
import { P1, P2 } from './data/postings'
import { AI_MODEL, getDb, newId, SCREENING_MODEL, type MockDb, type QAMeta } from './db'
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

export const handlers = [
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
    return HttpResponse.json({ ...p, counts: db.counts(p.id) })
  }),

  http.get(`${API}/postings/:id/competency-sets`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.posting(String(params.id))) return notFound('공고')
    return HttpResponse.json(db.competencySets.filter((c) => c.posting_id === params.id).sort((a, b) => a.version - b.version))
  }),

  http.post(`${API}/postings/:id/competency-sets`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    const posting = db.posting(String(params.id))
    if (!posting) return notFound('공고')
    const body = (await request.json()) as { competencies: unknown }
    if (!validCompetencies(body.competencies)) return invalid('competencies', '역량마다 이름, 설명, 1~5점 기준이 필요합니다.')
    const version = (db.latestSet(posting.id)?.version ?? 0) + 1
    const set = { id: newId(), posting_id: posting.id, version, competencies: body.competencies, approved_by: null, approved_at: null, created_at: new Date().toISOString() }
    db.competencySets.push(set)
    db.log({ actor_type: 'user', action: 'competency_set.created', target_type: 'competency_set', target_id: set.id })
    return HttpResponse.json(set, { status: 201 })
  }),

  http.post(`${API}/postings/:id/competency-sets/generate`, async ({ params }) => {
    await delay(1800 * mockConfig.speed)
    const db = getDb()
    const posting = db.posting(String(params.id))
    if (!posting) return notFound('공고')
    const base = db.latestSet(posting.id)
    const competencies: Competency[] = structuredClone(base?.competencies ?? [])
    if (!competencies.some((c) => c.name === '주도성')) {
      competencies.push({
        name: '주도성',
        description: '맡은 범위를 넘어서는 문제를 스스로 정의하고 끝까지 해결한다.',
        bars: {
          '1': '지시받은 일만 수행한다.',
          '2': '문제를 발견하면 보고한다.',
          '3': '문제를 스스로 정의하고 해결안을 실행했다.',
          '4': '여러 팀이 걸친 문제를 주도해 해결했다.',
          '5': '조직의 우선순위를 바꾸는 개선을 주도했다.',
        },
      })
    }
    const set = { id: newId(), posting_id: posting.id, version: (base?.version ?? 0) + 1, competencies, approved_by: null, approved_at: null, created_at: new Date().toISOString() }
    db.competencySets.push(set)
    db.log({ actor_type: 'ai', action: 'competency_set.generated', target_type: 'competency_set', target_id: set.id, model: AI_MODEL, prompt_version: 'competency-v0.2' })
    return HttpResponse.json(set, { status: 201 })
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
    set.approved_by = db.me.id
    set.approved_at = new Date().toISOString()
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

  http.get(`${API}/applications/schedulable`, async () => {
    await latency()
    return HttpResponse.json(getDb().schedulable())
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
    if (db.sessionsOf(app.id).some((s) => s.status === 'scheduled' || s.status === 'in_progress')) return conflict('이미 예정된 면접이 있습니다.')
    const session = {
      id: newId(),
      application_id: app.id,
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
    db.log({ actor_type: 'user', action: 'session.scheduled', target_type: 'interview_session', target_id: session.id, details: { scheduled_at: body.scheduled_at } })
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
    if (body.question_source === 'preset' && body.preset_question_id && ANSWER_BANK[body.preset_question_id]) {
      const posting = postingKey === 'P1' ? P1 : P2
      const preset = posting.presets.find((q) => q.id === body.preset_question_id)
      const bank = ANSWER_BANK[body.preset_question_id]!
      meta = { postingKey, presetId: body.preset_question_id, competency: preset?.competency ?? null, answer: bank.answer, suggestions: bank.suggestions }
    } else if (body.question_source === 'ai_suggested' && body.suggestion) {
      const sug = db.suggestions.get(body.suggestion.suggestion_id)
      if (!sug) return invalid('suggestion', '알 수 없는 제안입니다.')
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
    const set = db.approvedSet(db.application(s.application_id)!.posting_id)
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
