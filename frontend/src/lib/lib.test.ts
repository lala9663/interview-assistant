import { describe, expect, it } from 'vitest'

import { readSse } from '@/api/sse'
import type { Availability } from '@/api/types'

import { splitTokens } from './labels'
import { absorbInto, clearFrom, commonFreeIntervals, subtractIntervals, suggestSlots } from './schedule'
import { formatElapsed, kstDate, kstDayInput, kstMinuteOfDay, parseKstDayInput, startOfKstWeek } from './time'

const H = 3_600_000
const t0 = kstDate(2026, 10, 26, 0, 0).getTime() // Monday 00:00 KST

describe('schedule', () => {
  const by = new Map([
    ['a', [{ start: t0 + 9 * H, end: t0 + 12 * H }]],
    ['b', [{ start: t0 + 10 * H, end: t0 + 11.5 * H }, { start: t0 + 14 * H, end: t0 + 16 * H }]],
    ['c', [{ start: t0 + 11 * H, end: t0 + 15 * H }]],
  ])

  it('finds time when every selected interviewer is free', () => {
    expect(commonFreeIntervals(by, ['a', 'b'])).toEqual([{ start: t0 + 10 * H, end: t0 + 11.5 * H, ids: ['a', 'b'] }])
    expect(commonFreeIntervals(by, ['a', 'b', 'c'])).toEqual([{ start: t0 + 11 * H, end: t0 + 11.5 * H, ids: ['a', 'b', 'c'] }])
  })

  it('relaxes to a minimum panel size and proposes aligned slots', () => {
    const slots = suggestSlots(by, ['a', 'b', 'c'], 60, { minCount: 2 })
    expect(slots[0]).toEqual({ start_at: new Date(t0 + 10 * H).toISOString(), end_at: new Date(t0 + 11 * H).toISOString(), interviewer_ids: ['a', 'b'] })
    expect(slots.every((s) => s.interviewer_ids.length >= 2)).toBe(true)
  })

  it('takes booked time out of free time', () => {
    const free = [{ start: t0 + 9 * H, end: t0 + 12 * H }]
    expect(subtractIntervals(free, [{ start: t0 + 10 * H, end: t0 + 11 * H }])).toEqual([
      { start: t0 + 9 * H, end: t0 + 10 * H },
      { start: t0 + 11 * H, end: t0 + 12 * H },
    ])
    expect(subtractIntervals(free, [{ start: t0 + 8 * H, end: t0 + 9.5 * H }])).toEqual([{ start: t0 + 9.5 * H, end: t0 + 12 * H }])
    expect(subtractIntervals(free, [{ start: t0 + 13 * H, end: t0 + 14 * H }])).toEqual(free)
    expect(subtractIntervals(free, [{ start: t0 + 8 * H, end: t0 + 13 * H }])).toEqual([])
  })

  const block = (id: string, who: string, from: number, to: number): Availability => ({
    id,
    interviewer_id: who,
    start_at: new Date(t0 + from * H).toISOString(),
    end_at: new Date(t0 + to * H).toISOString(),
    source: 'manual',
    created_at: '2026-10-20T00:00:00.000Z',
  })
  const hours = (list: Availability[]) =>
    list.map((a) => [a.id, a.interviewer_id, (new Date(a.start_at).getTime() - t0) / H, (new Date(a.end_at).getTime() - t0) / H]).sort()

  it('merges a written block with the same interviewer’s blocks it touches, like the server', () => {
    const list = [block('a1', 'a', 10, 11), block('a2', 'a', 12, 13), block('a3', 'a', 15, 16), block('b1', 'b', 10, 11)]
    // An hour after a1 that also touches a2: one block 10–13 under the new id; b's block is not touched.
    expect(hours(absorbInto(list, block('new', 'a', 11, 12)))).toEqual([
      ['a3', 'a', 15, 16],
      ['b1', 'b', 10, 11],
      ['new', 'a', 10, 13],
    ])
    // Clicking 10:30 inside a1 (the bug: two boxes on top of each other) gives one block.
    expect(hours(absorbInto(list, block('new', 'a', 10.5, 11.5))).filter(([, who]) => who === 'a')).toEqual([
      ['a2', 'a', 12, 13],
      ['a3', 'a', 15, 16],
      ['new', 'a', 10, 11.5],
    ])
    // Growing a1 down to 12:00 keeps its id and takes a2 in.
    expect(hours(absorbInto(list, { ...block('a1', 'a', 10, 12) })).filter(([, who]) => who === 'a')).toEqual([
      ['a1', 'a', 10, 13],
      ['a3', 'a', 15, 16],
    ])
    // A gap is not touching.
    expect(absorbInto(list, block('new', 'a', 13.5, 14.5))).toHaveLength(5)
  })

  it('clears part of a block: shorter, split in two or gone', () => {
    const list = [block('a1', 'a', 10, 13), block('b1', 'b', 10, 13)]
    const cut = (from: number, to: number) => ({ start: t0 + from * H, end: t0 + to * H })
    expect(hours(clearFrom(list, 'a1', cut(11, 11.5), 'rest'))).toEqual([
      ['a1', 'a', 10, 11],
      ['b1', 'b', 10, 13],
      ['rest', 'a', 11.5, 13],
    ])
    expect(hours(clearFrom(list, 'a1', cut(12, 14), 'rest'))).toEqual([
      ['a1', 'a', 10, 12],
      ['b1', 'b', 10, 13],
    ])
    expect(hours(clearFrom(list, 'a1', cut(9, 14), 'rest'))).toEqual([['b1', 'b', 10, 13]])
    expect(clearFrom(list, 'nope', cut(9, 14), 'rest')).toEqual(list)
  })
})

describe('time (KST)', () => {
  it('computes KST weeks and minutes regardless of the host zone', () => {
    expect(startOfKstWeek(kstDate(2026, 10, 30, 23, 30)).getTime()).toBe(t0)
    expect(kstMinuteOfDay(kstDate(2026, 10, 26, 14, 5))).toBe(14 * 60 + 5)
    expect(formatElapsed(754_000)).toBe('12:34')
    expect(formatElapsed(3_754_000)).toBe('1:02:34')
  })

  it('reads and writes date inputs as KST days', () => {
    expect(kstDayInput(kstDate(2026, 10, 26, 23, 30))).toBe('2026-10-26')
    expect(kstDayInput(new Date('2026-10-26T15:00:00Z'))).toBe('2026-10-27') // 00:00 KST
    expect(parseKstDayInput('2026-10-26')?.getTime()).toBe(t0)
    expect(parseKstDayInput('')).toBeNull()
  })
})

describe('de-identification tokens', () => {
  it('splits text into plain parts and tokens', () => {
    expect(splitTokens('[회사-1]에서 [지원자]가 말함')).toEqual([
      { text: '[회사-1]', token: true },
      { text: '에서 ', token: false },
      { text: '[지원자]', token: true },
      { text: '가 말함', token: false },
    ])
  })
})

describe('SSE parser', () => {
  it('handles events split across chunks and multi-line data', async () => {
    const enc = new TextEncoder()
    const chunks = ['event: a\nda', 'ta: {"x":1}\n\n: comment\n\nevent: b\r\ndata: line1\r\ndata: line2\r\n\r\n']
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        for (const ch of chunks) c.enqueue(enc.encode(ch))
        c.close()
      },
    })
    const out = []
    for await (const m of readSse(body)) out.push(m)
    expect(out).toEqual([
      { event: 'a', data: '{"x":1}', id: undefined },
      { event: 'b', data: 'line1\nline2', id: undefined },
    ])
  })
})
