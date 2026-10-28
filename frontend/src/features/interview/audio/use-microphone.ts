import { onScopeDispose, shallowRef } from 'vue'

import { API_BASE } from '@/api/client'
import { endpoints } from '@/api/endpoints'
import type { MicRole, QAItem } from '@/api/types'

import { micErrorCode, problem, type AudioProblem } from './errors'
import type { MicSettings } from './settings'
import { AudioRefused, AudioTransport, type TransportKind } from './transport'

/** Served from public/: converts to 16 kHz PCM16 in 100 ms chunks (see the file). */
export const WORKLET_URL = '/audio/pcm16-worklet.js'

export type MicStatusKind = 'off' | 'starting' | 'on' | 'error'

export interface MicState {
  status: MicStatusKind
  /** input level of the last chunk, 0..1 */
  level: number
  /** the server's VAD hears speech */
  speaking: boolean
  role: MicRole
  transport: TransportKind | null
  /** what stopped the microphone (status 'error') */
  error: AudioProblem | null
  /** degraded but running: WS-BLOCKED, TURN-MISSING ... */
  notices: AudioProblem[]
  source: MicSettings['source'] | null
}

const OFF: MicState = { status: 'off', level: 0, speaking: false, role: 'candidate', transport: null, error: null, notices: [], source: null }

/**
 * The live interview's microphone: getUserMedia (or a bundled sample played into the same graph) ->
 * AudioWorklet (16 kHz PCM16) -> AudioTransport (WebSocket, else HTTP chunks). `setRole` switches
 * 질문 중 / 답변 듣는 중; a question asked aloud comes back as the next QA item (`onQuestion`).
 */
export function useMicrophone(sessionId: string, options: { onQuestion?: (qa: QAItem) => void } = {}) {
  const state = shallowRef<MicState>(OFF)
  const patch = (next: Partial<MicState>) => (state.value = { ...state.value, ...next })
  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let transport: AudioTransport | null = null
  let run = 0 // bumped by stop(): a start still in progress gives up

  function notice(code: string, message?: string) {
    if (state.value.notices.some((n) => n.code === code)) return
    patch({ notices: [...state.value.notices, problem(code, message)] })
  }

  function release() {
    transport?.close()
    transport = null
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    void context?.close().catch(() => {})
    context = null
  }

  function fail(code: string, message?: string) {
    release()
    patch({ status: 'error', error: problem(code, message), level: 0, speaking: false, transport: null })
  }

  /** The sample as a player, started once audio can be sent (nothing of it is lost while connecting). */
  async function samplePlayer(ctx: AudioContext, name: string): Promise<AudioBufferSourceNode> {
    const res = await fetch(new URL(`${API_BASE}/live/audio-samples/${encodeURIComponent(name)}`, window.location.origin), { credentials: 'same-origin' })
    if (!res.ok) throw new AudioRefused('SAMPLE-FAILED')
    const buffer = await ctx.decodeAudioData(await res.arrayBuffer())
    const player = ctx.createBufferSource()
    player.buffer = buffer
    return player
  }

  async function start(settings: MicSettings) {
    if (state.value.status === 'starting' || state.value.status === 'on') return
    const mine = ++run
    const source = settings.source
    patch({ ...OFF, status: 'starting', source })
    const media = navigator.mediaDevices
    if (!window.isSecureContext) return fail('MIC-HTTPS') // getUserMedia and AudioWorklet both need it
    if ((source === 'microphone' && !media?.getUserMedia) || typeof AudioContext === 'undefined' || typeof AudioWorkletNode === 'undefined')
      return fail('MIC-UNSUPPORTED')
    let applied: Record<string, unknown> = {}
    try {
      if (source === 'microphone') {
        stream = await media.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: settings.echoCancellation,
            noiseSuppression: settings.noiseSuppression,
            autoGainControl: settings.autoGainControl,
          },
        })
        applied = { ...(stream.getAudioTracks()[0]?.getSettings?.() ?? {}) }
      }
    } catch (error) {
      return fail(micErrorCode(error))
    }
    if (mine !== run) return release()
    try {
      context = new AudioContext()
      await context.audioWorklet.addModule(WORKLET_URL)
      const player = stream ? null : await samplePlayer(context, settings.sample)
      const input = stream ? context.createMediaStreamSource(stream) : player!
      const node = new AudioWorkletNode(context, 'pcm16', { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1, channelCountMode: 'explicit' })
      const mute = context.createGain()
      mute.gain.value = 0 // the graph must reach the destination to run; nothing is played
      input.connect(node)
      node.connect(mute).connect(context.destination)
      transport = new AudioTransport(
        sessionId,
        { source, constraints: { ...applied, sampleRate: context.sampleRate } },
        {
          onState: (speaking, role) => patch({ speaking, role }),
          onNotice: notice,
          onFatal: (code, message) => fail(code, message),
        },
      )
      await transport.open()
      if (mine !== run) return release()
      for (const code of transport.notices) notice(code)
      node.port.onmessage = (event: MessageEvent<{ pcm: ArrayBuffer; level: number }>) => {
        transport?.send(event.data.pcm)
        if (Math.abs(event.data.level - state.value.level) > 0.02) patch({ level: event.data.level })
      }
      await context.resume()
      player?.start()
      patch({ status: 'on', transport: transport.kind })
    } catch (error) {
      if (mine !== run) return
      if (error instanceof AudioRefused) return fail(error.code, error.message)
      return fail(source === 'sample' ? 'SAMPLE-FAILED' : 'MIC-FAILED')
    }
  }

  function stop() {
    run++
    release()
    patch({ ...OFF })
  }

  /** 질문 중 (interviewer) / 답변 듣는 중 (candidate). */
  async function setRole(role: MicRole) {
    const previous = state.value.role
    patch({ role })
    try {
      const result = await endpoints.setMicRole(sessionId, role)
      if (result.qa_item) options.onQuestion?.(result.qa_item)
    } catch (error) {
      patch({ role: previous })
      throw error
    }
  }

  onScopeDispose(stop)
  return { state, start, stop, setRole }
}
