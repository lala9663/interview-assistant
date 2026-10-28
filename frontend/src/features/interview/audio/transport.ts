import { API_BASE } from '@/api/client'
import type { MicRole } from '@/api/types'

/**
 * Sends the microphone's 16 kHz PCM16 chunks to the server (docs/api-contract.md 3.3). A WebSocket
 * first; when it cannot open (a proxy or DLP blocking WebSockets) or drops, HTTP chunks to the same
 * session instead, one request at a time, in order. The server's refusals (NO-CONSENT, MIC-TAKEN ...)
 * are final; a network failure on both paths is HTTP-FAILED. Cookies go with both, so the request runs
 * as the signed-in interviewer like every other API call.
 */
export type TransportKind = 'websocket' | 'http'

export interface TransportHandlers {
  /** the server's VAD started or stopped hearing speech */
  onState: (speaking: boolean, role: MicRole) => void
  /** something degraded but audio still flows: WS-BLOCKED, WS-LOST, server notices */
  onNotice: (code: string, message?: string) => void
  /** audio cannot flow any more */
  onFatal: (code: string, message?: string) => void
}

export interface StartInfo {
  source: 'microphone' | 'sample'
  /** what getUserMedia applied (echoCancellation ...), for the audit log */
  constraints: Record<string, unknown>
}

export class AudioRefused extends Error {
  readonly code: string
  constructor(code: string, message?: string) {
    super(message || code)
    this.code = code
  }
}

const READY_TIMEOUT_MS = 4000
const HTTP_RETRIES = 3
const MAX_BATCH = 16000 * 2 * 4 // bytes per HTTP request: 4 s of audio

