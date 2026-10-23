import type { AiCompetencySummary, Evaluation, Score } from '@/api/types'

import { round1 } from './utils'

/**
 * Per-competency digest of AI item scores: mean score (1 decimal), lowest confidence.
 * Only AI scores go in; interviewer scores are never part of it (FR-07: 합산하지 않음).
 */
export function summarizeAiScores(scores: readonly Score[]): AiCompetencySummary[] {
  const by = new Map<string, Score[]>()
  for (const s of scores) {
    if (s.evaluator_type !== 'ai') continue
    const list = by.get(s.competency) ?? []
    list.push(s)
    by.set(s.competency, list)
  }
  return [...by.entries()].map(([competency, list]) => ({
    competency,
    score: round1(list.reduce((sum, s) => sum + s.score, 0) / list.length),
    confidence: Math.min(...list.map((s) => s.confidence ?? 0)),
    item_count: list.length,
  }))
}

/** One row per competency with AI and each interviewer kept in separate fields. No totals. */
export interface CompetencyRow {
  competency: string
  ai: number | null
  aiConfidence: number | null
  /** interviewer id -> score (null: not submitted) */
  interviewers: Record<string, number | null>
}

export function buildCompetencyRows(evaluation: Evaluation): CompetencyRow[] {
  const names = evaluation.competency_set?.competencies.map((c) => c.name) ?? []
  const aiBy = new Map(evaluation.ai.summary.map((s) => [s.competency, s]))
  return names.map((competency) => {
    const ai = aiBy.get(competency)
    const interviewers: Record<string, number | null> = {}
    for (const ev of evaluation.interviewers) {
      const s = ev.scores.find((x) => x.competency === competency)
      interviewers[ev.interviewer.id] = s ? s.score : null
    }
    return {
      competency,
      ai: ai ? ai.score : null,
      aiConfidence: ai ? ai.confidence : null,
      interviewers,
    }
  })
}

export const LOW_CONFIDENCE = 0.6

export function confidenceLabel(c: number): string {
  if (c >= 0.8) return '높음'
  if (c >= LOW_CONFIDENCE) return '보통'
  return '낮음'
}
