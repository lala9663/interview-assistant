import { describe, expect, it } from 'vitest'

import type { FollowUpEvent } from '@/api/types'

import { followUpReducer, initialFollowUps, type FollowUpState } from './follow-ups'

const run = (state: FollowUpState, events: FollowUpEvent[]) => events.reduce((s, event) => followUpReducer(s, { type: 'event', event }), state)

describe('followUpReducer', () => {
  it('builds suggestions from streamed deltas', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [
      { event: 'batch.start', data: { batch_id: 'b1', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p' } },
      { event: 'suggestion.start', data: { batch_id: 'b1', suggestion_id: 's1', index: 0, competency: '협업' } },
      { event: 'suggestion.delta', data: { batch_id: 'b1', suggestion_id: 's1', text: '어떻게 ' } },
      { event: 'suggestion.delta', data: { batch_id: 'b1', suggestion_id: 's1', text: '설득했나요?' } },
    ])
    expect(s.status).toBe('streaming')
    expect(s.suggestions).toEqual([
      { id: 's1', index: 0, competency: '협업', text: '어떻게 설득했나요?', done: false, rationale: null, grounding: null },
    ])
    s = run(s, [
      { event: 'suggestion.done', data: { batch_id: 'b1', suggestion_id: 's1', index: 0, competency: '협업', question: '어떻게 설득했나요?', rationale: '근거', grounding: '인용' } },
      { event: 'batch.done', data: { batch_id: 'b1' } },
    ])
    expect(s.status).toBe('done')
    expect(s.suggestions[0]).toMatchObject({ done: true, rationale: '근거', grounding: '인용' })
    expect(s.used).toBeNull()
  })

  it('ignores events from a stale batch after a new request', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [{ event: 'batch.start', data: { batch_id: 'old', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p' } }])
    s = followUpReducer(s, { type: 'request', qaItemId: 'qa-2' })
    s = run(s, [
      { event: 'suggestion.start', data: { batch_id: 'old', suggestion_id: 'x', index: 0, competency: 'c' } },
      { event: 'batch.start', data: { batch_id: 'old', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p' } },
    ])
    expect(s.suggestions).toEqual([])
    expect(s.batchId).toBeNull()
  })

  it('marks the suggestion the interviewer used', () => {
    const s = followUpReducer(initialFollowUps, { type: 'used', suggestionId: 's2', seq: 4, edited: true })
    expect(s.used).toEqual({ suggestionId: 's2', seq: 4, edited: true })
  })
})
