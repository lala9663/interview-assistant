import type { ApplicationRow, ScreeningStatus } from '@/api/types'

export type StatusFilter = 'all' | ScreeningStatus
export type SortKey = 'fit' | 'pseudonym' | 'years' | 'created'
export interface Sort {
  key: SortKey
  dir: 'asc' | 'desc'
}

export function filterRows(rows: readonly ApplicationRow[], status: StatusFilter, query: string): ApplicationRow[] {
  const q = query.trim().toLowerCase()
  return rows.filter((r) => {
    if (status !== 'all' && r.screening?.status !== status) return false
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
