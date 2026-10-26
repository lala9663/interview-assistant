/**
 * MSW handlers for 관리자 > 모델 설정 (docs/api-contract.md "관리자 > 모델 설정"): same validation, status
 * codes and history semantics as `api/routes/admin.py`, on the in-memory state of mocks/models.ts.
 * Downloads progress on a timer; tests answer with canned results (the mock does not hear audio).
 */
import { delay, http, HttpResponse } from 'msw'

import type { ApplyModelRequest, ModelChange, ModelDownload, ModelRole, ModelSpec, RevertModelRequest } from '@/api/types'
import { MODEL_ROLES } from '@/api/types'

import { getDb, newId, type MockDb } from './db'
import { mockConfig } from './live'
import {
  findImpl,
  mockCatalog,
  modelName,
  normalize,
  requirementsFor,
  ROLE_INFO,
  roleState,
  specLabel,
  SpecError,
  testResult,
  WHISPER_SIZES,
  type ModelState,
} from './models'

const API = '/api/admin/models'
const latency = (ms = 200) => delay(Math.round(ms * mockConfig.speed))
const DOWNLOAD_MS = 6000 // a simulated download at speed 1

const forbidden = () => HttpResponse.json({ detail: '관리자만 쓸 수 있습니다.' }, { status: 403 })
const conflict = (detail: string) => HttpResponse.json({ detail }, { status: 409 })
const invalid = (field: string, msg: string) => HttpResponse.json({ detail: [{ loc: ['body', field], msg, type: 'value_error' }] }, { status: 422 })

const isRole = (role: unknown): role is ModelRole => typeof role === 'string' && (MODEL_ROLES as readonly string[]).includes(role)
const same = (a: ModelSpec, b: ModelSpec) => JSON.stringify(a) === JSON.stringify(b)

function catalogOf(state: ModelState) {
  syncDownloads(state)
  return mockCatalog(state.downloaded)
}

function syncDownloads(state: ModelState) {
  for (const [model, job] of state.downloads) {
    if (!job.cancelled && Date.now() - job.startedAt >= job.durationMs) {
      state.downloaded.add(model)
      state.downloads.delete(model)
    }
  }
}

function downloadView(state: ModelState, model: string): ModelDownload {
  syncDownloads(state)
  const total = WHISPER_SIZES[model] ?? 0
  const job = state.downloads.get(model)
  if (state.downloaded.has(model)) return { impl: 'faster_whisper', model, status: 'done', total_bytes: total, downloaded_bytes: total, error: null }
  if (job && !job.cancelled) {
    const share = Math.min(0.99, (Date.now() - job.startedAt) / job.durationMs)
    return { impl: 'faster_whisper', model, status: 'downloading', total_bytes: total, downloaded_bytes: Math.round(total * share), error: null }
  }
  return { impl: 'faster_whisper', model, status: job?.cancelled ? 'cancelled' : 'missing', total_bytes: total, downloaded_bytes: 0, error: null }
}

/** Validate a spec for a role; a Response on failure. */
function prepare(state: ModelState, role: ModelRole, spec: ModelSpec, stored = false) {
  const catalog = catalogOf(state)
  const impl = findImpl(catalog, role, spec.impl)
  if (!impl) return { error: invalid('impl', '등록되지 않은 provider입니다.') }
  if (!impl.roles.includes(role)) return { error: invalid('impl', `${impl.label}은(는) ${ROLE_INFO[role].label} 역할에 쓸 수 없습니다.`) }
  let options = spec.options
  if (!stored) {
    try {
      options = normalize(impl, role, spec.options ?? {})
    } catch (e) {
      if (e instanceof SpecError) return { error: invalid(e.field, e.message) }
      throw e
    }
  }
  const requirements = requirementsFor(impl, options, state.downloaded)
  return { impl, catalog, spec: { impl: spec.impl, options }, requirements, unmet: requirements.filter((r) => !r.ok) }
}

function record(db: MockDb, role: ModelRole, kind: ModelChange['kind'], spec: ModelSpec, reason: string, reverts: string | null, external: boolean) {
  const state = db.models
  const catalog = catalogOf(state)
  const previous = state.active[role]
  const change: ModelChange = {
    id: newId(),
    revision: (state.history[0]?.revision ?? 0) + 1,
    occurred_at: new Date().toISOString(),
    role,
    role_label: ROLE_INFO[role].label,
    kind,
    actor: { id: db.me.id, employee_no: db.me.employee_no, name: db.me.name },
    previous: structuredClone(previous),
    new: structuredClone(spec),
    previous_label: specLabel(catalog, role, previous),
    new_label: specLabel(catalog, role, spec) ?? '',
    reason,
    reverts_change_id: reverts,
    details: { model: modelName(spec), data_location: findImpl(catalog, role, spec.impl)?.data_location, confirmed_external: external },
  }
  state.history.unshift(change)
  state.active[role] = structuredClone(spec)
  return change
}

