import { onScopeDispose, shallowRef } from 'vue'

import { streamEvents } from '@/api/sse'
import type { FollowUpEvent, SuggestionSource } from '@/api/types'
import { frameBatch } from '@/lib/frame'

export interface Suggestion {
  id: string
  index: number
  competency: string
  /** question bank (approved, shown first) or AI */
  source: SuggestionSource
  text: string
  done: boolean
  rationale: string | null
  grounding: string | null
  /** shown, duplicate check still running: not usable yet */
  checking: boolean
  /** taken back after it was shown: the asked (or shown) question it means the same as */
  duplicateOf: string | null
}

export interface FollowUpState {
  batchId: string | null
  qaItemId: string | null
  status: 'idle' | 'streaming' | 'done' | 'error'
  suggestions: Suggestion[]
  model: string | null
  /** the embedding model the question bank was searched with (null: no search) */
  retrievalModel: string | null
  /** AI candidates taken back because they meant the same as a question already asked (their cards stay, folded) */
  discarded: { question: string; duplicateOf: string }[]
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
  retrievalModel: null,
  discarded: [],
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
          return { ...state, batchId: e.data.batch_id, model: e.data.model, retrievalModel: e.data.retrieval_model ?? null }
        case 'suggestion.start':
          if (e.data.batch_id !== state.batchId) return state
          return {
            ...state,
            suggestions: [
              ...state.suggestions,
              {
                id: e.data.suggestion_id,
                index: e.data.index,
                competency: e.data.competency,
                source: e.data.source ?? 'ai',
                text: '',
                done: false,
                rationale: null,
                grounding: null,
                checking: false,
                duplicateOf: null,
              },
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
                ? {
                    ...s,
                    text: e.data.question,
                    done: true,
                    rationale: e.data.rationale,
                    grounding: e.data.grounding,
                    competency: e.data.competency,
                    checking: e.data.checking ?? false,
                  }
                : s,
            ),
          }
        case 'suggestion.checked':
          if (e.data.batch_id !== state.batchId) return state
          return { ...state, suggestions: state.suggestions.map((s) => (s.id === e.data.suggestion_id ? { ...s, checking: false } : s)) }
        case 'suggestion.discarded': {
          if (e.data.batch_id !== state.batchId) return state
          const gone = state.suggestions.find((s) => s.id === e.data.suggestion_id)
          return {
            ...state,
            // The card stays where it was, folded and marked, so the list does not jump under the interviewer.
            suggestions: state.suggestions.map((s) =>
              s.id === e.data.suggestion_id ? { ...s, done: true, checking: false, duplicateOf: e.data.duplicate_of } : s,
            ),
            discarded: [...state.discarded, { question: gone?.text ?? '', duplicateOf: e.data.duplicate_of }],
          }
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
  // `current` is always up to date (the reducer filters stale batches with it); `state` renders once per frame.
  let current = initialFollowUps
  const state = shallowRef<FollowUpState>(current)
  const frame = frameBatch(() => (state.value = current))
  const dispatch = (action: FollowUpAction) => {
    current = followUpReducer(current, action)
    if (action.type === 'event') frame.schedule()
    else frame.flush()
  }
  let abort: AbortController | null = null

  async function request(qaItemId: string) {
    abort?.abort()
    const ctrl = new AbortController()
    abort = ctrl
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
  }

  function markUsed(suggestionId: string, seq: number, edited: boolean) {
    dispatch({ type: 'used', suggestionId, seq, edited })
  }

  onScopeDispose(() => abort?.abort())

  return { state, request, markUsed }
}
