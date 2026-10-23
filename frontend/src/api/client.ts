import type { ApiErrorBody } from './types'

/** All REST routes live under this prefix (FastAPI mounts its routers there). */
export const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody | null

  constructor(status: number, message: string, body: ApiErrorBody | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function messageFrom(status: number, body: ApiErrorBody | null): string {
  if (body && typeof body.detail === 'string') return body.detail
  if (body && Array.isArray(body.detail) && body.detail.length > 0) {
    return body.detail.map((d) => `${d.loc.slice(1).join('.')}: ${d.msg}`).join(', ')
  }
  if (status === 404) return '찾을 수 없습니다.'
  if (status >= 500) return '서버 오류가 발생했습니다.'
  return `요청이 실패했습니다 (${status}).`
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  // FormData (uploads) gets its multipart boundary from the browser.
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  let res: Response
  try {
    // Absolute URL so the same code runs in the browser and under jsdom (tests).
    res = await fetch(new URL(`${API_BASE}${path}`, window.location.origin), { ...init, headers })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, '서버에 연결할 수 없습니다.', null)
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiErrorBody | null
    throw new ApiError(res.status, messageFrom(res.status, body), body)
  }
  return res
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
