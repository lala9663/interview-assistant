/** Week grid geometry: 09:00–19:00 KST, 1px per minute. */
export const DAY_START = 9 * 60
export const DAY_END = 19 * 60
export const PX_PER_MIN = 1
export const HOURS = Array.from({ length: (DAY_END - DAY_START) / 60 + 1 }, (_, i) => DAY_START / 60 + i)

/** Availability is edited in 30-minute steps; a click on an empty slot marks an hour. */
export const STEP = 30
export const NEW_BLOCK_MINUTES = 60

/** Interviewer colors follow the entity (global order), slots 2.. so slot 1 (blue) stays the AI/brand color. */
export const colorOf = (index: number) => `var(--series-${(index % 5) + 2})`

/** Minutes of a KST day. */
export interface Range {
  start: number
  end: number
}

/** What a drag on a block changes: its top edge, its bottom edge or the whole block. */
export type DragMode = 'start' | 'end' | 'move'

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
const toStep = (minutes: number) => Math.round(minutes / STEP) * STEP

/**
 * A block after its edge (or the whole block) was dragged by `delta` minutes: the moved edge lands on
 * the 30-minute grid, the block stays at least 30 minutes long and inside 09:00–19:00. Less than
 * half a step changes nothing, so a click never nudges a block.
 */
export function dragRange(range: Range, mode: DragMode, delta: number): Range {
  if (Math.round(delta / STEP) === 0) return range
  if (mode === 'start') return { start: clamp(toStep(range.start + delta), DAY_START, range.end - STEP), end: range.end }
  if (mode === 'end') return { start: range.start, end: clamp(toStep(range.end + delta), range.start + STEP, DAY_END) }
  const length = Math.min(range.end - range.start, DAY_END - DAY_START)
  const start = clamp(toStep(range.start + delta), DAY_START, DAY_END - length)
  return { start, end: start + length }
}

/** The 30-minute slot a point in the day falls in. */
export function slotAt(minute: number): Range {
  const start = clamp(Math.floor(minute / STEP) * STEP, DAY_START, DAY_END - STEP)
  return { start, end: start + STEP }
}

/**
 * A new block from pressing at `from` and letting go at `to` (minutes of the day): every slot between
 * them. A click (`from === to`) marks an hour from its slot, pulled back so it ends by 19:00.
 */
export function paintRange(from: number, to: number): Range {
  if (from === to) {
    const start = Math.min(slotAt(from).start, DAY_END - NEW_BLOCK_MINUTES)
    return { start, end: start + NEW_BLOCK_MINUTES }
  }
  return { start: slotAt(Math.min(from, to)).start, end: slotAt(Math.max(from, to)).end }
}
