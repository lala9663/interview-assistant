import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { Evaluation, Score } from '@/api/types'
import { buildCompetencyRows, summarizeAiScores } from '@/lib/scoring'
import { renderPlain } from '@/test/render'

import { ScoreTable } from './score-views'

const bars = { '1': 'a', '2': 'b', '3': 'c', '4': 'd', '5': 'e' }

function score(p: Partial<Score> & Pick<Score, 'competency' | 'score' | 'evaluator_type'>): Score {
  return {
    id: Math.random().toString(36),
    qa_item_id: 'qa-1',
    evidence: p.evaluator_type === 'ai' ? '근거 인용' : null,
    confidence: p.evaluator_type === 'ai' ? 0.8 : null,
    evaluator_id: null,
    model: null,
    prompt_version: null,
    created_at: '2026-10-20T00:00:00Z',
    ...p,
  }
}

const aiScores = [
  score({ competency: '문제 해결', score: 4, evaluator_type: 'ai', confidence: 0.82 }),
  score({ competency: '문제 해결', score: 4, evaluator_type: 'ai', qa_item_id: 'qa-2', confidence: 0.55 }),
  score({ competency: '협업', score: 5, evaluator_type: 'ai' }),
]

const EV: Evaluation = {
  session: {
    id: 's1',
    application_id: 'a1',
    mode: 'remote',
    status: 'completed',
    scheduled_at: null,
    started_at: null,
    ended_at: null,
    has_recording: true,
    created_at: '2026-10-20T00:00:00Z',
  },
  candidate: { id: 'c1', pseudonym: 'CAND-0001' },
  posting: { id: 'p1', title: '공고' },
  competency_set: {
    id: 'cs1',
    posting_id: 'p1',
    version: 1,
    competencies: [
      { name: '문제 해결', description: '', bars },
      { name: '협업', description: '', bars },
    ],
    approved_by: null,
    approved_at: '2026-10-01T00:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
  },
  qa_items: [],
  ai: { status: 'completed', model: 'm', prompt_version: 'v', samples: 3, scores: aiScores, summary: summarizeAiScores(aiScores) },
  interviewers: [
    {
      interviewer: { id: 'iv1', employee_no: 'E1', name: '면접관A', job_family: null, department: null, created_at: '' },
      role: 'lead',
      submitted_at: '2026-10-20T01:00:00Z',
      scores: [
        score({ competency: '문제 해결', score: 2, evaluator_type: 'interviewer', evaluator_id: 'iv1' }),
        score({ competency: '협업', score: 3, evaluator_type: 'interviewer', evaluator_id: 'iv1' }),
      ],
    },
    {
      interviewer: { id: 'iv2', employee_no: 'E2', name: '면접관B', job_family: null, department: null, created_at: '' },
      role: 'panel',
      submitted_at: null,
      scores: [],
    },
  ],
}

describe('AI and interviewer scores are never summed', () => {
  it('summary aggregates AI scores only, with the lowest confidence', () => {
    const withInterviewer = [...aiScores, score({ competency: '문제 해결', score: 1, evaluator_type: 'interviewer' })]
    expect(summarizeAiScores(withInterviewer)).toEqual([
      { competency: '문제 해결', score: 4, confidence: 0.55, item_count: 2 },
      { competency: '협업', score: 5, confidence: 0.8, item_count: 1 },
    ])
  })

  it('rows keep AI and each interviewer in separate fields, with no total', () => {
    const rows = buildCompetencyRows(EV)
    expect(rows).toEqual([
      { competency: '문제 해결', ai: 4, aiConfidence: 0.55, interviewers: { iv1: 2, iv2: null } },
      { competency: '협업', ai: 5, aiConfidence: 0.8, interviewers: { iv1: 3, iv2: null } },
    ])
    for (const r of rows) expect(Object.keys(r).sort()).toEqual(['ai', 'aiConfidence', 'competency', 'interviewers'])
  })

  it('table shows AI 4.0 next to interviewer 2 and never their combination', () => {
    renderPlain(<ScoreTable ev={EV} hideAi={false} />)
    const row = screen.getByTestId('score-row-문제 해결')
    expect(within(row).getByTestId('ai-score')).toHaveTextContent('4.0')
    const human = within(row).getAllByTestId('interviewer-score')
    expect(human.map((c) => c.textContent)).toEqual(['2', '미제출'])
    // (4 + 2) / 2 = 3 and 4 + 2 = 6 must not appear anywhere.
    expect(within(row).queryByText(/^3(\.0)?$/)).toBeNull()
    expect(within(row).queryByText(/^6(\.0)?$/)).toBeNull()
    expect(screen.queryByText(/합계|종합|총점/, { selector: 'th' })).toBeNull()
    expect(screen.getByText(/합산하지 않습니다/)).toBeInTheDocument()
    expect(within(row).getByText(/낮음 · 0.55/)).toBeInTheDocument()
  })

  it('hiding AI removes the AI columns but keeps interviewer scores', () => {
    renderPlain(<ScoreTable ev={EV} hideAi />)
    expect(screen.queryByTestId('ai-score')).toBeNull()
    expect(screen.getAllByTestId('interviewer-score')[0]).toHaveTextContent('2')
  })
})