function streamId(): string {
  const random = globalThis.crypto?.randomUUID?.()
  return random ?? `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

async function refusalOf(res: Response): Promise<AudioRefused> {
  const body = (await res.json().catch(() => null)) as { detail?: { code?: string; message?: string } | string } | null
  const detail = body?.detail
  if (detail && typeof detail === 'object' && detail.code) return new AudioRefused(detail.code, detail.message)
  return new AudioRefused('HTTP-FAILED', typeof detail === 'string' ? detail : undefined)
}

export class AudioTransport {
  kind: TransportKind | null = null
  notices: string[] = []
  private socket: WebSocket | null = null
  private closed = false
  private stream = streamId()
  private seq = 0
  private queue: ArrayBuffer[] = []
  private sending = false

  private readonly sessionId: string
  private readonly start: StartInfo
  private readonly handlers: TransportHandlers
  private readonly options: { websocket?: boolean; fetch?: typeof fetch }

  constructor(sessionId: string, start: StartInfo, handlers: TransportHandlers, options: { websocket?: boolean; fetch?: typeof fetch } = {}) {
    this.sessionId = sessionId
    this.start = start
    this.handlers = handlers
    this.options = options
  }

  private get fetch(): typeof fetch {
    return this.options.fetch ?? ((...args) => fetch(...args))
  }

  /** Connect; resolves once audio can be sent, rejects with AudioRefused when it cannot. */
  async open(): Promise<void> {
    if (this.options.websocket !== false && typeof WebSocket !== 'undefined') {
      try {
        await this.openSocket()
        return
      } catch (error) {
        if (error instanceof AudioRefused) throw error
        this.handlers.onNotice('WS-BLOCKED')
      }
    }
    await this.openHttp()
  }

  private openSocket(): Promise<void> {
    const url = new URL(`${API_BASE}/sessions/${this.sessionId}/audio`, window.location.origin)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return new Promise((resolve, reject) => {
      let ready = false
      const socket = new WebSocket(url)
      socket.binaryType = 'arraybuffer'
      const timer = setTimeout(() => {
        socket.close()
        reject(new Error('timeout'))
      }, READY_TIMEOUT_MS)
      socket.onopen = () => socket.send(JSON.stringify({ type: 'start', format: 'pcm16', sample_rate: 16000, ...this.start }))
      socket.onmessage = (event) => {
        if (typeof event.data !== 'string') return
        const message = JSON.parse(event.data) as { type: string; code?: string; message?: string; speaking?: boolean; role?: MicRole; notices?: string[] }
        if (message.type === 'ready') {
          ready = true
          clearTimeout(timer)
          this.socket = socket
          this.kind = 'websocket'
          this.notices = message.notices ?? []
          resolve()
        } else if (message.type === 'state') {
          this.handlers.onState(Boolean(message.speaking), message.role ?? 'candidate')
        } else if (message.type === 'error') {
          clearTimeout(timer)
          const refused = new AudioRefused(message.code ?? 'HTTP-FAILED', message.message)
          if (ready) this.handlers.onFatal(refused.code, refused.message)
          else reject(refused)
          this.closed = this.closed || ready
        }
      }
      socket.onclose = () => {
        clearTimeout(timer)
        if (!ready) reject(new Error('closed'))
        else if (!this.closed && this.socket === socket) void this.fallBack()
      }
    })
  }

  /** The WebSocket dropped after it worked: go on over HTTP with a new stream. */
  private async fallBack() {
    this.socket = null
    this.handlers.onNotice('WS-LOST')
    this.stream = streamId()
    this.seq = 0
    try {
      await this.openHttp()
    } catch (error) {
      const refused = error instanceof AudioRefused ? error : new AudioRefused('HTTP-FAILED')
      this.handlers.onFatal(refused.code, refused.message)
    }
  }

  private chunkUrl(seq: number) {
    const query = new URLSearchParams({ stream: this.stream, seq: String(seq), source: this.start.source })
    return new URL(`${API_BASE}/sessions/${this.sessionId}/audio/chunks?${query}`, window.location.origin)
  }

  private async post(body: Uint8Array): Promise<void> {
    const seq = this.seq++
    for (let attempt = 0; ; attempt++) {
      let res: Response
      try {
        res = await this.fetch(this.chunkUrl(seq), {
          method: 'POST',
          body: body as BodyInit,
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/octet-stream', 'X-Audio-Format': 'pcm16;rate=16000' },
        })
      } catch {
        if (attempt + 1 >= HTTP_RETRIES) throw new AudioRefused('HTTP-FAILED')
        await new Promise((r) => setTimeout(r, 300 * 2 ** attempt))
        continue
      }
      if (!res.ok) throw await refusalOf(res)
      const state = (await res.json()) as { speaking: boolean; role: MicRole; notices: string[] }
      this.notices = state.notices
      this.handlers.onState(state.speaking, state.role)
      return
    }
  }

  private async openHttp(): Promise<void> {
    await this.post(new Uint8Array(0)) // checks consent and the session before any audio
    this.kind = 'http'
  }

  send(pcm: ArrayBuffer) {
    if (this.closed) return
    if (this.socket) {
      if (this.socket.readyState === WebSocket.OPEN) this.socket.send(pcm)
      return
    }
    if (this.kind !== 'http') return
    this.queue.push(pcm)
    if (!this.sending) void this.drain()
  }

  private async drain() {
    this.sending = true
    try {
      while (this.queue.length && !this.closed) {
        let size = 0
        const parts: ArrayBuffer[] = []
        while (this.queue.length && size + this.queue[0]!.byteLength <= MAX_BATCH) {
          const part = this.queue.shift()!
          parts.push(part)
          size += part.byteLength
        }
        const body = new Uint8Array(size)
        let at = 0
        for (const part of parts) {
          body.set(new Uint8Array(part), at)
          at += part.byteLength
        }
        await this.post(body)
      }
    } catch (error) {
      const refused = error instanceof AudioRefused ? error : new AudioRefused('HTTP-FAILED')
      this.closed = true
      this.handlers.onFatal(refused.code, refused.message)
    } finally {
      this.sending = false
    }
  }

  close() {
    this.closed = true
    this.queue = []
    if (this.socket) {
      const socket = this.socket
      this.socket = null
      socket.close(1000)
    } else if (this.kind === 'http') {
      const query = new URLSearchParams({ stream: this.stream })
      void this.fetch(new URL(`${API_BASE}/sessions/${this.sessionId}/audio/chunks?${query}`, window.location.origin), {
        method: 'DELETE',
        credentials: 'same-origin',
      }).catch(() => {})
    }
  }
}
