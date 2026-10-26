/**
 * 관리자 > 연동 현황 on the mock API: events the recruiting site "sent" (scripted, relative to now), the
 * summary the backend computes (api/views.py intake_summary) and 다시 처리. A retried event settles a
 * moment later: an unknown posting number goes through once a posting carries it, a closed posting once it
 * is open again; other failures fail again (the mock has no files to read).
 */
import type { IntakeEvent, IntakeFailure, IntakeSummary, IntakeTotals } from '@/api/types'
import { addMinutes } from '@/lib/time'

import type { MockDb } from './db'

const RETRY_MS = 1800

export interface MockIntakeEvent extends IntakeEvent {
  /** mock only: the failure a retry runs into again, and when the retry settles */
  lastFailure?: IntakeFailure
  settleAt?: number
}

export interface IntakeState {
  events: MockIntakeEvent[]
}

const iso = (d: Date) => d.toISOString()
const TOTAL_KEYS: (keyof IntakeTotals)[] = ['received', 'queued', 'processing', 'done', 'skipped', 'failed', 'rejected']

function failure(code: string, message: string, fields: string[]): IntakeFailure {
  return { code, message, fields }
}

/** Scripted history: some seeded applications came from the site, plus the usual failures. */
export function createIntakeState(db: MockDb, newId: () => string): IntakeState {
  const events: MockIntakeEvent[] = []
  let seq = 100
  let minutes = -150
  const add = (e: Partial<MockIntakeEvent> & Pick<MockIntakeEvent, 'status' | 'event_type' | 'posting_no' | 'application_no'>) => {
    minutes += 6
    const received = addMinutes(db.now, minutes)
    const took = 600 + ((seq * 137) % 1300)
    const started = new Date(received.getTime() + 300)
    const finished = new Date(started.getTime() + took)
    const settled = e.status !== 'rejected'
    seq += 1
    const event: MockIntakeEvent = {
      id: newId(),
      event_id: `EVT-${String(seq).padStart(6, '0')}`,
      revision: 1,
      occurred_at: iso(addMinutes(received, -1)),
      received_at: iso(received),
      started_at: settled ? iso(started) : null,
      finished_at: iso(settled ? finished : received),
      processing_ms: settled ? took : null,
      attempts: settled ? 1 : 0,
      posting: null,
      candidate: null,
      failure: null,
      dropped_fields: [],
      retriable: false,
      result: null,
      ...e,
    }
    events.push(event)
    return event
  }

  const fromSite = db.applications.filter((_, i) => [0, 1, 2, 4, 6, 7, 9, 11, 13, 15].includes(i))
  fromSite.forEach((a, k) => {
    a.channel = 'site'
    const p = db.posting(a.posting_id)!
    const c = db.candidate(a.candidate_id)!
    const common = {
      posting_no: p.site_posting_no,
      application_no: `A${100001 + k}`,
      posting: { id: p.id, title: p.title },
      candidate: { id: c.id, pseudonym: c.pseudonym },
    }
    if (k === 3) {
      // An update arrived before its submission: the update applied, the late submission was skipped.
      add({ ...common, event_type: 'updated', revision: 2, status: 'done', result: { created: true } })
      add({
        ...common,
        event_type: 'submitted',
        status: 'skipped',
        failure: failure('stale_revision', '더 새 버전(revision 2)이 이미 반영되어 이 버전은 반영하지 않았습니다.', []),
      })
      return
    }
    add({ ...common, event_type: 'submitted', status: 'done', dropped_fields: k === 5 ? ['applicant.military_service'] : [], result: { created: true } })
    if (k === 1) add({ ...common, event_type: 'updated', revision: 2, status: 'done', result: { created: false, screening_reset: true } })
  })

  const P1_NO = db.postings[0]!.site_posting_no
  const P2_NO = db.postings[1]!.site_posting_no
  add({ event_type: 'withdrawn', revision: 2, status: 'done', posting_no: P1_NO, application_no: 'A100090', result: { application_found: false } })
  for (let i = 0; i < 3; i++) {
    const f = failure(
      'unknown_posting',
      '채용 사이트 공고 번호 DS-2026-0103에 연결된 공고가 없습니다. 공고 화면에서 번호를 연결한 뒤 다시 처리하세요.',
      ['posting_no'],
    )
    add({ event_type: 'submitted', status: 'failed', posting_no: 'DS-2026-0103', application_no: `A10020${i + 1}`, failure: f, retriable: true })
  }
  add({
    event_type: 'submitted',
    status: 'failed',
    posting_no: P2_NO,
    application_no: 'A100211',
    failure: failure('unsupported_attachment', '첨부 1(이력서): HWP(한글) 파일은 아직 지원하지 않습니다', ['attachments[0]']),
    retriable: true,
  })
  add({
    event_type: 'submitted',
    status: 'failed',
    posting_no: P1_NO,
    application_no: 'A100212',
    failure: failure('ocr_required', '첨부 1(이력서): 스캔본이라 글자를 읽을 수 없습니다 (OCR 필요, 1쪽). 텍스트가 있는 PDF·DOCX로 올려 주세요.', ['attachments[0]']),
    retriable: true,
  })
  add({
    event_type: 'submitted',
    status: 'rejected',
    posting_no: P1_NO,
    application_no: 'A100213',
    failure: failure('forbidden_field', '받지 않는 항목이 들어 있어 지원서를 받지 않았습니다: 사진. 이 항목을 빼고 새 event_id로 다시 보내 주세요.', ['applicant.photo']),
  })
  add({
    event_type: 'submitted',
    status: 'rejected',
    posting_no: P2_NO,
    application_no: 'A100214',
    failure: failure('missing_field', '필수 항목이 없습니다: applicant.name', ['applicant.name']),
  })
  return { events }
}

