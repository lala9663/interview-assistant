import { describe, expect, it } from 'vitest'

import { readSse } from '@/api/sse'

import { splitTokens } from './labels'
import { commonFreeIntervals, subtractIntervals, suggestSlots } from './schedule'
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
