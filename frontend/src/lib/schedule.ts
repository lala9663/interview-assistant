import type { Availability, ScheduleSuggestion } from '@/api/types'

import { MINUTE } from './time'

export interface Interval {
  start: number
  end: number
}

/** Merge overlapping/touching intervals (ms epoch). */
export function mergeIntervals(list: readonly Interval[]): Interval[] {
  const sorted = [...list].sort((a, b) => a.start - b.start)
  const out: Interval[] = []
  for (const it of sorted) {
    const last = out[out.length - 1]
    if (last && it.start <= last.end) last.end = Math.max(last.end, it.end)
    else out.push({ ...it })
  }
  return out
}

export function availabilityByInterviewer(availabilities: readonly Availability[]): Map<string, Interval[]> {
  const map = new Map<string, Interval[]>()
  for (const a of availabilities) {
    const list = map.get(a.interviewer_id) ?? []
    list.push({ start: new Date(a.start_at).getTime(), end: new Date(a.end_at).getTime() })
    map.set(a.interviewer_id, list)
  }
  for (const [k, v] of map) map.set(k, mergeIntervals(v))
  return map
}

/**
 * Intervals in which at least `minCount` of the given interviewers are free at the same time.
 * Sweep over interval boundaries; result is merged.
 */
export function commonFreeIntervals(
  byInterviewer: Map<string, Interval[]>,
  interviewerIds: readonly string[],
  minCount = interviewerIds.length,
): (Interval & { ids: string[] })[] {
  if (interviewerIds.length === 0 || minCount <= 0) return []
  const points = new Set<number>()
  for (const id of interviewerIds) {
    for (const it of byInterviewer.get(id) ?? []) {
      points.add(it.start)
      points.add(it.end)
    }
  }
  const sorted = [...points].sort((a, b) => a - b)
  const out: (Interval & { ids: string[] })[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i]!
    const end = sorted[i + 1]!
    const mid = (start + end) / 2
    const ids = interviewerIds.filter((id) => (byInterviewer.get(id) ?? []).some((it) => it.start <= mid && mid < it.end))
    if (ids.length < minCount) continue
    const last = out[out.length - 1]
    if (last && last.end === start && sameIds(last.ids, ids)) last.end = end
    else out.push({ start, end, ids })
  }
  return out
}

function sameIds(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((x, i) => x === b[i])
}

/**
 * Candidate slots: within each common-free interval, slots of `durationMinutes` aligned to 30 minutes,
 * earliest first, at most one per interval start hour to keep the list short.
 */
export function suggestSlots(
  byInterviewer: Map<string, Interval[]>,
  interviewerIds: readonly string[],
  durationMinutes: number,
  opts: { minCount?: number; from?: number; to?: number; limit?: number } = {},
): ScheduleSuggestion[] {
  const step = 30 * MINUTE
  const dur = durationMinutes * MINUTE
  const out: ScheduleSuggestion[] = []
  for (const it of commonFreeIntervals(byInterviewer, interviewerIds, opts.minCount)) {
    let t = Math.ceil(Math.max(it.start, opts.from ?? -Infinity) / step) * step
    const end = Math.min(it.end, opts.to ?? Infinity)
    while (t + dur <= end) {
      out.push({ start_at: new Date(t).toISOString(), end_at: new Date(t + dur).toISOString(), interviewer_ids: it.ids })
      t += Math.max(dur, 60 * MINUTE)
    }
  }
  out.sort((a, b) => a.start_at.localeCompare(b.start_at) || b.interviewer_ids.length - a.interviewer_ids.length)
  return out.slice(0, opts.limit ?? 8)
}