/** Retries whose moment has come resolve here (called before every read, like the mock AI scoring). */
export function settle(db: MockDb) {
  const now = Date.now()
  for (const e of db.intake.events) {
    if (e.status !== 'queued' || e.settleAt === undefined || e.settleAt > now) continue
    const again = e.lastFailure!
    const posting = db.postings.find((p) => p.site_posting_no && p.site_posting_no === e.posting_no)
    const passes = (again.code === 'unknown_posting' && posting) || (again.code === 'posting_closed' && posting && posting.status !== 'closed')
    e.started_at = iso(new Date(e.settleAt - 900))
    e.finished_at = iso(new Date(e.settleAt))
    e.processing_ms = 900
    e.settleAt = undefined
    if (passes && posting) {
      const created = db.addApplication(posting.id, e.application_no ?? e.event_id, 'site')
      e.status = 'done'
      e.posting = { id: posting.id, title: posting.title }
      e.candidate = created.candidate
      e.result = { created: true, new_candidate: true }
      e.failure = null
    } else {
      e.status = 'failed'
      e.failure = again
      e.retriable = true
    }
  }
}

export function retry(db: MockDb, e: MockIntakeEvent, delayMs: number): boolean {
  if (e.status !== 'failed' || !e.retriable || !e.failure) return false
  e.lastFailure = e.failure
  e.failure = null
  e.retriable = false
  e.status = 'queued'
  e.attempts += 1
  e.settleAt = Date.now() + delayMs
  db.log({ actor_type: 'user', action: 'intake.retried', target_type: 'intake_event', target_id: e.id, details: { previous: e.lastFailure.code } })
  return true
}

export const retryDelay = (speed: number) => Math.round(RETRY_MS * speed)

export function summary(db: MockDb): IntakeSummary {
  const totals = Object.fromEntries(TOTAL_KEYS.map((k) => [k, 0])) as unknown as IntakeTotals
  const per = new Map<string | null, IntakeSummary['postings'][number]>()
  const failures = new Map<string, { count: number; retriable: number }>()
  for (const e of db.intake.events) {
    totals.received += 1
    totals[e.status] += 1
    let row = per.get(e.posting_no)
    if (!row) {
      const p = db.postings.find((x) => x.site_posting_no && x.site_posting_no === e.posting_no)
      row = {
        posting_no: e.posting_no,
        posting: p ? { id: p.id, title: p.title } : null,
        received: 0,
        submitted: 0,
        updated: 0,
        withdrawn: 0,
        done: 0,
        skipped: 0,
        failed: 0,
        rejected: 0,
        pending: 0,
        applications: p ? db.applications.filter((a) => a.posting_id === p.id && a.channel === 'site' && !a.withdrawn_at).length : 0,
      }
      per.set(e.posting_no, row)
    }
    row.received += 1
    if (e.event_type) row[e.event_type] += 1
    if (e.status === 'queued' || e.status === 'processing') row.pending += 1
    else row[e.status] += 1
    if ((e.status === 'failed' || e.status === 'rejected') && e.failure) {
      const f = failures.get(e.failure.code) ?? { count: 0, retriable: 0 }
      f.count += 1
      if (e.retriable) f.retriable += 1
      failures.set(e.failure.code, f)
    }
  }
  const applied = db.intake.events.filter((e) => (e.status === 'done' || e.status === 'skipped') && e.processing_ms !== null)
  const took = applied.map((e) => e.processing_ms!).sort((a, b) => a - b)
  const waits = applied.map((e) => new Date(e.started_at!).getTime() - new Date(e.received_at).getTime())
  const first = applied.length ? Math.min(...applied.map((e) => new Date(e.received_at).getTime())) : null
  const last = applied.length ? Math.max(...applied.map((e) => new Date(e.finished_at!).getTime())) : null
  const pct = (p: number) => (took.length ? took[Math.min(took.length - 1, Math.ceil(p * took.length) - 1)]! : null)
  const minutes = first !== null && last !== null && last > first ? (last - first) / 60000 : null
  const postings = [...per.values()].sort((a, b) => Number(!a.posting) - Number(!b.posting) || (a.posting_no ?? '').localeCompare(b.posting_no ?? ''))
  for (const p of db.postings) {
    if (p.site_posting_no && !per.has(p.site_posting_no)) {
      postings.push({
        posting_no: p.site_posting_no,
        posting: { id: p.id, title: p.title },
        received: 0,
        submitted: 0,
        updated: 0,
        withdrawn: 0,
        done: 0,
        skipped: 0,
        failed: 0,
        rejected: 0,
        pending: 0,
        applications: 0,
      })
    }
  }
  return {
    configured: true,
    workers: 4,
    totals,
    postings,
    failures: [...failures.entries()].sort((a, b) => b[1].count - a[1].count).map(([code, f]) => ({ code, ...f })),
    timing: {
      processed: took.length,
      avg_ms: took.length ? Math.round(took.reduce((s, x) => s + x, 0) / took.length) : null,
      p50_ms: pct(0.5),
      p95_ms: pct(0.95),
      max_ms: took.length ? took[took.length - 1]! : null,
      avg_wait_ms: waits.length ? Math.round(waits.reduce((s, x) => s + x, 0) / waits.length) : null,
      first_received_at: first !== null ? iso(new Date(first)) : null,
      last_finished_at: last !== null ? iso(new Date(last)) : null,
      per_minute: minutes ? Math.round((applied.length / minutes) * 10) / 10 : null,
    },
  }
}
