import { screen, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ApplicationRow, ScreeningStatus } from '@/api/types'
import { renderPlain } from '@/test/render'

import ScreeningTable from './ScreeningTable.vue'
import { countByStatus, filterRows, sortRows } from './table-logic'

function row(n: number, status: ScreeningStatus, fit: number, skills: string[] = []): ApplicationRow {
  return {
    application_id: `app-${n}`,
    candidate: { id: `cand-${n}`, pseudonym: `CAND-${String(n).padStart(4, '0')}` },
    screening: {
      id: `scr-${n}`,
      application_id: `app-${n}`,
      fit_score: fit,
      rationale: '요약',
      status,
      model: null,
      prompt_version: null,
      created_at: '2026-10-01T00:00:00Z',
    },
    years_experience: n,
    top_skills: skills,
    stage: 'screening',
    created_at: `2026-10-${String(n).padStart(2, '0')}T00:00:00Z`,
  }
}

const ROWS = [row(1, 'passed', 91, ['건식 식각']), row(2, 'hold', 68, ['포토']), row(3, 'rejected', 40), row(4, 'hold', 72, ['Python']), row(5, 'passed', 80)]

describe('screening table logic', () => {
  it('filters by status and by pseudonym or skill', () => {
    expect(filterRows(ROWS, 'hold', '').map((r) => r.application_id)).toEqual(['app-2', 'app-4'])
    expect(filterRows(ROWS, 'all', 'python').map((r) => r.application_id)).toEqual(['app-4'])
    expect(filterRows(ROWS, 'all', 'cand-0003').map((r) => r.application_id)).toEqual(['app-3'])
    expect(filterRows(ROWS, 'passed', 'python')).toEqual([])
  })

  it('sorts by fit score and counts per status', () => {
    expect(sortRows(ROWS, { key: 'fit', dir: 'desc' }).map((r) => r.screening!.fit_score)).toEqual([91, 80, 72, 68, 40])
    expect(sortRows(ROWS, { key: 'pseudonym', dir: 'asc' })[0]!.candidate.pseudonym).toBe('CAND-0001')
    expect(countByStatus(ROWS)).toEqual({ all: 5, passed: 2, hold: 2, rejected: 1 })
  })
})

describe('<ScreeningTable>', () => {
  it('status filter shows only the matching candidates, pseudonyms only', async () => {
    const user = userEvent.setup()
    renderPlain(ScreeningTable, { rows: ROWS, selectedId: null, onOpen: vi.fn() })
    expect(screen.getAllByTestId('screening-row')).toHaveLength(5)

    await user.click(screen.getByRole('radio', { name: /보류/ }))
    const rows = screen.getAllByTestId('screening-row')
    expect(rows).toHaveLength(2)
    expect(rows.map((r) => within(r).getByText(/CAND-/).textContent)).toEqual(['CAND-0004', 'CAND-0002'])
    for (const r of rows) expect(within(r).getByText('보류')).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /탈락/ }))
    expect(screen.getAllByTestId('screening-row')).toHaveLength(1)

    await user.click(screen.getByRole('radio', { name: /전체/ }))
    expect(screen.getAllByTestId('screening-row')).toHaveLength(5)
  })

  it('shows an empty state with a reset when nothing matches', async () => {
    const user = userEvent.setup()
    renderPlain(ScreeningTable, { rows: ROWS, selectedId: null, onOpen: vi.fn() })
    await user.type(screen.getByRole('textbox', { name: '지원자 검색' }), '없는기술')
    expect(screen.getByText('조건에 맞는 지원자가 없습니다')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '필터 초기화' }))
    expect(screen.getAllByTestId('screening-row')).toHaveLength(5)
  })
})
