import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ApplicationRow, ProgressStep, ScreeningStatus, StepStatus } from '@/api/types'
import { endpoints } from '@/api/endpoints'
import { getDb } from '@/mocks/db'
import { renderPlain, renderRoute } from '@/test/render'

import ScreeningPage from './ScreeningPage.vue'
import ScreeningTable from './ScreeningTable.vue'
import { countByStatus, filterRows, sortRows, stepOptions } from './table-logic'

const R1 = { id: 'r1', position: 1, label: '1차', name: '직무 면접', is_last: false }
const R2 = { id: 'r2', position: 2, label: '2차', name: '임원 면접', is_last: true }

/** 서류 → 1차 → 2차 → 최종 for a row that is at `round` (0 = still 서류) with `status` there. */
function trail(screening: ScreeningStatus, round = 0, status: StepStatus | null = null): ProgressStep[] {
  const at = (n: number): StepStatus | null => (n < round ? 'passed' : n === round ? status : null)
  return [
    { kind: 'screening', round: null, status: screening, at: null, session_id: null },
    { kind: 'round', round: R1, status: screening === 'passed' ? (round === 0 ? 'waiting' : at(1)) : null, at: null, session_id: null },
    { kind: 'round', round: R2, status: at(2), at: null, session_id: null },
    { kind: 'final', round: null, status: round > 2 ? 'passed' : null, at: null, session_id: null },
  ]
}

function row(n: number, status: ScreeningStatus, fit: number, skills: string[] = [], progress = trail(status)): ApplicationRow {
  const stage = progress.find((s) => s.status !== 'passed') ?? progress.at(-1)!
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
    stage,
    progress,
    channel: n % 2 ? 'site' : 'upload',
    created_at: `2026-10-${String(n).padStart(2, '0')}T00:00:00Z`,
  }
}

const ROWS = [
  row(1, 'passed', 91, ['건식 식각'], trail('passed', 2, 'in_progress')),
  row(2, 'hold', 68, ['포토']),
  row(3, 'rejected', 40),
  row(4, 'hold', 72, ['Python']),
  row(5, 'passed', 80, [], trail('passed', 1, 'deciding')),
]

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

    await user.click(screen.getByRole('radio', { name: /서류 전체/ }))
    expect(screen.getAllByTestId('screening-row')).toHaveLength(5)
  })

  it('shows where each candidate is: a short trail, the round badge apart from the status chip', () => {
    renderPlain(ScreeningTable, { rows: ROWS, selectedId: null, onOpen: vi.fn() })
    const first = screen.getAllByTestId('screening-row').find((r) => within(r).queryByText('CAND-0001'))!
    expect(within(first).getByTestId('progress-trail')).toHaveAccessibleName('서류 통과, 1차 합격, 2차 진행 중')
    expect(within(first).getByTestId('round-badge')).toHaveTextContent('2차')
    expect(within(first).getByTestId('status-chip')).toHaveTextContent('진행 중')
    const fifth = screen.getAllByTestId('screening-row').find((r) => within(r).queryByText('CAND-0005'))!
    expect(within(fifth).getByTestId('status-chip')).toHaveTextContent('결정 대기')
  })

  it('filters by the round a candidate is in', async () => {
    const user = userEvent.setup()
    expect(stepOptions(ROWS).map((o) => [o.label, o.count])).toEqual([
      ['전체', 5],
      ['서류', 3],
      ['1차', 1],
      ['2차', 1],
      ['최종', 0],
    ])
    renderPlain(ScreeningTable, { rows: ROWS, selectedId: null, onOpen: vi.fn() })
    await user.click(within(screen.getByTestId('step-filter')).getByRole('radio', { name: /2차/ }))
    expect(screen.getAllByTestId('screening-row').map((r) => within(r).getByText(/CAND-/).textContent)).toEqual(['CAND-0001'])
  })

  it('shows how each application came in: the recruiting site or an upload', () => {
    renderPlain(ScreeningTable, { rows: ROWS, selectedId: null, onOpen: vi.fn() })
    const byPseudonym = Object.fromEntries(
      screen.getAllByTestId('screening-row').map((r) => [within(r).getByText(/CAND-/).textContent, within(r).getByTestId('channel-badge').textContent?.trim()]),
    )
    expect(byPseudonym).toEqual({ 'CAND-0001': '사이트 연동', 'CAND-0002': '직접 업로드', 'CAND-0003': '사이트 연동', 'CAND-0004': '직접 업로드', 'CAND-0005': '사이트 연동' })
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

describe('서류 업로드', () => {
  const pdf = () => new File(['%PDF-1.7'], '지원서.pdf', { type: 'application/pdf' })

  it('sends the file and form fields as multipart (the browser sets the boundary)', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 201, headers: { 'Content-Type': 'application/json' } }))
    await endpoints.uploadApplication('p-1', { file: pdf(), name: '가나다', phone: '010-0000-0000', email: '' })
    const [url, init] = fetchSpy.mock.calls[0]!
    expect(String(url)).toMatch(/\/api\/postings\/p-1\/applications$/)
    expect(init?.method).toBe('POST')
    const body = init?.body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect((body.get('file') as File).name).toBe('지원서.pdf')
    expect(body.get('name')).toBe('가나다')
    expect(body.get('phone')).toBe('010-0000-0000')
    expect(body.get('email')).toBeNull()
    expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
  })

  it('uploads from the screening page and opens the new application, pseudonym only', async () => {
    // jsdom's FormData cannot travel through Node's fetch, so the upload call itself is stubbed here.
    vi.spyOn(endpoints, 'uploadApplication').mockImplementation(async (postingId, body) => getDb().addUpload(postingId, body.file.name))
    const user = userEvent.setup()
    const P2 = 'b1d6a0c2-1f3e-4b8a-9c41-5e2f7a9d0002'
    await renderRoute(ScreeningPage, { path: '/screening/:postingId', url: `/screening/${P2}` })
    await screen.findAllByTestId('screening-row')

    await user.click(screen.getByRole('button', { name: '서류 업로드' }))
    const submit = screen.getByRole('button', { name: '올리고 선별' })
    expect(submit).toBeDisabled()
    await user.upload(screen.getByLabelText('지원 서류'), pdf())
    await user.type(screen.getByLabelText('이름'), '가나다')
    await user.click(submit)

    await waitFor(() => expect(screen.getAllByTestId('screening-row')).toHaveLength(10))
    const added = getDb().applications.at(-1)!
    expect(getDb().screeningOf(added.id)?.status).toBe('hold')
    expect(screen.getAllByText('CAND-0021').length).toBeGreaterThan(0)
    expect(screen.queryByText('가나다')).not.toBeInTheDocument()
  })
})
