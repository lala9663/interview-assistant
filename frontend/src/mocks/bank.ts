/**
 * MSW handlers for 질문 은행, 평점 기준 예시, the embedding index and the follow-up metrics: the same paths,
 * validation messages and status codes as `api/routes/bank.py` and `api/routes/retrieval_admin.py`.
 */
import { delay, http, HttpResponse } from 'msw'

import type { BankQuestionBody, BankStatus, QuestionBankItem, RubricExample, RubricExampleBody } from '@/api/types'

import { families, indexStatus, metrics, overlap, personOf } from './bank-state'
import { getDb, newId, type MockDb } from './db'
import { mockConfig } from './live'
import { checkQuestion } from './question-rules'

const latency = (ms = 160) => delay(Math.round(ms * mockConfig.speed))
const forbidden = () => HttpResponse.json({ detail: '관리자만 쓸 수 있습니다.' }, { status: 403 })
const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 })
const notFound = (what: string) => HttpResponse.json({ detail: `${what}을(를) 찾을 수 없습니다.` }, { status: 404 })
const invalid = (field: string, msg: string) =>
  HttpResponse.json({ detail: [{ loc: ['body', field], msg, type: 'value_error' }] }, { status: 422 })

const squash = (s: string) => s.replace(/\s+/g, ' ').trim()
const now = () => new Date().toISOString()

function dictionaries(db: MockDb): [string, string[]][] {
  return db.rounds.flatMap((r) => {
    const set = db.approvedSet(r.id)
    const posting = db.posting(r.posting_id)
    return set && posting ? [[posting.job_family, set.competencies.map((c) => c.name)] as [string, string[]]] : []
  })
}

function clean(body: BankQuestionBody): Omit<BankQuestionBody, never> | string {
  const question = squash(body.question ?? '')
  if (!question) return 'question:질문을 입력하세요.'
  if (!body.job_family?.trim()) return 'job_family:직군을 고르세요.'
  if (!body.competency?.trim()) return 'competency:역량을 고르세요.'
  const follow_ups = (body.follow_ups ?? []).map(squash).filter(Boolean)
  if (follow_ups.length > 10) return 'follow_ups:꼬리질문 예시는 10개까지입니다.'
  return {
    job_family: body.job_family.trim(),
    competency: body.competency.trim(),
    round_position: body.round_position ?? null,
    question,
    intent: (body.intent ?? '').trim(),
    follow_ups,
  }
}

const refused = (message: string) => {
  const [field, msg] = message.split(':') as [string, string]
  return invalid(field, msg)
}

function question(db: MockDb, id: string) {
  return db.bank.questions.find((q) => q.id === id)
}

function rubricOverlaps(db: MockDb, row: RubricExample) {
  return db.bank.rubric
    .filter((o) => o.status === 'approved' && o.id !== row.id && o.score !== row.score && o.competency === row.competency && o.job_family === row.job_family)
    .map((o) => ({ id: o.id, score: o.score, similarity: Math.round(overlap(o.answer, row.answer) * 1000) / 1000 }))
    .filter((o) => o.similarity >= 0.8)
}

