import { formatDuration, MINUTE } from './time'

/**
 * Planned length of an interview. Rounds carry no length yet, and booking counts every interview as an
 * hour (BOOKED_MINUTES in api/routes/schedule.py), so the room plans for that same hour.
 */
export const DEFAULT_PLANNED_MINUTES = 60

/**
 * Open for this many times its planned length (2 hours by default), a session was most likely left running:
 * no panel interviews that long, and the next booked hour has already begun. The room shows a banner that
 * asks to end it, and the app menu marks it.
 */
export const LONG_OPEN_FACTOR = 2

export type ClockPhase = 'on_time' | 'over' | 'long_open'

export function elapsedMs(startedAt: string | null, now: Date): number {
  return startedAt ? Math.max(0, now.getTime() - new Date(startedAt).getTime()) : 0
}

export function clockPhase(ms: number, planned = DEFAULT_PLANNED_MINUTES): ClockPhase {
  const minutes = ms / MINUTE
  if (minutes >= planned * LONG_OPEN_FACTOR) return 'long_open'
  return minutes > planned ? 'over' : 'on_time'
}

/** "60분 중 42분"; past the plan "72분 (12분 초과)"; left open "37시간 46분째". */
export function formatClock(ms: number, planned = DEFAULT_PLANNED_MINUTES): string {
  const minutes = Math.floor(ms / MINUTE)
  switch (clockPhase(ms, planned)) {
    case 'on_time':
      return `${planned}분 중 ${minutes}분`
    case 'over':
      return `${formatDuration(minutes)} (${formatDuration(minutes - planned)} 초과)`
    case 'long_open':
      return `${formatDuration(minutes)}째`
  }
}
