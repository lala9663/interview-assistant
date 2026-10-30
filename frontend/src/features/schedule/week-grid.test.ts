import { cleanup, fireEvent, screen, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Availability, Interviewer } from '@/api/types'
import { getDb } from '@/mocks/db'
import { formatDateShort, kstDate, startOfKstWeek } from '@/lib/time'
import { renderPlain, renderRoute } from '@/test/render'

import { DAY_END, DAY_START, dragRange, paintRange, slotAt } from './grid'
import SchedulePage from './SchedulePage.vue'
import WeekGrid from './WeekGrid.vue'

const at = (h: number, m = 0) => h * 60 + m

describe('availability editing geometry', () => {
  const block = { start: at(10), end: at(11) }

  it('drags an edge in 30-minute steps, never below 30 minutes or outside 09–19', () => {
    expect(dragRange(block, 'end', 95)).toEqual({ start: at(10), end: at(12, 30) })
    expect(dragRange(block, 'end', 14)).toEqual(block) // under half a step: a click, not a resize
    expect(dragRange(block, 'end', -200)).toEqual({ start: at(10), end: at(10, 30) })
    expect(dragRange(block, 'end', 600)).toEqual({ start: at(10), end: DAY_END })
    expect(dragRange(block, 'start', -50)).toEqual({ start: at(9, 0), end: at(11) })
    expect(dragRange(block, 'start', -300)).toEqual({ start: DAY_START, end: at(11) })
    expect(dragRange(block, 'start', 90)).toEqual({ start: at(10, 30), end: at(11) })
  })

  it('moves a whole block keeping its length, inside the day', () => {
    expect(dragRange(block, 'move', 40)).toEqual({ start: at(10, 30), end: at(11, 30) })
    expect(dragRange(block, 'move', 900)).toEqual({ start: at(18), end: DAY_END })
    expect(dragRange(block, 'move', -900)).toEqual({ start: DAY_START, end: at(10) })
  })

  it('marks an hour on a click and the slots between press and release on a drag', () => {
    expect(paintRange(at(13, 10), at(13, 10))).toEqual({ start: at(13), end: at(14) })
    expect(paintRange(at(18, 40), at(18, 40))).toEqual({ start: at(18), end: DAY_END })
    expect(paintRange(at(15, 5), at(16, 40))).toEqual({ start: at(15), end: at(17) })
    expect(paintRange(at(16, 40), at(15, 5))).toEqual({ start: at(15), end: at(17) })
    expect(slotAt(at(10, 59))).toEqual({ start: at(10, 30), end: at(11) })
  })
})

const monday = kstDate(2027, 3, 1)
const person = (id: string, name: string): Interviewer => ({
  id,
  employee_no: id,
  name,
  job_family: '공정개발',
  department: null,
  is_admin: false,
  created_at: '2026-01-01T00:00:00.000Z',
})
const block = (id: string, who: string, from: number, to: number): Availability => ({
  id,
  interviewer_id: who,
  start_at: new Date(monday.getTime() + from * 60_000).toISOString(),
  end_at: new Date(monday.getTime() + to * 60_000).toISOString(),
  source: 'manual',
  created_at: '2026-01-01T00:00:00.000Z',
})

function renderGrid() {
  const on = { onCreate: vi.fn(), onUpdate: vi.fn(), onClear: vi.fn(), onRemove: vi.fn() }
  renderPlain(WeekGrid, {
    weekStart: monday,
    interviewers: [person('me', '김서연'), person('o', '박준호')],
    selected: ['me', 'o'],
    availabilities: [block('m1', 'me', at(10), at(11)), block('m2', 'me', at(12, 30), at(13, 30)), block('o1', 'o', at(10), at(12))],
    minCount: 2,
    highlight: null,
    editFor: 'me',
    ...on,
  })
  // jsdom lays nothing out: a column's top is y = 0, so clientY is minutes after 09:00.
  return { on, day: screen.getByRole('group', { name: formatDateShort(monday) }), y: (minute: number) => minute - DAY_START }
}
const mine = () => screen.getAllByRole('button', { name: /^김서연 가용/ }).map((b) => b.getAttribute('aria-label'))

