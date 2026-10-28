import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { render, screen, waitFor } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, effectScope, h } from 'vue'

import type { QAItem } from '@/api/types'
import { TooltipProvider } from '@/components/ui/tooltip'
import { server } from '@/mocks/node'

import MicPanel from '../MicPanel.vue'
import { DEFAULT_MIC_SETTINGS } from './settings'
import { useMicrophone } from './use-microphone'

const SESSION = 'session-1'

// --- browser audio stand-ins ---------------------------------------------------------------------

const track = { stop: vi.fn(), getSettings: () => ({ echoCancellation: true, noiseSuppression: false, autoGainControl: false, sampleRate: 48000 }) }
const getUserMedia = vi.fn(async (_c: MediaStreamConstraints) => ({ getTracks: () => [track], getAudioTracks: () => [track] }) as unknown as MediaStream)

const worklets: { port: { onmessage: ((e: { data: unknown }) => void) | null } }[] = []
const graphNode = () => ({ connect: (x: unknown) => x })

class FakeAudioContext {
  sampleRate = 48000
  destination = {}
  audioWorklet = { addModule: vi.fn(async () => {}) }
  createMediaStreamSource = vi.fn(graphNode)
  createGain = () => ({ gain: { value: 1 }, connect: (x: unknown) => x })
  resume = vi.fn(async () => {})
  close = vi.fn(async () => {})
}

class FakeWorkletNode {
  port = { onmessage: null }
  connect = (x: unknown) => x
  constructor() {
    worklets.push(this)
  }
}

type Reply = (socket: FakeSocket) => void
class FakeSocket {
  static instances: FakeSocket[] = []
  static reply: Reply = (s) => s.message({ type: 'ready', stream_id: 'x', role: 'candidate', notices: [] })
  readyState = 1
  binaryType = ''
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  url: URL
  constructor(url: URL) {
    this.url = url
    FakeSocket.instances.push(this)
    setTimeout(() => this.onopen?.())
  }
  send(data: unknown) {
    this.sent.push(data)
    if (typeof data === 'string') setTimeout(() => FakeSocket.reply(this))
  }
  message(body: unknown) {
    this.onmessage?.({ data: JSON.stringify(body) })
  }
  close() {
    this.readyState = 3
    this.onclose?.()
  }
  static OPEN = 1
}

beforeEach(() => {
  FakeSocket.instances = []
  FakeSocket.reply = (s) => s.message({ type: 'ready', stream_id: 'x', role: 'candidate', notices: [] })
  worklets.length = 0
  getUserMedia.mockClear()
  vi.stubGlobal('AudioContext', FakeAudioContext)
  vi.stubGlobal('AudioWorkletNode', FakeWorkletNode)
  vi.stubGlobal('WebSocket', FakeSocket)
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
})
afterEach(() => vi.unstubAllGlobals())

function microphone(onQuestion?: (qa: QAItem) => void) {
  const scope = effectScope()
  const mic = scope.run(() => useMicrophone(SESSION, { onQuestion }))!
  return { ...mic, scope }
}

const chunk = (level = 0.4) => worklets.at(-1)!.port.onmessage!({ data: { pcm: new Int16Array(1600).buffer, level } })

// --- the composable -----------------------------------------------------------------------------

