import { apiFetch } from './client'

export interface SseMessage {
  event: string
  data: string
  id?: string
}

/**
 * Minimal text/event-stream parser over fetch. Used instead of EventSource so the same client works
 * for POST streams (follow-ups), custom headers (SSO later) and the mock worker.
 */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const msg = parseBlock(block)
        if (msg) yield msg
        boundary = buffer.indexOf('\n\n')
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = 'message'
  let id: string | undefined
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    else if (field === 'id') id = value
  }
  if (data.length === 0) return null
  return { event, data: data.join('\n'), id }
}

/** Open an SSE endpoint and yield typed `{event, data}` objects (data JSON-parsed). */
export async function* streamEvents<E extends { event: string; data: unknown }>(
  path: string,
  init: RequestInit & { signal: AbortSignal },
): AsyncGenerator<E> {
  const res = await apiFetch(path, { ...init, headers: { ...init.headers, Accept: 'text/event-stream' } })
  if (!res.body) return
  for await (const msg of readSse(res.body)) {
    yield { event: msg.event, data: JSON.parse(msg.data) } as E
  }
}
