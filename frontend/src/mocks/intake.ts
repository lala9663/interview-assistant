/**
 * MSW handlers for 관리자 > 연동 현황 (docs/api-contract.md "채용 사이트 연동"): same filters, status codes and
 * 403 for non-admins as `api/routes/intake.py`, on the scripted state of mocks/intake-state.ts. The site's own
 * signed endpoints are not mocked: the browser never calls them.
 */
import { delay, http, HttpResponse } from 'msw'

import type { IntakeStatus } from '@/api/types'

import { getDb } from './db'
import { retry, retryDelay, settle, summary } from './intake-state'
import { mockConfig } from './live'

const API = '/api/admin/intake'
const latency = (ms = 180) => delay(Math.round(ms * mockConfig.speed))
const forbidden = () => HttpResponse.json({ detail: '관리자만 쓸 수 있습니다.' }, { status: 403 })

export const intakeHandlers = [
  http.get(`${API}/summary`, async () => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    settle(db)
    return HttpResponse.json(summary(db))
  }),

  http.get(`${API}/events`, async ({ request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    settle(db)
    const q = new URL(request.url).searchParams
    const status = q.get('status') as IntakeStatus | null
    const postingNo = q.get('posting_no')
    const limit = Math.min(Math.max(Number(q.get('limit') ?? 200), 1), 1000)
    const list = db.intake.events
      .filter((e) => !status || e.status === status)
      .filter((e) => !postingNo || (postingNo === '-' ? e.posting_no === null : e.posting_no === postingNo))
      .slice()
      .reverse()
      .slice(0, limit)
      .map(({ lastFailure: _f, settleAt: _s, ...e }) => {
        // Like the backend: an event that never resolved its posting is named by the linked number.
        const linked = e.posting ? null : db.postings.find((p) => p.site_posting_no && p.site_posting_no === e.posting_no)
        return linked ? { ...e, posting: { id: linked.id, title: linked.title } } : e
      })
    return HttpResponse.json(list)
  }),

  http.post(`${API}/events/:id/retry`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const e = db.intake.events.find((x) => x.id === params.id)
    if (!e) return HttpResponse.json({ detail: '연동 이벤트를 찾을 수 없습니다.' }, { status: 404 })
    if (!retry(db, e, retryDelay(mockConfig.speed))) {
      return HttpResponse.json(
        { detail: '다시 처리할 수 없는 이벤트입니다. 실패했고 원문이 남아 있는 이벤트만 다시 처리합니다. 거절된 이벤트는 채용 사이트에서 새 event_id로 보내야 합니다.' },
        { status: 409 },
      )
    }
    const { lastFailure: _f, settleAt: _s, ...view } = e
    return HttpResponse.json(view)
  }),

  http.post(`${API}/retry`, async ({ request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const body = (await request.json()) as { failure_code?: string; posting_no?: string }
    const targets = db.intake.events.filter(
      (e) =>
        e.status === 'failed' &&
        e.retriable &&
        (!body.failure_code || e.failure?.code === body.failure_code) &&
        (!body.posting_no || e.posting_no === body.posting_no),
    )
    let requeued = 0
    for (const e of targets) if (retry(db, e, retryDelay(mockConfig.speed))) requeued += 1
    return HttpResponse.json({ requeued })
  }),
]