describe('WeekGrid editing', () => {
  it('grows a block by dragging its bottom edge and shows it merged with the block it reaches', async () => {
    const { on, y } = renderGrid()
    const first = screen.getByRole('button', { name: '김서연 가용 10:00부터 11:00까지' })
    await fireEvent.pointerDown(first.querySelector('[data-edge="end"]')!, { clientY: y(at(11)), pointerId: 1 })
    await fireEvent.pointerMove(first, { clientY: y(at(12, 35)), pointerId: 1 })
    // 10:00–12:30 touches 12:30–13:30: one box while dragging, never two on top of each other.
    expect(mine()).toEqual(['김서연 가용 10:00부터 13:30까지'])
    expect(screen.getByText('10:00–12:30')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^박준호 가용/ })).toHaveLength(1)
    await fireEvent.pointerUp(first, { clientY: y(at(12, 35)), pointerId: 1 })
    expect(on.onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), kstDate(2027, 3, 1, 10), kstDate(2027, 3, 1, 12, 30))

    // The top edge, shrinking: 10:00 → 10:30.
    await fireEvent.pointerDown(first.querySelector('[data-edge="start"]')!, { clientY: y(at(10)), pointerId: 2 })
    await fireEvent.pointerMove(first, { clientY: y(at(10, 28)), pointerId: 2 })
    await fireEvent.pointerUp(first, { clientY: y(at(10, 28)), pointerId: 2 })
    expect(on.onUpdate).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'm1' }), kstDate(2027, 3, 1, 10, 30), kstDate(2027, 3, 1, 11))
    expect(on.onCreate).not.toHaveBeenCalled()
  })

  it('adds an hour on a click on empty time, or the dragged span', async () => {
    const { on, day, y } = renderGrid()
    await fireEvent.pointerDown(day, { clientY: y(at(15, 10)), pointerId: 1 })
    await fireEvent.pointerUp(day, { clientY: y(at(15, 10)), pointerId: 1 })
    expect(on.onCreate).toHaveBeenLastCalledWith(kstDate(2027, 3, 1, 15), kstDate(2027, 3, 1, 16))

    await fireEvent.pointerDown(day, { clientY: y(at(15, 5)), pointerId: 2 })
    await fireEvent.pointerMove(day, { clientY: y(at(16, 40)), pointerId: 2 })
    expect(mine()).toContain('김서연 가용 15:00부터 17:00까지')
    await fireEvent.pointerUp(day, { clientY: y(at(16, 40)), pointerId: 2 })
    expect(on.onCreate).toHaveBeenLastCalledWith(kstDate(2027, 3, 1, 15), kstDate(2027, 3, 1, 17))
  })

  it('resizes and moves with the keyboard, saving once the keys stop', async () => {
    const { on } = renderGrid()
    const first = screen.getByRole('button', { name: '김서연 가용 10:00부터 11:00까지' })
    first.focus()
    await fireEvent.keyDown(first, { key: 'ArrowDown', shiftKey: true })
    await fireEvent.keyDown(first, { key: 'ArrowDown', shiftKey: true })
    expect(first).toHaveAccessibleName('김서연 가용 10:00부터 12:00까지')
    await fireEvent.keyDown(first, { key: 'ArrowUp' })
    expect(screen.getByText('09:30–11:30', { selector: '[aria-live]' })).toBeInTheDocument()
    expect(on.onUpdate).not.toHaveBeenCalled()
    await fireEvent.blur(first)
    expect(on.onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), kstDate(2027, 3, 1, 9, 30), kstDate(2027, 3, 1, 11, 30))

    await fireEvent.keyDown(first, { key: 'Delete' })
    expect(on.onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }))
  })

  it('opens a menu on a click on a block to clear the 30 minutes clicked or delete the block', async () => {
    const user = userEvent.setup()
    const { on, y } = renderGrid()
    const second = screen.getByRole('button', { name: '김서연 가용 12:30부터 13:30까지' })
    await fireEvent.pointerDown(second, { clientY: y(at(13, 10)), pointerId: 1 })
    await fireEvent.pointerUp(second, { clientY: y(at(13, 10)), pointerId: 1 })
    const menu = await screen.findByRole('dialog')
    expect(menu).toHaveTextContent('내 가용 12:30–13:30')
    await user.click(within(menu).getByRole('button', { name: '13:00–13:30만 비우기' }))
    expect(on.onClear).toHaveBeenCalledWith(expect.objectContaining({ id: 'm2' }), kstDate(2027, 3, 1, 13), kstDate(2027, 3, 1, 13, 30))
    expect(on.onUpdate).not.toHaveBeenCalled()

    await fireEvent.pointerDown(second, { clientY: y(at(12, 40)), pointerId: 2 })
    await fireEvent.pointerUp(second, { clientY: y(at(12, 40)), pointerId: 2 })
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '블록 삭제' }))
    expect(on.onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: 'm2' }))
  })

  it('drops a drag cut short by leaving the page but keeps arrow-key changes, and survives a lost pointer', async () => {
    vi.spyOn(Element.prototype, 'setPointerCapture').mockImplementation(() => {
      throw new DOMException('No active pointer with the given id is found.', 'NotFoundError')
    })
    const { on, y } = renderGrid()
    const first = screen.getByRole('button', { name: '김서연 가용 10:00부터 11:00까지' })
    await fireEvent.pointerDown(first.querySelector('[data-edge="end"]')!, { clientY: y(at(11)), pointerId: 1 })
    await fireEvent.pointerMove(first, { clientY: y(at(12)), pointerId: 1 })
    expect(mine()).toContain('김서연 가용 10:00부터 12:00까지') // no capture, the drag still runs
    cleanup()
    expect(on.onUpdate).not.toHaveBeenCalled()

    const again = renderGrid()
    const block = screen.getByRole('button', { name: '김서연 가용 10:00부터 11:00까지' })
    await fireEvent.keyDown(block, { key: 'ArrowDown', shiftKey: true })
    cleanup()
    expect(again.on.onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }), kstDate(2027, 3, 1, 10), kstDate(2027, 3, 1, 11, 30))
  })

  it('leaves other interviewers’ blocks alone', async () => {
    const { on, y } = renderGrid()
    const other = screen.getByRole('button', { name: '박준호 가용 10:00부터 12:00까지' })
    await fireEvent.pointerDown(other, { clientY: y(at(10, 30)), pointerId: 1 })
    await fireEvent.pointerUp(other, { clientY: y(at(10, 30)), pointerId: 1 })
    await fireEvent.keyDown(other, { key: 'Delete' })
    expect(on.onCreate).not.toHaveBeenCalled()
    expect(on.onRemove).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('면접관 스케줄: marking free time (mock API)', { timeout: 30_000 }, () => {
  it('turns hours marked next to each other into one block', async () => {
    const user = userEvent.setup()
    const db = getDb()
    await renderRoute(SchedulePage, { path: '/schedule', url: '/schedule' })
    await user.click(await screen.findByRole('switch', { name: '내 가용 시간 편집' }))
    // The mock's 김서연 is free 10–12 and 14–17 on Monday of this week.
    const day = screen.getByRole('group', { name: formatDateShort(startOfKstWeek(new Date())) })
    expect(within(day).getByRole('button', { name: '김서연 가용 10:00부터 12:00까지' })).toBeInTheDocument()

    await fireEvent.pointerDown(day, { clientY: at(12) - DAY_START, pointerId: 1 })
    await fireEvent.pointerUp(day, { clientY: at(12) - DAY_START, pointerId: 1 })
    expect(await within(day).findByRole('button', { name: '김서연 가용 10:00부터 13:00까지' })).toBeInTheDocument()
    await fireEvent.pointerDown(day, { clientY: at(13, 15) - DAY_START, pointerId: 2 })
    await fireEvent.pointerUp(day, { clientY: at(13, 15) - DAY_START, pointerId: 2 })
    expect(await within(day).findByRole('button', { name: '김서연 가용 10:00부터 17:00까지' })).toBeInTheDocument()
    expect(within(day).getAllByRole('button', { name: /^김서연 가용/ })).toHaveLength(1)

    const monday = startOfKstWeek(new Date()).getTime()
    const kept = () => db.availabilities.filter((a) => a.interviewer_id === db.me.id && new Date(a.start_at).getTime() - monday < 86_400_000)
    await vi.waitFor(() => expect(kept().map((a) => [a.start_at, a.end_at])).toEqual([[new Date(monday + at(10) * 60_000).toISOString(), new Date(monday + at(17) * 60_000).toISOString()]]))
  })
})
