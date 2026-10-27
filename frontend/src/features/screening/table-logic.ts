import type { ApplicationRow, ScreeningStatus } from '@/api/types'

export type StatusFilter = 'all' | ScreeningStatus
/** Where the application is now: 서류, a round by position (1 = 1차), or 최종. */
export type StepFilter = 'all' | 'screening' | 'final' | number
export type SortKey = 'fit' | 'pseudonym' | 'years' | 'created'
export interface Sort {
  key: SortKey
  dir: 'asc' | 'desc'
}

export function stepOf(r: ApplicationRow): Exclude<StepFilter, 'all'> {
  return r.stage.kind === 'round' ? r.stage.round!.position : r.stage.kind
}

export function filterRows(rows: readonly ApplicationRow[], status: StatusFilter, query: string, step: StepFilter = 'all'): ApplicationRow[] {
  const q = query.trim().toLowerCase()
  return rows.filter((r) => {
    if (status !== 'all' && r.screening?.status !== status) return false
    if (step !== 'all' && stepOf(r) !== step) return false
    if (!q) return true
    return r.candidate.pseudonym.toLowerCase().includes(q) || r.top_skills.some((s) => s.toLowerCase().includes(q))
  })
}

export function sortRows(rows: readonly ApplicationRow[], sort: Sort): ApplicationRow[] {
  const val = (r: ApplicationRow): number | string => {
    switch (sort.key) {
      case 'fit':
        return r.screening?.fit_score ?? -1
      case 'years':
        return r.years_experience ?? -1
      case 'created':
        return r.created_at
      case 'pseudonym':
        return r.candidate.pseudonym
    }
  }
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = val(a)
    const y = val(b)
    return (x < y ? -1 : x > y ? 1 : 0) * sign
  })
}

export function countByStatus(rows: readonly ApplicationRow[]): Record<StatusFilter, number> {
  const c: Record<StatusFilter, number> = { all: rows.length, passed: 0, hold: 0, rejected: 0 }
  for (const r of rows) if (r.screening) c[r.screening.status] += 1
  return c
}

/** Round filter options in order (서류, 1차, 2차 …, 최종) with how many rows are at each. */
export function stepOptions(rows: readonly ApplicationRow[]): { value: StepFilter; label: string; count: number }[] {
  const rounds = new Map<number, string>()
  for (const r of rows) for (const s of r.progress) if (s.round) rounds.set(s.round.position, s.round.label)
  const count = (v: StepFilter) => (v === 'all' ? rows.length : rows.filter((r) => stepOf(r) === v).length)
  const options: { value: StepFilter; label: string }[] = [
    { value: 'all', label: '전체' },
    { value: 'screening', label: '서류' },
    ...[...rounds.entries()].sort((a, b) => a[0] - b[0]).map(([position, label]) => ({ value: position, label })),
    { value: 'final', label: '최종' },
  ]
  return options.map((o) => ({ ...o, count: count(o.value) }))
}
