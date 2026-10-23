import { useCallback, useEffect, useReducer, useRef } from 'react'

import { streamEvents } from '@/api/sse'
import type { FollowUpEvent } from '@/api/types'

export interface Suggestion {
  id: string
  index: number
  competency: string
  text: string
  done: boolean
  rationale: string | null
  grounding: string | null
}

export interface FollowUpState {
  batchId: string | null
  qaItemId: string | null
  status: 'idle' | 'streaming' | 'done' | 'error'
  suggestions: Suggestion[]
  model: string | null
  error: string | null
  /** suggestion the interviewer turned into a question, and the QA seq it became */
  used: { suggestionId: string; seq: number; edited: boolean } | null
}

export type FollowUpAction =
  | { type: 'request'; qaItemId: string }
  | { type: 'event'; event: FollowUpEvent }
  | { type: 'failed'; message: string }
  | { type: 'used'; suggestionId: string; seq: number; edited: boolean }
  | { type: 'reset' }

export const initialFollowUps: FollowUpState = {
  batchId: null,
  qaItemId: null,
  status: 'idle',
  suggestions: [],
  model: null,
  error: null,
  used: null,
}

/** Pure reducer over the follow-up SSE events (unit-tested). */
export function followUpReducer(state: FollowUpState, action: FollowUpAction): FollowUpState {
  switch (action.type) {
    case 'request':
      return { ...initialFollowUps, qaItemId: action.qaItemId, status: 'streaming' }
    case 'reset':
      return initialFollowUps
    case 'failed':
      return { ...state, status: 'error', error: action.message }
    case 'used':
      return { ...state, used: { suggestionId: action.suggestionId, seq: action.seq, edited: action.edited } }
    case 'event': {
      const e = action.event
      switch (e.event) {
        case 'batch.start':
          if (e.data.qa_item_id !== state.qaItemId) return state
          return { ...state, batchId: e.data.batch_id, model: e.data.model }
        case 'suggestion.start':
          if (e.data.batch_id !== state.batchId) return state
          return {
            ...state,
            suggestions: [
              ...state.suggestions,
              { id: e.data.suggestion_id, index: e.data.index, competency: e.data.competency, text: '', done: false, rationale: null, grounding: null },
            ],
          }
        case 'suggestion.delta':
          if (e.data.batch_id !== state.batchId) return state
          return {
            ...state,
            suggestions: state.suggestions.map((s) => (s.id === e.data.suggestion_id ? { ...s, text: s.text + e.data.text } : s)),
          }
        case 'suggestion.done':
          if (e.data.batch_id !== state.batchId) return state
          return {
            ...state,
            suggestions: state.suggestions.map((s) =>
              s.id === e.data.suggestion_id
                ? { ...s, text: e.data.question, done: true, rationale: e.data.rationale, grounding: e.data.grounding, competency: e.data.competency }
                : s,
            ),
          }
        case 'batch.done':
          if (e.data.batch_id !== state.batchId) return state
          return { ...state, status: 'done' }
        case 'error':
          return { ...state, status: 'error', error: e.data.message }
      }
    }
  }
  return state
}

/** Streams follow-up suggestions (POST /api/sessions/{id}/follow-ups, SSE). */
export function useFollowUps(sessionId: string) {
  const [state, dispatch] = useReducer(followUpReducer, initialFollowUps)
  const abortRef = useRef<AbortController | null>(null)

  const request = useCallback(
    async (qaItemId: string) => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      dispatch({ type: 'request', qaItemId })
      try {
        for await (const event of streamEvents<FollowUpEvent>(`/sessions/${sessionId}/follow-ups`, {
          method: 'POST',
          body: JSON.stringify({ qa_item_id: qaItemId }),
          signal: ctrl.signal,
        })) {
          dispatch({ type: 'event', event })
        }
      } catch (err) {
        if (ctrl.signal.aborted) return
        dispatch({ type: 'failed', message: err instanceof Error ? err.message : '제안을 불러오지 못했습니다.' })
      }
    },
    [sessionId],
  )

  const markUsed = useCallback((suggestionId: string, seq: number, edited: boolean) => {
    dispatch({ type: 'used', suggestionId, seq, edited })
  }, [])

  useEffect(() => () => abortRef.current?.abort(), [])

  return { state, request, markUsed }
}
