/**
 * Time helpers. Everything is displayed in Korea time (Asia/Seoul, UTC+9, no DST) whatever the
 * browser zone is, so a "day" or "week" is always a KST day/week.
 */
export const KST_OFFSET_MS = 9 * 60 * 60 * 1000
export const MINUTE = 60 * 1000
export const HOUR = 60 * MINUTE
export const DAY = 24 * HOUR

/** Wall-clock parts of an instant in KST. */
export function kstParts(date: Date | string) {
  const d = new Date(new Date(date).getTime() + KST_OFFSET_MS)
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    weekday: d.getUTCDay(), // 0 = Sunday
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  }
}

/** Instant for a KST wall-clock time. */
export function kstDate(year: number, month: number, day: number, hour = 0, minute = 0): Date {
  return new Date(Date.UTC(year, month - 1, day, hour, minute) - KST_OFFSET_MS)
}

/** Start (00:00 KST) of the KST day containing `date`. */
export function startOfKstDay(date: Date | string): Date {
  const p = kstParts(date)
  return kstDate(p.year, p.month, p.day)
}

/** Monday 00:00 KST of the week containing `date`. */
export function startOfKstWeek(date: Date | string): Date {
  const p = kstParts(date)
  const back = (p.weekday + 6) % 7
  return new Date(startOfKstDay(date).getTime() - back * DAY)
}

export function addMinutes(date: Date | string, minutes: number): Date {
  return new Date(new Date(date).getTime() + minutes * MINUTE)
}

export function addDays(date: Date | string, days: number): Date {
  return new Date(new Date(date).getTime() + days * DAY)
}

export function isSameKstDay(a: Date | string, b: Date | string): boolean {
  return startOfKstDay(a).getTime() === startOfKstDay(b).getTime()
}

/** Minutes since 00:00 KST of that day. */
export function kstMinuteOfDay(date: Date | string): number {
  const p = kstParts(date)
  return p.hour * 60 + p.minute
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

const pad = (n: number) => String(n).padStart(2, '0')

export function formatTime(date: Date | string): string {
  const p = kstParts(date)
  return `${pad(p.hour)}:${pad(p.minute)}`
}

export function formatDate(date: Date | string): string {
  const p = kstParts(date)
  return `${p.month}월 ${p.day}일 (${WEEKDAYS[p.weekday]})`
}

export function formatDateShort(date: Date | string): string {
  const p = kstParts(date)
  return `${p.month}.${p.day} ${WEEKDAYS[p.weekday]}`
}

export function formatDateTime(date: Date | string): string {
  return `${formatDate(date)} ${formatTime(date)}`
}

export function formatFullDate(date: Date | string): string {
  const p = kstParts(date)
  return `${p.year}. ${p.month}. ${p.day}.`
}

export function weekdayLabel(date: Date | string): string {
  return WEEKDAYS[kstParts(date).weekday] ?? ''
}

/** "방금", "5분 전", "3시간 전", "어제 14:00", "10월 3일 (금)"; future: "12분 후", "오늘 16:00". */
export function formatRelative(date: Date | string, now: Date = new Date()): string {
  const t = new Date(date).getTime()
  const diff = now.getTime() - t
  if (diff < 0) {
    const ahead = -diff
    if (ahead < HOUR) return `${Math.max(1, Math.round(ahead / MINUTE))}분 후`
    if (isSameKstDay(date, now)) return `오늘 ${formatTime(date)}`
    if (isSameKstDay(date, addDays(now, 1))) return `내일 ${formatTime(date)}`
    return formatDateTime(date)
  }
  if (diff < MINUTE) return '방금'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}분 전`
  if (isSameKstDay(date, now)) return `${Math.floor(diff / HOUR)}시간 전`
  if (isSameKstDay(date, addDays(now, -1))) return `어제 ${formatTime(date)}`
  return formatDate(date)
}

/** 754_000 -> "12:34", 3_754_000 -> "1:02:34". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m}분`
  return m === 0 ? `${h}시간` : `${h}시간 ${m}분`
}