/** Minimal CSV: quoted fields with "" escapes and line breaks inside quotes. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (c === '"') quoted = false
      else field += c
    } else if (c === '"') quoted = true
    else if (c === ',') {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else field += c
  }
  if (field || row.length) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((x) => x.trim()))
}

const HEADERS: Record<string, string[]> = {
  job_family: ['직군', 'job_family'],
  competency: ['역량', 'competency'],
  round: ['차수', 'round', 'round_position'],
  question: ['질문', 'question'],
  intent: ['의도', 'intent'],
  follow_ups: ['꼬리질문 예시', '꼬리질문', 'follow_ups'],
}

async function decode(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '')
  } catch {
    return new TextDecoder('euc-kr').decode(bytes) // Excel on Korean Windows saves CSV as CP949
  }
}

export const bankHandlers = [
  // ----- 질문 은행 -------------------------------------------------------------------------------
  http.get('/api/question-bank', async ({ request }) => {
    await latency()
    const db = getDb()
    const q = new URL(request.url).searchParams
    let rows = db.bank.questions.slice()
    const every = rows.map((r) => [r.job_family, r.competency] as [string, string])
    if (q.get('job_family')) rows = rows.filter((r) => r.job_family === q.get('job_family'))
    if (q.get('competency')) rows = rows.filter((r) => r.competency === q.get('competency'))
    if (q.get('round')) rows = rows.filter((r) => r.round_position === null || r.round_position === Number(q.get('round')))
    const counts = { draft: 0, approved: 0, retired: 0 } as Record<BankStatus, number>
    for (const r of rows) counts[r.status]++
    if (q.get('status')) rows = rows.filter((r) => r.status === q.get('status'))
    const needle = q.get('q')?.trim().toLowerCase()
    if (needle) rows = rows.filter((r) => [r.question, r.intent, ...r.follow_ups].some((t) => t.toLowerCase().includes(needle)))
    rows.sort((a, b) => a.job_family.localeCompare(b.job_family) || a.competency.localeCompare(b.competency) || a.created_at.localeCompare(b.created_at))
    return HttpResponse.json({ items: rows, families: families(every, dictionaries(db)), counts, total: rows.length })
  }),

  http.post('/api/question-bank/check', async ({ request }) => {
    const body = (await request.json()) as { question: string; follow_ups: string[] }
    return HttpResponse.json({ flags: checkQuestion(body.question ?? '', ...(body.follow_ups ?? [])) })
  }),

  http.post('/api/question-bank/import', async ({ request }) => {
    await latency(400)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const form = await request.formData()
    const file = form.get('file')
    if (!(file instanceof File)) return invalid('file', '필수 항목입니다.')
    const dryRun = form.get('dry_run') === 'true'
    const [header = [], ...data] = parseCsv(await decode(file))
    const lowered = header.map((h) => h.trim().toLowerCase())
    const column = (key: string) => {
      const names = HEADERS[key]!
      return lowered.findIndex((h) => names.some((n) => n.toLowerCase() === h))
    }
    const missing = ['job_family', 'competency', 'question'].filter((k) => column(k) < 0).map((k) => HEADERS[k]![0])
    if (missing.length) return invalid('file', `CSV 첫 줄에 ${missing.join(', ')} 열이 있어야 합니다.`)
    const existing = new Set(db.bank.questions.map((r) => `${r.job_family}|${r.competency}|${r.question.replace(/\s/g, '')}`))
    const errors: { row: number; message: string }[] = []
    const warnings: { row: number; message: string }[] = []
    let created = 0
    let skipped = 0
    data.forEach((raw, i) => {
      const row = i + 1
      const cell = (key: string) => (column(key) >= 0 ? (raw[column(key)] ?? '').trim() : '')
      const roundText = cell('round').replace('차', '')
      if (roundText && !/^[1-6]$/.test(roundText)) {
        errors.push({ row, message: '차수는 1~6 또는 비워 둡니다.' })
        return
      }
      const values = clean({
        job_family: cell('job_family'),
        competency: cell('competency'),
        round_position: roundText ? Number(roundText) : null,
        question: cell('question'),
        intent: cell('intent'),
        follow_ups: cell('follow_ups').split(/\|\||\||\n/),
      })
      if (typeof values === 'string') {
        errors.push({ row, message: values.split(':')[1]! })
        return
      }
      const key = `${values.job_family}|${values.competency}|${values.question.replace(/\s/g, '')}`
      if (existing.has(key)) {
        skipped++
        return
      }
      existing.add(key)
      const flags = checkQuestion(values.question, ...values.follow_ups)
      if (flags.length) warnings.push({ row, message: `금지 질문 경고: ${flags.map((f) => f.label).join(', ')}` })
      created++
      if (!dryRun) {
        db.bank.questions.push({
          id: newId(),
          ...values,
          status: 'draft',
          flags,
          source: 'csv',
          created_by: personOf(db.me),
          approved_by: null,
          created_at: now(),
          updated_at: now(),
          approved_at: null,
          retired_at: null,
        })
      }
    })
    return HttpResponse.json({ dry_run: dryRun, rows: data.length, created, skipped, errors, warnings })
  }),

  http.post('/api/question-bank', async ({ request }) => {
    await latency()
    const db = getDb()
    const values = clean((await request.json()) as BankQuestionBody)
    if (typeof values === 'string') return refused(values)
    const item: QuestionBankItem = {
      id: newId(),
      ...values,
      status: 'draft',
      flags: checkQuestion(values.question, ...values.follow_ups),
      source: 'manual',
      created_by: personOf(db.me),
      approved_by: null,
      created_at: now(),
      updated_at: now(),
      approved_at: null,
      retired_at: null,
    }
    db.bank.questions.push(item)
    db.log({ actor_type: 'user', action: 'question_bank.created', target_type: 'question_bank_item', target_id: item.id })
    return HttpResponse.json(item, { status: 201 })
  }),

  http.put('/api/question-bank/:id', async ({ params, request }) => {
    await latency()
    const db = getDb()
    const item = question(db, String(params.id))
    if (!item) return notFound('질문')
    if (item.status === 'retired') return conflict('폐기한 질문은 고칠 수 없습니다. 먼저 되살리세요.')
    const values = clean((await request.json()) as BankQuestionBody)
    if (typeof values === 'string') return refused(values)
    const changed = values.question !== item.question
    const ai = changed ? [] : item.flags.filter((f) => f.source === 'ai')
    Object.assign(item, values, { flags: [...checkQuestion(values.question, ...values.follow_ups), ...ai], updated_at: now() })
    if (item.status === 'approved') Object.assign(item, { status: 'draft', approved_by: null, approved_at: null })
    return HttpResponse.json(item)
  }),

  http.post('/api/question-bank/:id/approve', async ({ params, request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const item = question(db, String(params.id))
    if (!item) return notFound('질문')
    if (item.status === 'approved') return conflict('이미 승인한 질문입니다.')
    if (item.status === 'retired') return conflict('폐기한 질문은 승인할 수 없습니다. 먼저 되살리세요.')
    const body = (await request.json().catch(() => ({}))) as { confirm_warnings?: boolean }
    item.flags = [...checkQuestion(item.question, ...item.follow_ups), ...item.flags.filter((f) => f.source === 'ai')]
    if (item.flags.length && !body.confirm_warnings) {
      const labels = [...new Set(item.flags.map((f) => f.label))].join(', ')
      return conflict(`금지 질문 경고가 있습니다(${labels}). 직무와 관련 있는 질문인지 확인한 뒤 경고를 확인하고 승인하세요.`)
    }
    Object.assign(item, { status: 'approved', approved_by: personOf(db.me), approved_at: now() })
    db.log({ actor_type: 'user', action: 'question_bank.approved', target_type: 'question_bank_item', target_id: item.id })
    return HttpResponse.json(item)
  }),

  http.post('/api/question-bank/:id/retire', async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const item = question(db, String(params.id))
    if (!item) return notFound('질문')
    if (item.status === 'retired') return conflict('이미 폐기한 질문입니다.')
    Object.assign(item, { status: 'retired', retired_at: now() })
    return HttpResponse.json(item)
  }),

  http.post('/api/question-bank/:id/restore', async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const item = question(db, String(params.id))
    if (!item) return notFound('질문')
    if (item.status !== 'retired') return conflict('폐기한 질문만 되살릴 수 있습니다.')
    Object.assign(item, { status: 'draft', retired_at: null, approved_by: null, approved_at: null })
    return HttpResponse.json(item)
  }),

  http.post('/api/question-bank/:id/ai-check', async ({ params }) => {
    await latency(900)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const item = question(db, String(params.id))
    if (!item) return notFound('질문')
    const rules = checkQuestion(item.question, ...item.follow_ups)
    const ai = rules.map((f) => ({ ...f, source: 'ai' as const, note: `${f.label}: 직무와 무관한 개인 정보를 묻는 질문으로 보입니다 (${f.basis}).` }))
    item.flags = [...rules, ...ai]
    return HttpResponse.json(item)
  }),

  // ----- 평점 기준 예시 ----------------------------------------------------------------------------
  http.get('/api/rubric-examples', async ({ request }) => {
    await latency()
    const db = getDb()
    const q = new URL(request.url).searchParams
    let rows = db.bank.rubric.slice()
    const every = rows.map((r) => [r.job_family, r.competency] as [string, string])
    if (q.get('job_family')) rows = rows.filter((r) => r.job_family === q.get('job_family'))
    if (q.get('competency')) rows = rows.filter((r) => r.competency === q.get('competency'))
    const counts = { draft: 0, approved: 0, retired: 0 } as Record<BankStatus, number>
    for (const r of rows) counts[r.status]++
    rows.sort((a, b) => a.job_family.localeCompare(b.job_family) || a.competency.localeCompare(b.competency) || a.score - b.score)
    return HttpResponse.json({ items: rows.map((r) => ({ ...r, overlaps: r.status === 'retired' ? [] : rubricOverlaps(db, r) })), families: families(every, dictionaries(db)), counts })
  }),

  http.post('/api/rubric-examples', async ({ request }) => {
    await latency()
    const db = getDb()
    const body = (await request.json()) as RubricExampleBody
    if (!body.answer?.trim()) return invalid('answer', '예시 답변을 입력하세요.')
    if (/01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}|@/.test(body.answer)) return invalid('answer', '연락처·이메일·주민번호 모양이 있습니다. 실제 사람의 정보는 쓰지 마세요.')
    if (db.qaItems.some((q) => q.answer_deidentified && overlap(q.answer_deidentified, body.answer) > 0.6)) {
      return conflict('지원자의 실제 답변과 거의 같습니다. 평점 기준 예시는 사람이 새로 쓴 가상의 답변이어야 합니다.')
    }
    const row: RubricExample = {
      id: newId(),
      job_family: body.job_family,
      competency: body.competency,
      score: body.score,
      question: body.question?.trim() ?? '',
      answer: body.answer.trim(),
      rationale: body.rationale?.trim() ?? '',
      status: 'draft',
      source: 'manual',
      created_by: personOf(db.me),
      approved_by: null,
      created_at: now(),
      updated_at: now(),
      approved_at: null,
      retired_at: null,
      overlaps: [],
    }
    db.bank.rubric.push(row)
    return HttpResponse.json({ ...row, overlaps: rubricOverlaps(db, row) }, { status: 201 })
  }),

  http.put('/api/rubric-examples/:id', async ({ params, request }) => {
    await latency()
    const db = getDb()
    const row = db.bank.rubric.find((r) => r.id === params.id)
    if (!row) return notFound('평점 기준 예시')
    if (row.status === 'retired') return conflict('폐기한 예시는 고칠 수 없습니다. 먼저 되살리세요.')
    const body = (await request.json()) as RubricExampleBody
    if (!body.answer?.trim()) return invalid('answer', '예시 답변을 입력하세요.')
    Object.assign(row, { ...body, answer: body.answer.trim(), updated_at: now() })
    if (row.status === 'approved') Object.assign(row, { status: 'draft', approved_by: null, approved_at: null })
    return HttpResponse.json({ ...row, overlaps: rubricOverlaps(db, row) })
  }),

  ...(['approve', 'retire', 'restore'] as const).map((action) =>
    http.post(`/api/rubric-examples/:id/${action}`, async ({ params }) => {
      await latency()
      const db = getDb()
      if (!db.me.is_admin) return forbidden()
      const row = db.bank.rubric.find((r) => r.id === params.id)
      if (!row) return notFound('평점 기준 예시')
      if (action === 'approve') {
        if (row.status !== 'draft') return conflict('초안만 승인할 수 있습니다.')
        Object.assign(row, { status: 'approved', approved_by: personOf(db.me), approved_at: now() })
      } else if (action === 'retire') {
        if (row.status === 'retired') return conflict('이미 폐기한 예시입니다.')
        Object.assign(row, { status: 'retired', retired_at: now() })
      } else {
        if (row.status !== 'retired') return conflict('폐기한 예시만 되살릴 수 있습니다.')
        Object.assign(row, { status: 'draft', retired_at: null, approved_by: null, approved_at: null })
      }
      return HttpResponse.json({ ...row, overlaps: rubricOverlaps(db, row) })
    }),
  ),

  // ----- 관리자: 임베딩 색인, 꼬리질문 지표 -----------------------------------------------------------
  http.get('/api/admin/embedding-index', async () => {
    await latency(80)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    return HttpResponse.json(indexStatus(db.bank))
  }),

  http.post('/api/admin/embedding-index/rebuild', async () => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    db.bank.rebuildStartedAt = Date.now()
    return HttpResponse.json(indexStatus(db.bank), { status: 202 })
  }),

  http.get('/api/admin/follow-up-metrics', async ({ request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const days = Number(new URL(request.url).searchParams.get('days') ?? 30)
    return HttpResponse.json(metrics(db.bank, days))
  }),
]
