import { describe, expect, it } from 'vitest'

import type { FollowUpEvent } from '@/api/types'

import { followUpReducer, initialFollowUps, type FollowUpState } from './follow-ups'

const run = (state: FollowUpState, events: FollowUpEvent[]) => events.reduce((s, event) => followUpReducer(s, { type: 'event', event }), state)

describe('followUpReducer', () => {
  it('builds suggestions from streamed deltas', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [
      { event: 'batch.start', data: { batch_id: 'b1', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p', retrieval_model: null } },
      { event: 'suggestion.start', data: { batch_id: 'b1', suggestion_id: 's1', index: 0, competency: '협업', source: 'ai' } },
      { event: 'suggestion.delta', data: { batch_id: 'b1', suggestion_id: 's1', text: '어떻게 ' } },
      { event: 'suggestion.delta', data: { batch_id: 'b1', suggestion_id: 's1', text: '설득했나요?' } },
    ])
    expect(s.status).toBe('streaming')
    expect(s.suggestions).toEqual([
      {
        id: 's1',
        index: 0,
        competency: '협업',
        source: 'ai',
        text: '어떻게 설득했나요?',
        done: false,
        rationale: null,
        grounding: null,
        checking: false,
        duplicateOf: null,
      },
    ])
    s = run(s, [
      {
        event: 'suggestion.done',
        data: { batch_id: 'b1', suggestion_id: 's1', index: 0, competency: '협업', source: 'ai', question: '어떻게 설득했나요?', rationale: '근거', grounding: '인용' },
      },
      { event: 'batch.done', data: { batch_id: 'b1' } },
    ])
    expect(s.status).toBe('done')
    expect(s.suggestions[0]).toMatchObject({ done: true, rationale: '근거', grounding: '인용' })
    expect(s.used).toBeNull()
  })

  it('ignores events from a stale batch after a new request', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [{ event: 'batch.start', data: { batch_id: 'old', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p', retrieval_model: null } }])
    s = followUpReducer(s, { type: 'request', qaItemId: 'qa-2' })
    s = run(s, [
      { event: 'suggestion.start', data: { batch_id: 'old', suggestion_id: 'x', index: 0, competency: 'c', source: 'ai' } },
      { event: 'batch.start', data: { batch_id: 'old', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p', retrieval_model: null } },
    ])
    expect(s.suggestions).toEqual([])
    expect(s.batchId).toBeNull()
  })

  it('keeps an AI suggestion unusable until its duplicate check passes', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [
      { event: 'batch.start', data: { batch_id: 'b1', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p', retrieval_model: 'BAAI/bge-m3-int8' } },
      { event: 'suggestion.start', data: { batch_id: 'b1', suggestion_id: 'a1', index: 0, competency: '공정', source: 'ai' } },
      {
        event: 'suggestion.done',
        data: { batch_id: 'b1', suggestion_id: 'a1', index: 0, competency: '공정', source: 'ai', question: '새 질문', rationale: 'r', grounding: 'g', checking: true },
      },
    ])
    expect(s.suggestions[0]).toMatchObject({ done: true, checking: true, duplicateOf: null })
    s = run(s, [{ event: 'suggestion.checked', data: { batch_id: 'b1', suggestion_id: 'a1' } }])
    expect(s.suggestions[0]).toMatchObject({ checking: false, duplicateOf: null })
  })

  it('shows question-bank suggestions first and folds an AI duplicate found after it was shown', () => {
    let s = followUpReducer(initialFollowUps, { type: 'request', qaItemId: 'qa-1' })
    s = run(s, [
      { event: 'batch.start', data: { batch_id: 'b1', qa_item_id: 'qa-1', model: 'm', prompt_version: 'p', retrieval_model: 'BAAI/bge-m3' } },
      { event: 'suggestion.start', data: { batch_id: 'b1', suggestion_id: 'bank', index: 0, competency: '공정', source: 'bank' } },
      {
        event: 'suggestion.done',
        data: { batch_id: 'b1', suggestion_id: 'bank', index: 0, competency: '공정', source: 'bank', question: '은행 질문', rationale: '의도', grounding: '인용', bank_item_id: 'q1', score: 0.7 },
      },
      { event: 'suggestion.start', data: { batch_id: 'b1', suggestion_id: 'ai', index: 1, competency: '공정', source: 'ai' } },
      { event: 'suggestion.delta', data: { batch_id: 'b1', suggestion_id: 'ai', text: '이미 한 질문' } },
      {
        event: 'suggestion.done',
        data: { batch_id: 'b1', suggestion_id: 'ai', index: 1, competency: '공정', source: 'ai', question: '이미 한 질문', rationale: 'r', grounding: 'g', checking: true },
      },
      { event: 'suggestion.discarded', data: { batch_id: 'b1', suggestion_id: 'ai', reason: 'duplicate', duplicate_of: '이미 한 질문', similarity: 0.97 } },
      { event: 'batch.done', data: { batch_id: 'b1', discarded: 1 } },
    ])
    expect(s.retrievalModel).toBe('BAAI/bge-m3')
    // The bank card is usable at once; the AI card stays in place, marked, never usable.
    expect(s.suggestions.map((x) => [x.id, x.source, x.done, x.checking, x.duplicateOf])).toEqual([
      ['bank', 'bank', true, false, null],
      ['ai', 'ai', true, false, '이미 한 질문'],
    ])
    expect(s.discarded).toEqual([{ question: '이미 한 질문', duplicateOf: '이미 한 질문' }])
  })

  it('marks the suggestion the interviewer used', () => {
    const s = followUpReducer(initialFollowUps, { type: 'used', suggestionId: 's2', seq: 4, edited: true })
    expect(s.used).toEqual({ suggestionId: 's2', seq: 4, edited: true })
  })
})
