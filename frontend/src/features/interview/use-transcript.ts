import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { endpoints } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { streamEvents } from '@/api/sse'
import type { SessionDetail, StreamStatus, TranscriptEvent, TranscriptSegment } from '@/api/types'

export type Connection = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'error'

export interface TranscriptState {
  segments: TranscriptSegment[]
  partial: TranscriptSegment | null
  status: StreamStatus | null
  connection: Connection
}

const MAX_RETRIES = 3

/**
 * Live transcript: loads final segments (GET /transcript), then follows the SSE stream.
 * Partial segments replace each other; final segments are appended once (by segment_id).
 * On disconnect it retries with backoff, then gives up so the UI can fall back to manual mode.
 */
export function useTranscript(
  sessionId: string,
  enabled: boolean,
  onAnswered: (e: { qa_item_id: string; answer_deidentified: string; answered_at: string }) => void,
) {
  const qc = useQueryClient()
  const [state, setState] = useState<TranscriptState>({ segments: [], partial: null, status: null, connection: 'idle' })
  const [attempt, setAttempt] = useState(0)
  const onAnsweredRef = useRef(onAnswered)
  useEffect(() => {
    onAnsweredRef.current = onAnswered
  }, [onAnswered])

  useEffect(() => {
    if (!enabled) return
    const ctrl = new AbortController()
    let retryTimer: ReturnType<typeof setTimeout> | undefined

    const apply = (e: TranscriptEvent) => {
      switch (e.event) {
        case 'status':
          setState((s) => ({ ...s, status: e.data }))
          break
        case 'segment.partial':
          setState((s) => ({ ...s, partial: e.data }))
          break
        case 'segment.final':
          setState((s) => ({
            ...s,
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
          onAnsweredRef.current(e.data)
          break
      }
    }

    void (async () => {
      setState((s) => ({ ...s, connection: attempt === 0 ? 'connecting' : 'reconnecting' }))
      try {
        const history = await endpoints.transcript(sessionId, ctrl.signal)
        setState((s) => {
          const ids = new Set(history.segments.map((x) => x.segment_id))
          return { ...s, segments: [...history.segments, ...s.segments.filter((x) => !ids.has(x.segment_id))] }
        })
        let opened = false
        for await (const e of streamEvents<TranscriptEvent>(`/sessions/${sessionId}/transcript/stream`, { signal: ctrl.signal })) {
          if (!opened) {
            opened = true
            setState((s) => ({ ...s, connection: 'open' }))
          }
          apply(e)
        }
        if (ctrl.signal.aborted) return
        throw new Error('stream closed')
      } catch {
        if (ctrl.signal.aborted) return
        if (attempt < MAX_RETRIES) {
          setState((s) => ({ ...s, connection: 'reconnecting', partial: null }))
          retryTimer = setTimeout(() => setAttempt((a) => a + 1), 1000 * 2 ** attempt)
        } else {
          setState((s) => ({ ...s, connection: 'error', partial: null }))
        }
      }
    })()

    return () => {
      ctrl.abort()
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [enabled, sessionId, attempt, qc])

  const reconnect = useCallback(() => setAttempt(0), [])
  return { ...state, reconnect, retrying: attempt }
}