describe('microphone', () => {
  it('asks for the STT-friendly processing and streams 16 kHz chunks over a WebSocket', async () => {
    const mic = microphone()
    await mic.start(DEFAULT_MIC_SETTINGS)
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    })
    const socket = FakeSocket.instances[0]!
    expect(socket.url.protocol).toBe('ws:')
    expect(socket.url.pathname).toBe(`/api/sessions/${SESSION}/audio`)
    const start = JSON.parse(socket.sent[0] as string)
    expect(start).toMatchObject({ type: 'start', format: 'pcm16', sample_rate: 16000, source: 'microphone' })
    expect(start.constraints).toMatchObject({ echoCancellation: true, noiseSuppression: false, sampleRate: 48000 })
    expect(mic.state.value).toMatchObject({ status: 'on', transport: 'websocket', error: null })

    chunk(0.4)
    expect(socket.sent[1]).toBeInstanceOf(ArrayBuffer)
    expect(mic.state.value.level).toBe(0.4)
    socket.message({ type: 'state', speaking: true, role: 'candidate' })
    expect(mic.state.value.speaking).toBe(true)

    mic.stop()
    expect(track.stop).toHaveBeenCalled()
    expect(socket.readyState).toBe(3)
    expect(mic.state.value.status).toBe('off')
  })

  it.each([
    ['NotAllowedError', 'MIC-DENIED'],
    ['NotFoundError', 'MIC-NONE'],
    ['NotReadableError', 'MIC-BUSY'],
  ])('reports %s from getUserMedia as %s', async (name, code) => {
    getUserMedia.mockRejectedValueOnce(new DOMException('no', name))
    const mic = microphone()
    await mic.start(DEFAULT_MIC_SETTINGS)
    expect(mic.state.value.status).toBe('error')
    expect(mic.state.value.error?.code).toBe(code)
    expect(FakeSocket.instances).toHaveLength(0)
  })

  it('refuses outside HTTPS before asking for the microphone', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    const mic = microphone()
    await mic.start(DEFAULT_MIC_SETTINGS)
    expect(mic.state.value.error?.code).toBe('MIC-HTTPS')
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('falls back to HTTP chunks when the WebSocket is blocked', async () => {
    FakeSocket.reply = (s) => s.close() // a proxy drops the upgrade
    const posts: { seq: string | null; stream: string | null; bytes: number; format: string | null }[] = []
    server.use(
      http.post('/api/sessions/:id/audio/chunks', async ({ request }) => {
        const url = new URL(request.url)
        posts.push({ seq: url.searchParams.get('seq'), stream: url.searchParams.get('stream'), bytes: (await request.arrayBuffer()).byteLength, format: request.headers.get('x-audio-format') })
        return HttpResponse.json({ speaking: posts.length > 1, role: 'candidate', notices: ['TURN-MISSING'] })
      }),
    )
    const mic = microphone()
    await mic.start(DEFAULT_MIC_SETTINGS)
    expect(mic.state.value).toMatchObject({ status: 'on', transport: 'http' })
    expect(mic.state.value.notices.map((n) => n.code)).toEqual(['WS-BLOCKED', 'TURN-MISSING'])
    chunk()
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[0]).toMatchObject({ seq: '0', bytes: 0, format: 'pcm16;rate=16000' })
    expect(posts[1]).toMatchObject({ seq: '1', bytes: 3200, stream: posts[0]!.stream })
    await waitFor(() => expect(mic.state.value.speaking).toBe(true))
  })

  it("stops on the server's refusal without falling back", async () => {
    FakeSocket.reply = (s) => s.message({ type: 'error', code: 'NO-CONSENT', message: '녹음 동의가 없는 면접입니다.' })
    const fallback = vi.fn(() => HttpResponse.json({}))
    server.use(http.post('/api/sessions/:id/audio/chunks', fallback))
    const mic = microphone()
    await mic.start(DEFAULT_MIC_SETTINGS)
    expect(mic.state.value.error).toMatchObject({ code: 'NO-CONSENT', stop: true })
    expect(fallback).not.toHaveBeenCalled()
    expect(track.stop).toHaveBeenCalled()
  })
})

// --- the panel ------------------------------------------------------------------------------------

function renderPanel(props: { manual: boolean }, onQuestion = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Host = defineComponent(() => () =>
    h(TooltipProvider, { delayDuration: 0 }, () => h(MicPanel, { sessionId: SESSION, manual: props.manual, status: null, onQuestion })),
  )
  return render(Host, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
}

describe('microphone panel', () => {
  it('keeps the microphone off without recording consent and says why', () => {
    renderPanel({ manual: true })
    expect(screen.getByTestId('mic-toggle')).toBeDisabled()
    expect(screen.getByTestId('mic-problem-NO-CONSENT')).toHaveTextContent('NO-CONSENT')
  })

  it('switches to 질문 중 with Alt+1 and records a question asked aloud when going back with Alt+2', async () => {
    const user = userEvent.setup()
    const roles: string[] = []
    const asked = { id: 'qa-9', session_id: SESSION, seq: 4, question: '그때 데이터는 어디서 얻었나요?', question_source: 'interviewer', answer_deidentified: null, asked_at: null, answered_at: null, created_at: '' }
    server.use(
      http.post('/api/sessions/:id/live/role', async ({ request }) => {
        const { role } = (await request.json()) as { role: string }
        roles.push(role)
        return HttpResponse.json({ role, qa_item: role === 'candidate' ? asked : null })
      }),
    )
    const onQuestion = vi.fn()
    renderPanel({ manual: false }, onQuestion)
    await user.click(screen.getByTestId('mic-toggle'))
    await waitFor(() => expect(screen.getByTestId('mic-transport')).toHaveTextContent('WebSocket'))
    expect(screen.getByTestId('role-candidate')).toHaveAttribute('aria-checked', 'true')

    await user.keyboard('{Alt>}1{/Alt}')
    await waitFor(() => expect(screen.getByTestId('role-interviewer')).toHaveAttribute('aria-checked', 'true'))
    await user.keyboard('{Alt>}2{/Alt}')
    await waitFor(() => expect(onQuestion).toHaveBeenCalledWith(asked))
    expect(roles).toEqual(['interviewer', 'candidate'])
  })
})
