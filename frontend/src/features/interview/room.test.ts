import { describe, expect, it } from 'vitest'

import type { QAItem, TranscriptSegment } from '@/api/types'
import { clockPhase, formatClock } from '@/lib/session-clock'
import { MINUTE } from '@/lib/time'

import { roomLayout } from './room-layout'
import { buildBlocks, buildTurns } from './transcript-utils'

const qa = (seq: number, extra: Partial<QAItem> = {}): QAItem => ({
  id: `q${seq}`,
  session_id: 's',
  seq,
  question: `질문 ${seq}`,
  question_source: 'preset',
  answer_deidentified: null,
  asked_at: null,
  answered_at: null,
  created_at: '2026-10-30T00:00:00Z',
  ...extra,
})
const seg = (id: string, qaId: string | null, speaker: TranscriptSegment['speaker'], text = id): TranscriptSegment => ({
  segment_id: id,
  qa_item_id: qaId,
  speaker,
  text,
  is_final: true,
  start_ms: 0,
  end_ms: 1,
})

describe('room layout by width', () => {
  it('three columns from 1080 px (1366 at 125%), two from 760 px, one below; unmeasured is the full layout', () => {
    expect(roomLayout(null)).toBe('wide')
    expect(roomLayout(1536)).toBe('wide')
    expect(roomLayout(1093)).toBe('wide') // 1366 at 125%
    expect(roomLayout(1024)).toBe('medium') // 1280 at 125%, 1536 at 150%
    expect(roomLayout(853)).toBe('medium') // 1280 at 150%
    expect(roomLayout(700)).toBe('narrow')
  })
})

describe('session clock', () => {
  it('plans an hour, marks overtime, and calls two hours open "left open"', () => {
    expect(formatClock(42 * MINUTE)).toBe('60분 중 42분')
    expect(clockPhase(60 * MINUTE)).toBe('on_time')
    expect(formatClock(72 * MINUTE)).toBe('1시간 12분 (12분 초과)')
    expect(clockPhase(72 * MINUTE)).toBe('over')
    expect(clockPhase(119 * MINUTE)).toBe('over')
    expect(clockPhase(120 * MINUTE)).toBe('long_open')
    expect(formatClock((37 * 60 + 46) * MINUTE)).toBe('37시간 46분째')
  })
})

describe('buildBlocks', () => {
  it('groups turns under their question and gives an unheard question its place by number', () => {
    const items = [qa(1), qa(2, { answer_deidentified: '수기 답변' }), qa(3)]
    const turns = buildTurns([seg('a', null, 'candidate'), seg('b', 'q1', 'interviewer'), seg('c', 'q1', 'candidate'), seg('d', 'q3', 'interviewer')], null)
    const blocks = buildBlocks(turns, items)
    expect(blocks.map((b) => [b.qa?.seq ?? null, b.turns.length])).toEqual([
      [null, 1],
      [1, 2],
      [2, 0], // picked while the transcription was down: still listed, in order
      [3, 1],
    ])
    expect(blocks.every((b) => !b.continued)).toBe(true)
  })

  it('does not repeat a question header when its turns come back later', () => {
    const turns = buildTurns([seg('a', 'q1', 'candidate'), seg('b', null, 'interviewer'), seg('c', 'q1', 'candidate')], null)
    expect(buildBlocks(turns, [qa(1)]).map((b) => b.continued)).toEqual([false, false, true])
  })
})
