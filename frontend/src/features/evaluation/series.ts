import type { Evaluation } from '@/api/types'

/** Series colors: AI is always slot 1; interviewers take slots 2.. in panel order (lead first). */
export function seriesColor(i: number) {
  return `var(--series-${Math.min(i + 1, 6)})`
}

export interface Series {
  key: string
  label: string
  color: string
  kind: 'ai' | 'interviewer'
}

export function buildSeries(ev: Evaluation, hideAi: boolean): Series[] {
  const out: Series[] = []
  if (!hideAi) out.push({ key: 'ai', label: 'AI (참고)', color: seriesColor(0), kind: 'ai' })
  ev.interviewers.forEach((iv, i) =>
    out.push({ key: iv.interviewer.id, label: iv.interviewer.name, color: seriesColor(i + 1), kind: 'interviewer' }),
  )
  return out
}

