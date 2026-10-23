/** Week grid geometry: 09:00–19:00 KST, 1px per minute. */
export const DAY_START = 9 * 60
export const DAY_END = 19 * 60
export const PX_PER_MIN = 1
export const HOURS = Array.from({ length: (DAY_END - DAY_START) / 60 + 1 }, (_, i) => DAY_START / 60 + i)

/** Interviewer colors follow the entity (global order), slots 2.. so slot 1 (blue) stays the AI/brand color. */
export const colorOf = (index: number) => `var(--series-${(index % 5) + 2})`
