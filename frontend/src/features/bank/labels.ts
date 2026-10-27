import type { BankFamily, BankStatus } from '@/api/types'

export const BANK_STATUS_LABEL: Record<BankStatus, string> = { draft: '초안', approved: '승인', retired: '폐기' }

export const bankStatusVariant = (s: BankStatus) => (s === 'approved' ? 'success' : s === 'draft' ? 'warning' : 'outline')

export const roundLabel = (position: number | null) => (position === null ? '모든 차수' : `${position}차`)

export const ROUND_CHOICES: { value: string; label: string }[] = [
  { value: 'any', label: '모든 차수' },
  ...[1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n}차` })),
]

/** Competencies of a job family (bank, rubric and postings' approved dictionaries). */
export const competenciesOf = (families: BankFamily[], family: string) => families.find((f) => f.job_family === family)?.competencies ?? []

/** One example per line, blank lines dropped. */
export const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