export const adminHandlers = [
  http.get(API, async () => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const catalog = catalogOf(db.models)
    return HttpResponse.json({
      revision: db.models.history[0]?.revision ?? 0,
      persistent: true,
      roles: MODEL_ROLES.map((r) => roleState(db.models, r, catalog)),
    })
  }),

  http.get(`${API}/catalog`, async () => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    return HttpResponse.json(catalogOf(db.models))
  }),

  http.get(`${API}/history`, async () => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    return HttpResponse.json(db.models.history.slice(0, 50))
  }),

  http.get(`${API}/downloads`, async () => {
    await latency(80)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    return HttpResponse.json(Object.keys(WHISPER_SIZES).map((m) => downloadView(db.models, m)))
  }),

  http.post(`${API}/downloads`, async ({ request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const body = (await request.json()) as { impl: string; model: string }
    if (body.impl !== 'faster_whisper' || !(body.model in WHISPER_SIZES)) return HttpResponse.json({ detail: '모델 파일을(를) 찾을 수 없습니다.' }, { status: 404 })
    const now = downloadView(db.models, body.model)
    if (now.status !== 'done' && now.status !== 'downloading') {
      db.models.downloads.set(body.model, { startedAt: Date.now(), durationMs: DOWNLOAD_MS * mockConfig.speed, cancelled: false })
    }
    return HttpResponse.json(downloadView(db.models, body.model), { status: 202 })
  }),

  http.delete(`${API}/downloads/:impl/:model`, async ({ params }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const model = String(params.model)
    const job = db.models.downloads.get(model)
    if (job) job.cancelled = true
    return HttpResponse.json(downloadView(db.models, model))
  }),

  http.post(`${API}/:role/check`, async ({ params, request }) => {
    await latency()
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    if (!isRole(params.role)) return invalid('role', '알 수 없는 역할입니다.')
    const p = prepare(db.models, params.role, (await request.json()) as ModelSpec)
    if (p.error) return p.error
    return HttpResponse.json({
      role: params.role,
      spec: p.spec,
      data_location: p.impl.data_location,
      external: p.impl.data_location === 'external',
      requirements: p.requirements,
      ready: p.unmet.length === 0,
      same_as_active: same(db.models.active[params.role], p.spec),
    })
  }),

  http.post(`${API}/:role/test`, async ({ params, request }) => {
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    if (!isRole(params.role)) return invalid('role', '알 수 없는 역할입니다.')
    const form = await request.formData()
    let spec: ModelSpec
    try {
      spec = JSON.parse(String(form.get('spec') ?? ''))
    } catch {
      return invalid('spec', '모델 설정(JSON)을 읽을 수 없습니다.')
    }
    const p = prepare(db.models, params.role, spec)
    if (p.error) return p.error
    if (p.impl.data_location === 'external' && form.get('confirm_external') !== 'true')
      return conflict('회사 밖으로 데이터를 보내는 provider입니다. 경고를 확인한 뒤 테스트하세요.')
    if (p.unmet.length) return conflict(`요구 조건을 충족하지 않습니다: ${p.unmet.map((r) => r.label).join(', ')}`)
    const audio = form.get('audio')
    const result = testResult(params.role, p.spec, audio instanceof File ? audio : null)
    await latency(Math.min(result.latency_ms, 1500))
    return HttpResponse.json(result)
  }),

  http.post(`${API}/:role/apply`, async ({ params, request }) => {
    await latency(500)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    if (!isRole(params.role)) return invalid('role', '알 수 없는 역할입니다.')
    const body = (await request.json()) as ApplyModelRequest
    const p = prepare(db.models, params.role, { impl: body.impl, options: body.options })
    if (p.error) return p.error
    if (same(db.models.active[params.role], p.spec)) return conflict('지금 쓰는 설정과 같습니다.')
    const external = p.impl.data_location === 'external'
    if (external && !body.confirm_external) return conflict('회사 밖으로 데이터를 보내는 provider입니다. 경고를 확인하고 사유를 적어야 적용됩니다.')
    if (!body.reason?.trim()) return invalid('reason', '변경 사유를 적어 주세요.')
    if (p.unmet.length) return conflict(`요구 조건을 충족하지 않습니다: ${p.unmet.map((r) => r.label).join(', ')}`)
    record(db, params.role, 'apply', p.spec, body.reason.trim(), null, external)
    return HttpResponse.json(roleState(db.models, params.role, catalogOf(db.models)))
  }),

  http.post(`${API}/history/:changeId/revert`, async ({ params, request }) => {
    await latency(500)
    const db = getDb()
    if (!db.me.is_admin) return forbidden()
    const change = db.models.history.find((c) => c.id === params.changeId)
    if (!change) return HttpResponse.json({ detail: '변경 이력을(를) 찾을 수 없습니다.' }, { status: 404 })
    if (!change.previous) return conflict('처음 설정이라 되돌릴 이전 설정이 없습니다.')
    const role = change.role as ModelRole
    const body = (await request.json()) as RevertModelRequest
    const p = prepare(db.models, role, change.previous, true)
    if (p.error) return p.error
    if (same(db.models.active[role], p.spec)) return conflict('지금 쓰는 설정과 같습니다.')
    const external = p.impl.data_location === 'external'
    if (external && !body.confirm_external) return conflict('회사 밖으로 데이터를 보내는 provider입니다. 경고를 확인하고 사유를 적어야 적용됩니다.')
    if (!body.reason?.trim()) return invalid('reason', '변경 사유를 적어 주세요.')
    if (p.unmet.length) return conflict(`요구 조건을 충족하지 않습니다: ${p.unmet.map((r) => r.label).join(', ')}`)
    record(db, role, 'rollback', p.spec, body.reason.trim(), change.id, external)
    return HttpResponse.json(roleState(db.models, role, catalogOf(db.models)))
  }),
]
