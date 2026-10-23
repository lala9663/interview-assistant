import { useQueryClient } from '@tanstack/vue-query'
import { ref, shallowRef, watch } from 'vue'

import { endpoints } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { streamEvents } from '@/api/sse'
import type { SessionDetail, StreamStatus, TranscriptEvent, TranscriptSegment } from '@/api/types'
import { frameBatch } from '@/lib/frame'

export type Connection = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'error'

export interface TranscriptState {
  segments: TranscriptSegment[]
  partial: TranscriptSegment | null
  status: StreamStatus | null
  connection: Connection
}

export type AnsweredEvent = { qa_item_id: string; answer_deidentified: string; answered_at: string }

const MAX_RETRIES = 3

/**
 * Live transcript: loads final segments (GET /transcript), then follows the SSE stream.
 * Partial segments replace each other; final segments are appended once (by segment_id).
 * On disconnect it retries with backoff, then gives up so the UI can fall back to manual mode.
 */
export function useTranscript(sessionId: string, enabled: boolean, onAnswered: (e: AnsweredEvent) => void) {
  const qc = useQueryClient()
  // Events update `current` immediately; `state` (what renders) follows once per frame.
  let current: TranscriptState = { segments: [], partial: null, status: null, connection: 'idle' }
  const state = shallowRef<TranscriptState>(current)
  const frame = frameBatch(() => (state.value = current))
  const attempt = ref(0)
  const patch = (fn: (s: TranscriptState) => Partial<TranscriptState>) => {
    current = { ...current, ...fn(current) }
    frame.schedule()
  }
  const setConnection = (connection: Connection, extra: Partial<TranscriptState> = {}) => {
    current = { ...current, ...extra, connection }
    frame.flush()
  }

  const apply = (e: TranscriptEvent) => {
    switch (e.event) {
      case 'status':
        patch(() => ({ status: e.data }))
        break
      case 'segment.partial':
        patch(() => ({ partial: e.data }))
        break
      case 'segment.final':
        patch((s) => ({
          segments: s.segments.some((x) => x.segment_id === e.data.segment_id) ? s.segments : [...s.segments, e.data],
          partial: s.partial?.segment_id === e.data.segment_id ? null : s.partial,
        }))
        break
      case 'qa.answered':
        qc.setQueryData<SessionDetail>(qk.session(sessionId), (d) =>
          d
            ? {
                ...d,
                qa_items: d.qa_items.map((q) =>
                  q.id === e.data.qa_item_id ? { ...q, answer_deidentified: e.data.answer_deidentified, answered_at: e.data.answered_at } : q,
                ),
              }
            : d,
        )
        onAnswered(e.data)
        break
    }
  }

  watch(
    attempt,
    (n, _prev, onCleanup) => {
      if (!enabled) return
      const ctrl = new AbortController()
      let retryTimer: ReturnType<typeof setTimeout> | undefined
      onCleanup(() => {
        ctrl.abort()
        if (retryTimer) clearTimeout(retryTimer)
      })

      void (async () => {
        setConnection(n === 0 ? 'connecting' : 'reconnecting')
        try {
          const history = await endpoints.transcript(sessionId, ctrl.signal)
          patch((s) => {
            const ids = new Set(history.segments.map((x) => x.segment_id))
            return { segments: [...history.segments, ...s.segments.filter((x) => !ids.has(x.segment_id))] }
          })
          let opened = false
          for await (const e of streamEvents<TranscriptEvent>(`/sessions/${sessionId}/transcript/stream`, { signal: ctrl.signal })) {
            if (!opened) {
              opened = true
              setConnection('open')
            }
            apply(e)
          }
          if (ctrl.signal.aborted) return
          throw new Error('stream closed')
        } catch {
          if (ctrl.signal.aborted) return
          if (n < MAX_RETRIES) {
            setConnection('reconnecting', { partial: null })
            retryTimer = setTimeout(() => (attempt.value = n + 1), 1000 * 2 ** n)
          } else {
            setConnection('error', { partial: null })
          }
        }
      })()
    },
    { immediate: true },
  )

  const reconnect = () => {
    attempt.value = 0
  }
  return { state, reconnect, retrying: attempt }
}
